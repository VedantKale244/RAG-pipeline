"""Guardian: floors, staged failure lifecycle, tombstone (Spec §8).

The optimizer measures itself. ``check_after_cycle`` advances a strictly-ordered
stage machine on judged losses; ``check_floors`` compares the champion's live
rolling metrics against absolute floors; ``self_destruct`` shuts the subsystem
down permanently, archiving forensics before purging.

State machine::

    HEALTHY → WARNING(3) → ROLLBACK_OBSERVATION(5) → HIBERNATING(10) → TOMBSTONED(20 ∧ floor breach)

A successful promotion resets to HEALTHY from any non-terminal stage. Skipped
cycles ("skipped:*") neither increment nor reset the counter. No data for a
floor ⇒ not breached — a fresh install must not tombstone itself on day one.
"""
from __future__ import annotations

import gzip
import json
import logging
import time
from typing import TypedDict

from ..config import settings
from . import metrics, overrides, store

logger = logging.getLogger(__name__)

STAGE_HEALTHY = "HEALTHY"
STAGE_WARNING = "WARNING"
STAGE_ROLLBACK = "ROLLBACK_OBSERVATION"
STAGE_HIBERNATING = "HIBERNATING"
STAGE_TOMBSTONED = "TOMBSTONED"

_STAGE_COUNTER = {
    STAGE_HEALTHY: 0,
    STAGE_WARNING: 3,
    STAGE_ROLLBACK: 5,
    STAGE_HIBERNATING: 10,
    STAGE_TOMBSTONED: 20,
}

_STATE_STAGE = "lifecycle_stage"
_STATE_FAILURES = "consecutive_failures"
_STATE_DISABLED = "disabled"
_STATE_PAUSED = "paused"
_STATE_PAUSE_UNTIL = "pause_until"
_STATE_WAKE = "wake"

# 7-day live rolling window.
_ROLLING_WINDOW_S = 7 * 24 * 3600
# Feedback floor needs at least this many votes before it can count as breached.
_FEEDBACK_MIN_VOTES = 20

_RAGAS_FLOORS = {
    "faithfulness": 0.90,
    "answer_relevancy": 0.88,
    "context_precision": 0.85,
    "context_recall": 0.85,
}
_LATENCY_FLOOR_MS = 2500.0
_EDGE_FLOOR_FRACTION = 0.5


class FloorReport(TypedDict):
    breached: bool
    floors: dict[str, bool]   # name → breached


# --- Lifecycle ---------------------------------------------------------------

def get_lifecycle_stage() -> str:
    if store.get_tombstone():
        return STAGE_TOMBSTONED
    return store.get_state(_STATE_STAGE, STAGE_HEALTHY) or STAGE_HEALTHY


def _failures() -> int:
    raw = store.get_state(_STATE_FAILURES, "0") or "0"
    try:
        return int(raw)
    except ValueError:
        return 0


def _pause_until() -> float:
    raw = store.get_state(_STATE_PAUSE_UNTIL, "0") or "0"
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _stage_for(counter: int, floor_breach: bool) -> str:
    """Map the consecutive-failure counter to a stage, without skipping any.

    The counter is authoritative for the non-terminal stages; the tombstone
    additionally requires a live floor breach.
    """
    if counter >= 20 and floor_breach:
        return STAGE_TOMBSTONED
    if counter >= 10:
        return STAGE_HIBERNATING
    if counter >= 5:
        return STAGE_ROLLBACK
    if counter >= 3:
        return STAGE_WARNING
    return STAGE_HEALTHY


def check_after_cycle(outcome: str) -> str:
    """Advance the stage machine after one cycle. Returns the current stage.

    ``outcome`` is one of the experiment ladder's statuses. "skipped:*" is
    neutral (neither a failure nor a reset); "promoted*" / "rollback_resolved"
    resets; a judged loss increments.
    """
    if store.get_tombstone():
        return STAGE_TOMBSTONED

    if outcome.startswith("skipped"):
        return get_lifecycle_stage()
    if outcome.startswith("promoted") or outcome == "canary:win":
        store.set_state(_STATE_FAILURES, "0")
        store.set_state(_STATE_STAGE, STAGE_HEALTHY)
        return STAGE_HEALTHY

    # A judged loss.
    counter = _failures() + 1
    store.set_state(_STATE_FAILURES, str(counter))
    stage = _stage_for(counter, _any_floor_breached())
    _enter(stage)
    return stage


def _enter(stage: str) -> None:
    """Apply a stage's side effects as the lifecycle reaches it."""
    if stage == STAGE_ROLLBACK:
        _rollback_to_last_good()
        store.set_state(_STATE_PAUSE_UNTIL, str(time.time() + 6 * 3600))
    elif stage == STAGE_HIBERNATING:
        store.set_state(_STATE_PAUSE_UNTIL, str(time.time() + 24 * 3600))
    elif stage == STAGE_TOMBSTONED:
        self_destruct()
        return
    store.set_state(_STATE_STAGE, stage)
    store.record_activity(
        store.KIND_GUARDIAN,
        f"lifecycle entered {stage} (consecutive failures {_failures()})",
    )


# --- Floors ------------------------------------------------------------------

def _rollback_to_last_good() -> str | None:
    """Walk the lineage to the most recent version that passed all floors.

    Returns the restored version id, or None when the system falls back to the
    cold-start `.env` baseline (nothing ever passed). Retiring the current
    champion alone is what makes `.env` become active again.
    """
    current = store.get_champion_version()
    versions = store.get_all_versions()
    candidates = [
        v for v in versions
        if v["status"] in ("retired", "champion") and v["version"] != current
    ]
    for v in candidates:  # newest first (get_all_versions is newest-first)
        if not _floors_for(v["version"])["breached"]:
            store.promote(v["version"], v.get("composite_score") or 0.0)
            logger.warning("Guardian rolled back to last-good %s", v["version"])
            return v["version"]
    if current:
        # Retire the failing champion, leaving zero champions: the whole system
        # falls back to the `.env` cold-start baseline.
        store.update_version(current, status="retired")
        logger.warning("No good ancestor; falling back to .env cold-start baseline")
    return None


def _floors_for(version: str) -> FloorReport:
    """Compute floor breaches for one version's live 7-day rolling metrics."""
    since = time.time() - _ROLLING_WINDOW_S
    floor_flags: dict[str, bool] = {}

    for metric, floor in _RAGAS_FLOORS.items():
        samples = store.metrics_since(metric, since, version)
        if not samples:
            floor_flags[metric] = False  # never measured ⇒ unknown, not breached
        else:
            floor_flags[metric] = (sum(samples) / len(samples)) < floor

    lat = metrics.p95(store.metrics_since("latency_ms", since, version))
    floor_flags["latency_p95"] = bool(lat is not None and lat > _LATENCY_FLOOR_MS)

    up = int(store.count_metrics(version, "feedback_up"))
    down = int(store.count_metrics(version, "feedback_down"))
    votes = up + down
    if votes >= _FEEDBACK_MIN_VOTES:
        floor_flags["feedback"] = metrics.wilson_lower_bound(up, down) < 0.70
    else:
        floor_flags["feedback"] = False  # not enough votes ⇒ not breached

    floor_flags["edges"] = _edge_floor_breached()

    return FloorReport(breached=any(floor_flags.values()), floors=floor_flags)


def _edge_floor_breached() -> bool:
    baseline = store.get_baseline("edge_baseline")
    if not baseline:
        return False  # never pinned ⇒ unknown, not breached
    try:
        pinned = float(baseline)
    except ValueError:
        return False
    current = _current_edge_count()
    if current is None:
        return False  # graph unreadable ⇒ unknown, not breached
    return current < pinned * _EDGE_FLOOR_FRACTION


def _current_edge_count() -> float | None:
    """Live RELATED edge count. Wire to api.admin._get_admin_stats()."""
    try:
        from ..api.admin import _get_admin_stats
        return float(_get_admin_stats().get("total_edges") or 0)
    except Exception:
        try:
            from ..core.clients import neo4j_driver
            with neo4j_driver().session() as session:
                row = session.run("MATCH ()-[r:RELATED]->() RETURN count(r) AS cnt").single()
                return float(row["cnt"] if row else 0)
        except Exception:
            return None


def check_floors() -> FloorReport:
    """Check floors against the current champion. No champion ⇒ no floors ⇒ OK."""
    champion = store.get_champion_version()
    if not champion:
        return FloorReport(breached=False, floors={})
    return _floors_for(champion)


def _any_floor_breached() -> bool:
    return check_floors()["breached"]


# --- Self-destruct (Spec §8.3) ----------------------------------------------

def self_destruct(reason: str = "live quality fell below floors") -> None:
    """Terminal: archive, purge, tombstone, disable. Order matters."""
    if store.get_tombstone():
        return

    restored = _rollback_to_last_good()
    final_metrics = _champion_summary()
    failure_history = _failure_history()

    _archive_history()

    store.purge_experiments()
    store.insert_tombstone(reason, final_metrics, failure_history, restored)
    store.set_state(_STATE_DISABLED, "true")
    overrides.uninstall()
    store.set_state(_STATE_STAGE, STAGE_TOMBSTONED)
    store.record_activity(
        store.KIND_GUARDIAN,
        f"SELF-DESTRUCT: {reason} (restored {restored or 'cold-start baseline'})",
        restored,
    )
    logger.error("selfopt self-destructed: %s", reason)


def _champion_summary() -> dict:
    version = store.get_champion_version()
    if not version:
        return {}
    row = store.get_version(version) or {}
    return {
        "version": row.get("version"),
        "composite_score": row.get("composite_score"),
        "parameters": row.get("parameters_json", {}),
    }


def _failure_history() -> list[dict]:
    out = []
    for r in store.list_repairs(limit=10):
        out.append({
            "fingerprint": r["fingerprint"],
            "endpoint": r["endpoint"],
            "count": r["count"],
            "last_seen": r["last_seen"],
        })
    return out


def _archive_history() -> None:
    """Gzip the experiment rows into a single archive blob (before purge)."""
    payload = {
        "archived_at": time.time(),
        "config_versions": store.get_all_versions(),
        "tunable_stats": store.get_all_tunable_stats(),
        "repairs": store.list_repairs(limit=500),
    }
    store.insert_archive(gzip.compress(json.dumps(payload, default=str).encode("utf-8")))