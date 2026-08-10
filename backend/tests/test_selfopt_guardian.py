"""Tests for the guardian lifecycle, floors, and self-destruct."""
from __future__ import annotations

import time

import pytest

from app.config import settings
from app.selfopt import store
from app.selfopt import guardian
from app.selfopt.guardian import (
    STAGE_HEALTHY,
    STAGE_HIBERNATING,
    STAGE_ROLLBACK,
    STAGE_TOMBSTONED,
    STAGE_WARNING,
    check_after_cycle,
    check_floors,
    get_lifecycle_stage,
    self_destruct,
)


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db), raising=False)
    store._reset_conn()
    store.init_db()
    yield
    store._reset_conn()


def _seed_champion(v="v1"):
    store.insert_version(v, None, {"retrieve_top_k": 10}, {})
    store.promote(v, 0.8)


def _record_good(v):
    for m in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
        store.record_metric(v, m, 0.95)
    store.record_metric(v, "latency_ms", 300.0)


def test_starts_healthy():
    assert get_lifecycle_stage() == STAGE_HEALTHY


def test_three_failures_enter_warning():
    for i in range(3):
        check_after_cycle("offline_fail")
    assert get_lifecycle_stage() == STAGE_WARNING


def test_five_failures_enter_rollback_and_pause():
    _seed_champion("good"); _record_good("good")
    store.insert_version("bad", "good", {"retrieve_top_k": 11}, {})
    store.promote("bad", 0.9)  # bad is now champion (no metrics → floors breached? no data = not breached)
    # Ensure a good ancestor exists but the current champion has no good data.
    for i in range(5):
        check_after_cycle("offline_fail")
    stage = get_lifecycle_stage()
    assert stage == STAGE_ROLLBACK
    # Paused 6h.
    assert guardian._pause_until() > time.time()


def test_promotion_resets_from_any_stage():
    for i in range(5):
        check_after_cycle("offline_fail")
    assert get_lifecycle_stage() == STAGE_ROLLBACK
    check_after_cycle("promoted")
    assert get_lifecycle_stage() == STAGE_HEALTHY


def test_skipped_is_neutral():
    for i in range(5):
        check_after_cycle("skipped:no-judge")
    assert get_lifecycle_stage() == STAGE_HEALTHY
    check_after_cycle("skipped:lock-held")
    assert get_lifecycle_stage() == STAGE_HEALTHY


def test_no_data_floors_are_not_breached():
    _seed_champion()
    rep = check_floors()
    assert rep["breached"] is False


def test_feedback_floor_needs_twenty_votes():
    _seed_champion()
    # 19 downs — under the 20-vote guard, so not a breach despite the bad ratio.
    for _ in range(19):
        store.record_metric("v1", "feedback_down", 1.0)

    rep = check_floors()
    assert rep["floors"]["feedback"] is False

    store.record_metric("v1", "feedback_down", 1.0)  # → 20 votes
    rep = check_floors()
    assert rep["floors"]["feedback"] is True
    assert rep["breached"] is True


def test_latency_floor_breaches_over_2500ms():
    _seed_champion()
    for _ in range(10):
        store.record_metric("v1", "latency_ms", 4000.0)
    rep = check_floors()
    assert rep["floors"]["latency_p95"] is True


def test_low_ragas_floor_breaches():
    _seed_champion()
    for _ in range(10):
        store.record_metric("v1", "faithfulness", 0.4)
    rep = check_floors()
    assert rep["floors"]["faithfulness"] is True


def test_stage_thresholds():
    assert guardian._stage_for(0, False) == STAGE_HEALTHY
    assert guardian._stage_for(3, False) == STAGE_WARNING
    assert guardian._stage_for(5, False) == STAGE_ROLLBACK
    assert guardian._stage_for(10, False) == STAGE_HIBERNATING
    # 20 failures need a live floor breach to cross the terminal line.
    assert guardian._stage_for(20, False) == STAGE_HIBERNATING
    assert guardian._stage_for(20, True) == STAGE_TOMBSTONED
    # A jump never skips a stage.
    assert guardian._stage_for(17, False) == STAGE_HIBERNATING
    assert guardian._stage_for(50, True) == STAGE_TOMBSTONED


def test_tombstone_survives_restart():
    store.insert_tombstone("terminal collapse", {"composite": 0.1}, [], "v1")
    # A restart (fresh connection, same .db file) must stay dead.
    store._reset_conn()
    store.init_db()
    assert get_lifecycle_stage() == STAGE_TOMBSTONED
    assert store.get_tombstone() is not None


def test_self_destruct_writes_tombstone_and_disables():
    _seed_champion()
    _record_good("v1")
    self_destruct("collapse")
    assert store.get_tombstone() is not None
    assert store.get_state("disabled") == "true"
    assert get_lifecycle_stage() == STAGE_TOMBSTONED
    # Experiments purged but champion/retired retained for restore.
    assert store.get_all_versions()  # at least the champion survives as a restore target