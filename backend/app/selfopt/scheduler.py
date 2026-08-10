"""Scheduler: the single ``asyncio`` task driving the three cycle triggers (§6).

No Celery, no cron. ``loop()`` wakes every ``tick`` seconds, evaluates the
event/schedule/metric-drop triggers, runs a judged cycle when one fires, then
hands the outcome to the guardian. Reading/writing all happen on the same
background thread, so the shared store connection is single-caller here.
"""
from __future__ import annotations

import asyncio
import logging
import time

from ..config import settings
from . import experiment, guardian, rebuild, store

logger = logging.getLogger(__name__)

_EVENT_QUERY_THRESHOLD = 200          # spec §6: 200 queries since last cycle
_SCHEDULE_FLOOR_S = 3600              # 1h floor between cycles
_SCHEDULE_CEILING_S = 6 * 3600        # 6h idle → run anyway
_METRIC_DROP_FACTOR = 0.97            # current < 0.97 × rolling baseline → cycle
_BASELINE_WINDOW_DAYS = 7
_BASELINE_MIN_SAMPLES = 10
_QUERY_COUNTER_KEY = "queries_since_cycle"
_LAST_CYCLE_KEY = "last_cycle_at"


def module_enabled() -> bool:
    return settings.selfopt_enabled and store.get_tombstone() is None


def enabled() -> bool:
    return module_enabled()


def note_query() -> int:
    """Increment the in-flight query counter; returns the new count."""
    cur = int(store.get_state(_QUERY_COUNTER_KEY) or 0) + 1
    store.set_state(_QUERY_COUNTER_KEY, str(cur))
    return cur


def _mark_cycle_started() -> None:
    store.set_state(_LAST_CYCLE_KEY, str(time.time()))
    store.set_state(_QUERY_COUNTER_KEY, "0")


def _last_cycle_at() -> float | None:
    raw = store.get_state(_LAST_CYCLE_KEY)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def event_trigger() -> bool:
    """200+ queries accumulated since the last cycle."""
    return int(store.get_state(_QUERY_COUNTER_KEY) or 0) >= _EVENT_QUERY_THRESHOLD


def schedule_trigger(now: float | None = None) -> bool:
    """Floor of 1h between cycles; ceiling of 6h idle → run anyway. No prior
    cycle means the ceiling is never hit — a fresh system waits for its first
    real trigger rather than immediately spinning a cycle."""
    t = now or time.time()
    last = _last_cycle_at()
    if last is None:
        return False
    elapsed = t - last
    return elapsed >= _SCHEDULE_CEILING_S or elapsed < 0


def _metric_drop_trigger(__unused=None) -> bool:
    """Current champion composite < 0.97 × 7-day rolling baseline → immediate cycle."""
    champion_version = store.get_champion_version()
    if champion_version is None:
        return False
    since = time.time() - _BASELINE_WINDOW_DAYS * 86400
    samples = store.metrics_since("composite", since, champion_version)
    if len(samples) < _BASELINE_MIN_SAMPLES:
        return False  # not enough history to call a drop (§6)
    baseline = sum(samples) / len(samples)
    current = _latest_composite(champion_version)
    if current is None:
        return False
    return current < baseline * _METRIC_DROP_FACTOR


def _latest_composite(version: str) -> float | None:
    recent = store.recent_metrics(version, "composite", limit=3)
    return recent[0] if recent else None


def evaluate_triggers(now: float | None = None) -> list[str]:
    """Which triggers want a cycle right now."""
    fired = []
    if event_trigger():
        fired.append("event")
    if schedule_trigger(now):
        fired.append("schedule")
    if _metric_drop_trigger():
        fired.append("metric_drop")
    return fired


def tripped(now: float | None = None) -> bool:
    return bool(evaluate_triggers(now))


def _golden_samples() -> list[dict]:
    """Source of the offline golden set. Returns empty when no curated set is
    configured — the cycle then degrades to ``skipped:no-golden-set`` (§9).
    Replace with whatever golden-set source production exposes."""
    try:
        from ..core import golden  # deferred; None if the project has no golden module
        return list(golden.load() or [])
    except Exception:
        return []


async def tick(now: float | None = None) -> dict:
    """One background pass. Runs a cycle iff a trigger fired (or poison pill).

    Returns a small status dict for logging/monitoring.
    """
    if not enabled():
        return {"status": "disabled", "version": None}

    if not tripped(now):
        return {"status": "no-op", "version": None}
    fired = evaluate_triggers()
    store.record_activity("trigger", "cycle triggered by: " + ", ".join(fired))
    _mark_cycle_started()

    golden = _golden_samples()
    result = await asyncio.to_thread(experiment.run_cycle, golden)
    guardian.check_after_cycle(result.get("status", ""))
    maybe_rebuild(result)
    return result


_REBUILD_KNOBS = {"chunk_size", "chunk_overlap", "entity_match_threshold", "graph_confidence_threshold"}


def maybe_rebuild(result: dict) -> None:
    """After a promotion that touched data-layer knobs, schedule a shadow rebuild
    if the 24h fence is clear (real re-chunking is a call-back to ingest)."""
    if result.get("status") not in {"promoted:first", "promoted"}:
        return
    changes = (result.get("changes") or {})
    if set(changes.get("perturbed", [])) & _REBUILD_KNOBS and rebuild.can_rebuild():
        rebuild.mark_rebuilt()


async def loop() -> None:
    """Sliceable background loop; keeps running until the process dies."""
    while True:
        try:
            await asyncio.sleep(settings.selfopt_tick_seconds)
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("selfopt scheduler tick failed; continuing")


def start(loop_obj: asyncio.AbstractEventLoop) -> asyncio.Task | None:
    """Begin the background task inside the FastAPI lifespan."""
    if not enabled():
        logger.info("selfopt scheduler NOT started (disabled or tombstoned)")
        return None
    store.record_activity(
        store.KIND_SYSTEM,
        f"scheduler started (tick {settings.selfopt_tick_seconds}s; champion "
        f"{store.get_champion_version() or 'none → .env baseline'})",
    )
    return loop_obj.create_task(loop())