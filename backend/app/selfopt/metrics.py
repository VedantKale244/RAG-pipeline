"""Metrics & scoring for the self-optimization subsystem.

Collects the three signal sources — RAGAS quality, request latency, human
feedback — into one scorecard, and implements the improvement rule that decides
whether a challenger wins.

Spec §4::

    composite = 0.50 * quality + 0.30 * latency_score + 0.20 * feedback
    latency_score = clamp(1 - p95_ms / 2500, 0, 1)
    feedback       = Wilson lower bound at 95% confidence

``strict_ragas`` is the optimizer's verified-judge path. It refuses to score on
any fallback: without a valid GROQ key it raises immediately, and a result
missing any of the four judges metrics is treated as unverified rather than
optimized against. The live ``/eval`` endpoint keeps its existing fallback; only
the optimizer bypasses it.
"""
from __future__ import annotations

import math
import time
from typing import TypedDict

from ..config import settings
from ..eval import ragas_eval
from . import store

# Re-export so experiment.py can raise/import it without a second dependency.
RagasUnavailable = ragas_eval.RagasUnavailable

# Composite weights — tuned once, used everywhere, never drifted.
_W_QUALITY = 0.50
_W_LATENCY = 0.30
_W_FEEDBACK = 0.20

# Improvement rule (Spec §4.3).
_MARGIN = 0.005
_MAX_REGRESSION = 0.02

# Selfopt-only judge timeout. The optimizer is willing to pay ~15s for a real
# judge (the legacy 1.5s made every run fall back to the clamped scorer).
_SELFOPT_RAGAS_TIMEOUT_S = 15.0


class QualityMetrics(TypedDict):
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float


class Scorecard(TypedDict):
    composite: float
    quality: float
    latency_score: float
    feedback: float
    quality_metrics: QualityMetrics
    composite_history: list[float]
    latency_p95_ms: float | None


def p95(values: list[float]) -> float | None:
    """95th percentile. None for an empty series (unmeasured ≠ 0)."""
    if not values:
        return None
    s = sorted(values)
    k = math.ceil(0.95 * len(s)) - 1
    return float(s[max(0, k)])


def latency_score(p95_ms: float | None) -> float:
    """clamp(1 - p95/2500, 0, 1). Unmeasured → p95=2500 → 0.0, never a free 1.0."""
    p = p95_ms if p95_ms is not None else _LATENCY_FLOOR_MS
    return max(0.0, min(1.0, 1.0 - p / _LATENCY_FLOOR_MS))


_LATENCY_FLOOR_MS = 2500.0


def wilson_lower_bound(positive: int, negative: int, z: float = 1.96) -> float:
    """Wilson score lower bound at 95% confidence.

    3 votes at 100% must not outrank 200 votes at 85%; the bound tightens with
    sample size. Zero votes → 0.0.
    """
    n = positive + negative
    if n == 0:
        return 0.0
    phat = positive / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = phat + z2 / (2 * n)
    half = z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))
    return max(0.0, min(1.0, (centre - half) / denom))


def composite(quality: float, latency: float, feedback: float) -> float:
    """Weighted composite per Spec §4.1."""
    return (
        _W_QUALITY * quality
        + _W_LATENCY * latency
        + _W_FEEDBACK * feedback
    )


def _recent(version: str, metric: str, limit: int = 200) -> list[float]:
    return store.recent_metrics(version, metric, limit)


def _quality_mean(version: str, metrics_seq: list[str]) -> float:
    """Mean of the given RAGAS metrics, NaN-agnostic. Unmeasured → neutral."""
    samples = []
    for m in metrics_seq:
        for v in _recent(version, m, 200):
            if v == v:  # not NaN
                samples.append(v)
    return sum(samples) / len(samples) if samples else _NEUTRAL_QUALITY


_NEUTRAL_QUALITY = 0.0


def scorecard(version: str) -> Scorecard:
    """Assemble a version's scorecard from its stored rolling metrics.

    ``quality`` is the mean of the four RAGAS metrics, ``latency_score`` from the
    stored latency p95, ``feedback`` the Wilson bound from up/down votes.
    """
    quality_metrics: QualityMetrics = {
        "faithfulness": _quality_mean(version, ["faithfulness"]),
        "answer_relevancy": _quality_mean(version, ["answer_relevancy"]),
        "context_precision": _quality_mean(version, ["context_precision"]),
        "context_recall": _quality_mean(version, ["context_recall"]),
    }
    q = _quality_mean(version, list(quality_metrics))
    lat_p95 = p95(_recent(version, "latency_ms", 200))
    lat = latency_score(lat_p95)
    up = int(store.count_metrics(version, "feedback_up"))
    down = int(store.count_metrics(version, "feedback_down"))
    fb = wilson_lower_bound(up, down)
    return Scorecard(
        composite=composite(q, lat, fb),
        quality=q,
        latency_score=lat,
        feedback=fb,
        quality_metrics=quality_metrics,
        composite_history=_recent(version, "composite", 100),
        latency_p95_ms=lat_p95,
    )


def record_request(version: str, latency_ms: float) -> None:
    """Record one request's elapsed time for the version's latency bucket."""
    store.record_metric(version, "latency_ms", float(latency_ms))


def record_vote(version: str, positive: bool) -> None:
    """Record one thumbs up/down for the version's feedback bucket."""
    store.record_metric(version, "feedback_up" if positive else "feedback_down", 1.0)


def record_quality(version: str, metrics: QualityMetrics) -> None:
    """Record one RAGAS scoring run for the version (verified path only)."""
    for key, value in metrics.items():
        store.record_metric(version, key, float(value))


def is_improvement(
    champion: Scorecard, challenger: Scorecard
) -> tuple[bool, str]:
    """Both gates must pass: composite margin AND no >2% metric regression.

    The weighted sum alone lets a challenger trade faithfulness away to buy
    latency. Gate 2 rejects any single judge metric that regressed more than 2%
    relative to the champion.
    """
    margin_ok = challenger["composite"] > champion["composite"] + _MARGIN
    if not margin_ok:
        return False, f"no composite margin ({challenger['composite']:.4f} <= {champion['composite']:.4f} + {_MARGIN})"

    ce = champion["quality_metrics"]
    ne = challenger["quality_metrics"]
    for name in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
        old = ce.get(name)
        new = ne.get(name)
        if old is None or new is None or old <= 0:
            continue
        if new < old * (1 - _MAX_REGRESSION):
            return False, f"{name} regressed {new:.4f} vs {old:.4f} (>2%)"
    return True, "passes both gates"


def strict_ragas(samples: list[dict], version_id: str) -> dict:
    """Raises ``RagasUnavailable`` if no judge key is configured, or if the result
    is missing any of the four judge metrics — i.e. whenever the answer would
    have been clamped, not judged. The reward value: a challenger must not be
    scored against the 0.90-faithfulness fallback floor.
    """
    ragas_eval._require_ragas_key()  # raises RagasUnavailable when key absent
    timeout_backup = settings.ragas_timeout_s
    try:
        settings.ragas_timeout_s = _SELFOPT_RAGAS_TIMEOUT_S
        result = ragas_eval.run_eval(samples, user_id=version_id or "selfopt")
    finally:
        settings.ragas_timeout_s = timeout_backup
    scores = result.get("scores") or {}
    missing = [k for k in ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
               if k not in scores or scores.get(k) is None]
    if missing:
        raise RagasUnavailable(
            "no verified judge scores for " + ", ".join(missing)
        )
    return result