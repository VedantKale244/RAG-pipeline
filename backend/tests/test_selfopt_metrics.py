"""Tests for the scorecard math, strict-judge gate, and the improvement rule."""
from __future__ import annotations

import pytest

from app.config import settings
from app.eval import ragas_eval
from app.selfopt import metrics
from app.selfopt.metrics import (
    RagasUnavailable,
    Scorecard,
    composite,
    is_improvement,
    latency_score,
    p95,
    scorecard,
    strict_ragas,
    wilson_lower_bound,
)


def _scorecard(comp, q, lat, fb, qm=None) -> Scorecard:
    return Scorecard(
        composite=comp,
        quality=q,
        latency_score=lat,
        feedback=fb,
        quality_metrics=qm
        or {
            "faithfulness": 0.9,
            "answer_relevancy": 0.9,
            "context_precision": 0.9,
            "context_recall": 0.9,
        },
        composite_history=[],
        latency_p95_ms=None,
    )


def test_wilson_penalizes_small_samples():
    # 3/3 perfect is *not* ranked above 200/235.
    small = wilson_lower_bound(3, 0)
    large = wilson_lower_bound(200, 35)
    assert small < 1.0
    assert small < large
    assert wilson_lower_bound(200, 0) > small


def test_wilson_zero_votes():
    assert wilson_lower_bound(0, 0) == 0.0
    assert wilson_lower_bound(0, 10) == 0.0


def test_latency_clamps_both_ends():
    assert latency_score(0) == 1.0
    assert latency_score(2500) == 0.0
    assert latency_score(5000) == 0.0
    assert latency_score(1250) == pytest.approx(0.5)


def test_unmeasured_latency_is_not_a_free_one():
    # No requests bucketed ⇒ treated as at the floor ⇒ 0.0, not an incentive.
    assert latency_score(None) == 0.0


def test_composite_weights():
    assert composite(1.0, 1.0, 1.0) == pytest.approx(1.0)
    assert composite(1.0, 0.0, 0.0) == pytest.approx(0.5)
    assert composite(0.0, 1.0, 0.0) == pytest.approx(0.3)
    assert composite(0.0, 0.0, 1.0) == pytest.approx(0.2)


def test_p95_empty_is_none():
    assert p95([]) is None


def test_p95_percentile():
    vals = list(range(1, 21))  # 1..20
    assert p95(vals) == 19.0  # ceil(0.95*20)=19th largest
    assert p95([1, 5, 5, 5, 100, 100, 100]) == 100.0


def test_scorecard_assembles_from_store(tmp_path, monkeypatch):
    from app.selfopt import store
    db = tmp_path / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db), raising=False)
    store._reset_conn()
    store.init_db()
    try:
        store.record_metric("v1", "faithfulness", 0.94)
        store.record_metric("v1", "answer_relevancy", 0.92)
        store.record_metric("v1", "context_precision", 0.9)
        store.record_metric("v1", "context_recall", 0.9)
        store.record_metric("v1", "latency_ms", 1000.0)
        store.record_metric("v1", "feedback_up", 1.0)
        store.record_metric("v1", "feedback_up", 1.0)
        store.record_metric("v1", "feedback_down", 1.0)

        sc = scorecard("v1")
        assert sc["quality_metrics"]["faithfulness"] == 0.94
        assert sc["latency_score"] == pytest.approx(1.0 - 1000 / 2500)
        assert sc["feedback"] > 0
    finally:
        store._reset_conn()


def test_strict_ragas_returns_scorecard_metrics(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "", raising=False)
    res = strict_ragas([{"question": "q?", "ground_truth": "a"}], "v1")
    assert isinstance(res, dict)
    assert "scores" in res




def test_is_improvement_needs_margin():
    champion = _scorecard(0.60, 0.7, 0.5, 0.5)
    tied = _scorecard(0.604, 0.7, 0.5, 0.5)  # +0.004 < 0.005 margin
    ok, reason = is_improvement(champion, tied)
    assert not ok


def test_is_improvement_passes_on_real_win():
    champion = _scorecard(0.60, 0.7, 0.5, 0.5)
    winner = _scorecard(0.63, 0.75, 0.5, 0.5)
    ok, _ = is_improvement(champion, winner)
    assert ok


def test_is_improvement_rejects_regression():
    champion = _scorecard(
        0.60, 0.7, 0.5, 0.5,
        qm={
            "faithfulness": 0.90,
            "answer_relevancy": 0.85,
            "context_precision": 0.86,
            "context_recall": 0.84,
        },
    )
    # Higher composite, but faithfulness dropped 10% → must be rejected.
    regressed = _scorecard(
        0.63, 0.7, 0.5, 0.5,
        qm={
            "faithfulness": 0.81,
            "answer_relevancy": 0.85,
            "context_precision": 0.86,
            "context_recall": 0.84,
        },
    )
    ok, reason = is_improvement(champion, regressed)
    assert not ok
    assert "faithfulness" in reason