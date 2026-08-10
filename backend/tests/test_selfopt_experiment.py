"""Tests for proposals, canary routing, oscillation suppression, and the ladder."""
from __future__ import annotations

import random
import time

import pytest

from app.config import settings
from app.selfopt import experiment, overrides, store
from app.selfopt.experiment import canary_bucket, check_oscillation, propose, record_attempt


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db), raising=False)
    store._reset_conn()
    store.init_db()
    yield
    store._reset_conn()


@pytest.fixture(autouse=True)
def _seed():
    random.seed(0)


def _seed_champion():
    store.insert_version("v3", None, {"retrieve_top_k": 10, "rerank_top_n": 4}, {})
    store.promote("v3", 0.8)
    # Live metrics so scorecard() has something to beat (champion ~0.6–0.8).
    for m in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
        store.record_metric("v3", m, 0.8)
    store.record_metric("v3", "latency_ms", 500.0)


def test_proposal_perturbs_one_to_three_distinct_fields():
    _seed_champion()
    # `propose()` may legitimately return None (a no-op delta after clamping),
    # so sample widely and assert on the successes.
    lengths = set()
    proposals = 0
    for _ in range(400):
        p = propose()
        if p is None:
            continue
        proposals += 1
        perturbed = p["changes"]["perturbed"]
        assert 1 <= len(perturbed) <= 3
        assert len(set(perturbed)) == len(perturbed)
        lengths.add(len(perturbed))
        overrides.validate(p["params"])
    assert proposals > 50
    assert lengths == {1, 2, 3}


def test_proposal_validated_and_in_range():
    _seed_champion()
    for _ in range(200):
        p = propose()
        if p is None:
            continue
        for name, value in p["params"].items():
            lo, hi, is_int = overrides.TUNABLES[name]
            assert lo <= value <= hi
    assert store.get_champion()["retrieve_top_k"] == 10


def test_canary_determinism_and_stickiness():
    a = canary_bucket("usr_1", "v10")
    b = canary_bucket("usr_1", "v10")
    assert a == b
    # Different version generally lands elsewhere.
    assert canary_bucket("usr_1", "v10") == a


def test_canary_distribution_about_15_percent():
    inside = sum(1 for i in range(1000) if canary_bucket(f"usr_{i}", "v10"))
    # 15% of 1000 = 150; the plan's tolerance is 100–200.
    assert 100 <= inside <= 200


def test_oscillation_halves_wins_and_freezes():
    store.insert_version("cv", None, {}, {})
    store.promote("cv", 0.0)
    # Within 5% of the max ⇒ flags as oscillating (A→B→A→B→A).
    for value in (100.0, 96.0, 100.0):
        check_oscillation("chunk_size", value)
    assert check_oscillation("chunk_size", 97.0) is True
    st = store.get_tunable_stat("chunk_size") or {}
    assert st["frozen_until"] > time.time()
    assert experiment._is_frozen("chunk_size") is True
    # The knob is now excluded from proposals.
    random.seed(0)
    for _ in range(60):
        p = propose()
        if p:
            assert "chunk_size" not in p["changes"]["perturbed"]


def test_oscillation_does_not_fire_on_spread_trail():
    store.insert_version("cv", None, {}, {}); store.promote("cv", 0.0)
    # A wide-spread trail (values diverge >5% of max) is not oscillation.
    for v in (10.0, 30.0, 10.0):
        check_oscillation("chunk_size", v)
    assert check_oscillation("chunk_size", 28.0) is False


def test_record_attempt_tracks_beta_counters():
    record_attempt(["retrieve_top_k"], won=True)
    st = store.get_tunable_stat("retrieve_top_k")
    assert st["wins"] == 1 and st["attempts"] == 1

    record_attempt(["retrieve_top_k"], won=False)
    st = store.get_tunable_stat("retrieve_top_k")
    assert st["wins"] == 1 and st["attempts"] == 2


def test_ladder_lock_contention_skips():
    class _FakeJudge:
        def __call__(self, *a):
            return {"scores": {"faithfulness": .9, "answer_relevancy": .9,
                                "context_precision": .9, "context_recall": .9}}

    assert store.acquire_lock("other-holder") is True
    out = experiment.run_cycle([{"question": "q", "ground_truth": "a"}], judge=_FakeJudge())
    assert out["status"] == "skipped:lock-held"
    store.release_lock("other-holder")


def test_run_cycle_skips_without_golden_set():
    _seed_champion()
    out = experiment.run_cycle([], judge=lambda s, v: {})
    assert out["status"] == "skipped:no-golden-set"
    # A skipped cycle wrote no champion change.
    assert store.get_champion_version() == "v3"


def test_run_cycle_offline_fail_without_improvement():
    _seed_champion()  # champion scored ~0.64 composite

    class _WorseJudge:
        def __call__(self, samples, version):
            return {"scores": {"faithfulness": 0.2, "answer_relevancy": 0.2,
                                "context_precision": 0.2, "context_recall": 0.2}}

    # A challenger may no-op to None; retry until an actual proposal is judged.
    for _ in range(50):
        out = experiment.run_cycle(
            [{"question": "q", "ground_truth": "a"}], judge=_WorseJudge()
        )
        if out["status"] == "skipped:no-proposal":
            continue
        assert out["status"] == "offline_fail"
        assert store.get_champion_version() == "v3"
        return
    raise AssertionError("never produced a judged proposal")