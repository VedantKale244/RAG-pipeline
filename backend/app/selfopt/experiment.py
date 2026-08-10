"""The engine: proposals + the promotion ladder (Spec §5).

``propose`` produces a challenger — 1–3 tunables perturbed ±5–20%, weighted by
each knob's Beta posterior mean, validated so a bad challenger never reaches an
experiment. ``run_cycle`` walks the ladder under a single-experiment lock:
offline gate over the golden set → canary → promote or roll back. Oscillation
suppression (Spec §5.7) runs on the promotion trail.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time

from ..config import settings
from . import metrics, overrides, store

logger = logging.getLogger(__name__)

_OSC_HISTORY_KEY = "oscillation_history"
_OSC_BAND = 0.05          # within-5% of the max ⇒ "same place"
_OSC_FROZEN_CYCLES = 5    # exclusive for the next 5 cycles


# --- Canary routing (Spec §5.3) ----------------------------------------------

def canary_bucket(user_id: str, version: str) -> bool:
    """Deterministic, sticky ~15% canary. Same (user, version) is always in
    (or out of) the bucket, so no mid-conversation flipping."""
    digest = hashlib.sha256(f"{user_id}{version}".encode()).digest()
    return (digest[0] % 100) < max(1, settings.selfopt_canary_percent)


# --- Beta-weighted stats -----------------------------------------------------

def _posterior_mean(field: str) -> float:
    st = store.get_tunable_stat(field) or {}
    wins = float(st.get("wins", 0) or 0)
    attempts = float(st.get("attempts", 0) or 0)
    return (wins + 1) / (attempts + 2)


def _is_frozen(field: str) -> bool:
    st = store.get_tunable_stat(field) or {}
    return float(st.get("frozen_until", 0) or 0) > time.time()


def _champion_or_baseline() -> dict:
    """Champion params, with any tunable the champion never touched backfilled
    from the `.env` baseline so the proposal search spans the whole whitelist
    (a 2-knob champion must still be able to try a 14th knob)."""
    merged = {name: getattr(settings, name) for name in overrides.TUNABLES}
    champion = store.get_champion()
    if champion:
        merged.update({k: v for k, v in champion.items() if k in overrides.TUNABLES})
    return merged


def _clamp(value, lo, hi, is_int):
    if is_int:
        return max(int(lo), min(int(hi), int(round(value))))
    return max(lo, min(hi, value))


def _weighted_sample(pool: list, count: int) -> list:
    """`count` distinct fields from `pool`, weighted by posterior mean.

    `random.choices(k=3)` can return the same knob three times — reporting a
    1-field challenger as a 3-field one. Sampling without replacement keeps the
    lineage report honest and the search broad.
    """
    pool = list(pool)
    random.shuffle(pool)
    result: list = []
    while pool and len(result) < count:
        weights = [_posterior_mean(f) for f in pool]
        total = sum(weights)
        r = random.uniform(0.0, total)
        acc = 0.0
        idx = len(pool) - 1
        for i, w in enumerate(weights):
            acc += w
            if r <= acc:
                idx = i
                break
        result.append(pool.pop(idx))
    return result


def propose() -> dict | None:
    """Propose one validated challenger, or None when nothing is worth trying.

    Moves are ±5–20% of the current value, snapped to the field's range, ints
    rounded. Frozen knobs are excluded. A no-op (every sampled move clamps back
    to the current value) yields None, never a phantom cycle.
    """
    base = _champion_or_baseline()
    candidates = [f for f in overrides.TUNABLES if not _is_frozen(f)]
    if not candidates:
        return None

    k = random.randint(1, min(3, len(candidates)))
    chosen = _weighted_sample(candidates, k)

    params = dict(base)
    deltas: dict[str, str] = {}
    perturbed: list[str] = []
    for name in chosen:
        lo, hi, is_int = overrides.TUNABLES[name]
        cur = params.get(name)
        if cur is None:
            continue
        sign = random.choice((-1.0, 1.0))
        pct = sign * random.uniform(0.05, 0.20)
        new = _clamp(cur * (1.0 + pct), lo, hi, is_int)
        if new == cur:
            continue
        params[name] = new
        rel = (new - cur) / cur * 100.0 if cur else 0.0
        deltas[name] = f"{rel:+.1f}%"
        perturbed.append(name)

    if not perturbed:
        return None
    try:
        overrides.validate(params)
    except ValueError:
        return None
    return {"params": params, "changes": {"perturbed": perturbed, "deltas": deltas}}


def _new_version(parent: str | None) -> str:
    return f"v{int(time.time() * 1000)}"


# --- Oscillation suppression (Spec §5.7) -------------------------------------

def _osc_history() -> list[dict]:
    raw = store.get_state(_OSC_HISTORY_KEY)
    try:
        return json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []


def _append_osc(entry: dict) -> None:
    store.set_state(_OSC_HISTORY_KEY, json.dumps((_osc_history() + [entry])[-30:]))


def check_oscillation(field: str, new_value: float) -> bool:
    """Process one promotion's field→value. True if the knob is oscillating.

    A field appearing ≥3 times in its trail whose values span ≤5% of the largest
    value is A→B→A→B→A'ing: halve its Beta `wins` and freeze it for 5 cycles.
    """
    _append_osc({"field": field, "value": float(new_value)})
    trail = [e["value"] for e in _osc_history() if e.get("field") == field][-3:]
    if len(trail) < 3:
        return False
    mx = max(trail)
    if mx == 0:
        return False
    if (max(trail) - min(trail)) > _OSC_BAND * mx:
        return False
    st = store.get_tunable_stat(field) or {}
    store.update_tunable_stat(
        field,
        wins=float(st.get("wins", 0) or 0) / 2,
        frozen_until=time.time() + _OSC_FROZEN_CYCLES * settings.selfopt_tick_seconds,
    )
    logger.warning("%s oscillating, temporarily excluded", field)
    return True


# --- Scorecard helper --------------------------------------------------------

def _scorecard_from_ragas(ragas_scores: dict, version: str) -> metrics.Scorecard:
    """Build a Scorecard from a strict RAGAS run's four judge metrics. Latency +
    feedback are gathered only after a challenger reaches canary, so they start
    neutral here.
    """
    q = (
        ragas_scores["faithfulness"]
        + ragas_scores["answer_relevancy"]
        + ragas_scores["context_precision"]
        + ragas_scores["context_recall"]
    ) / 4
    return metrics.Scorecard(
        composite=metrics.composite(q, 0.0, 0.0),
        quality=q,
        latency_score=metrics.latency_score(None),
        feedback=0.0,
        quality_metrics={
            "faithfulness": ragas_scores["faithfulness"],
            "answer_relevancy": ragas_scores["answer_relevancy"],
            "context_precision": ragas_scores["context_precision"],
            "context_recall": ragas_scores["context_recall"],
        },
        composite_history=[],
        latency_p95_ms=None,
    )


def record_attempt(perturbed: list[str], won: bool) -> None:
    """Increment Beta counters: a win adds to both, a loss only to attempts."""
    for f in perturbed:
        st = store.get_tunable_stat(f) or {}
        wins = float(st.get("wins", 0) or 0)
        attempts = float(st.get("attempts", 0) or 0)
        store.update_tunable_stat(f, wins=wins + (1.0 if won else 0.0), attempts=attempts + 1.0)


def promote(version: str, composite: float, perturbed: list[str]) -> None:
    """Promote a canary winner: atomic swap, seed Beta counters, oscillation
    trail update.
    """
    store.promote(version, composite)
    store.update_version(version, status="champion")
    for f in perturbed:
        record_attempt([f], won=True)
        row = store.get_version(version) or {}
        value = row.get("parameters_json", {}).get(f)
        if value is not None:
            check_oscillation(f, value)


def rollback(version: str, reason: str) -> None:
    store.update_version(version, status="rolled_back", rolled_back_at=time.time(), rollback_reason=reason)
    store.record_activity(
        store.KIND_ROLLBACK,
        f"rolled back: {reason}",
        version,
    )


# --- The ladder --------------------------------------------------------------

def run_cycle(golden_samples: list[dict], *, judge=None) -> dict:
    """Run one optimization ladder. ``judge`` is injectable for tests; the
    default is ``metrics.strict_ragas`` (which raises ``RagasUnavailable`` when
    no verified judge exists). Returns a status/version dict the guardian maps
    to lifecycle transitions; the "skipped:*" statuses are neutral (neither a
    win nor a failure).
    """
    holder = f"cycle-{os.getpid()}"
    if not store.acquire_lock(holder):
        return {"status": "skipped:lock-held", "version": None}
    try:
        result = _cycle_once(golden_samples, judge or metrics.strict_ragas)
        store.record_activity(
            store.KIND_CYCLE,
            f"cycle → {result.get('status', '?')}"
            + (f" (reason: {result.get('reason')})" if result.get("reason") else ""),
            result.get("version"),
        )
        return result
    finally:
        store.release_lock(holder)


def _cycle_once(golden: list[dict], judge) -> dict:
    if not golden:
        # Nothing to score against — correct, not a failure (a no-op cycle).
        return {"status": "skipped:no-golden-set", "version": None}

    champion_version = store.get_champion_version()
    proposal = propose()
    if not proposal:
        return {"status": "skipped:no-proposal", "version": None}

    version = _new_version(champion_version)
    store.insert_version(version, champion_version, proposal["params"], proposal["changes"])

    try:
        result = judge(golden, version)
    except metrics.RagasUnavailable:
        return {"status": "skipped:no-judge", "version": version}

    ragas_scores = (result or {}).get("scores") or {}
    required = {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}
    if not required <= set(ragas_scores):
        return {"status": "skipped:no-judge", "version": version}

    competitor = _scorecard_from_ragas(ragas_scores, version)
    if champion_version is None:
        # First champion: nothing offline to beat, promote straight to champion.
        store.update_version(version, status="offline_pass")
        promote(version, competitor["composite"], proposal["changes"]["perturbed"])
        return {"status": "promoted:first", "version": version}

    champion = metrics.scorecard(champion_version)
    ok, reason = metrics.is_improvement(champion, competitor)
    if not ok:
        store.update_version(version, status="offline_fail", rollback_reason=reason)
        return {"status": "offline_fail", "version": version, "reason": reason}

    store.update_version(version, status="offline_pass")
    return {"status": "canary:pending", "version": version}