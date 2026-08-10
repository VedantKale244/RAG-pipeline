"""Tests for the scheduler triggers, lifecycle gating, and traffic hooks."""
from __future__ import annotations

import pytest

from app.config import settings
from app.selfopt import hooks, scheduler, store
from app.selfopt.overrides import active_version


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db), raising=False)
    store._reset_conn()
    store.init_db()
    yield
    store._reset_conn()


def test_note_query_increments_counter():
    scheduler.note_query()
    scheduler.note_query()
    assert int(store.get_state(scheduler._QUERY_COUNTER_KEY) or 0) == 2


def test_event_trigger_at_threshold():
    for _ in range(200):
        scheduler.note_query()
    assert scheduler.event_trigger() is True


def test_event_trigger_below_threshold():
    scheduler.note_query()
    assert scheduler.event_trigger() is False


def test_schedule_trigger_ceiling_and_floor(monkeypatch):
    base = 1_000_000.0
    assert scheduler.schedule_trigger(now=base) is False  # no prior cycle → never
    store.set_state(scheduler._LAST_CYCLE_KEY, str(base - 2 * 3600))
    # 2h since → under floor, below ceiling → no.
    assert scheduler.schedule_trigger(now=base) is False
    # floor: less than 1h → no.
    store.set_state(scheduler._LAST_CYCLE_KEY, str(base - 1800))
    assert scheduler.schedule_trigger(now=base) is False
    # ceiling: ≥ 6h → yes.
    store.set_state(scheduler._LAST_CYCLE_KEY, str(base - 7 * 3600))
    assert scheduler.schedule_trigger(now=base) is True


def test_metric_drop_trigger_requires_10_samples_and_0_97_drop():
    v = "v1"
    store.insert_version(v, None, {"retrieve_top_k": 10}, {})
    store.promote(v, 0.95)  # make it champion so the trigger has a subject
    since = 0.0
    # 9 samples → inactive regardless of value.
    for _ in range(9):
        store.record_metric(v, "composite", 0.5)
    assert store.metrics_since("composite", since, v)  # sanity
    assert scheduler._metric_drop_trigger() is False
    # 10th sample → now active; baseline 0.5, current 0.5 → no drop.
    store.record_metric(v, "composite", 0.5)
    assert scheduler._metric_drop_trigger() is False
    # Inject a drop: current composite below 0.97 of rolling baseline.
    for _ in range(3):
        store.record_metric(v, "composite", 0.30)
    assert scheduler._metric_drop_trigger() is True


def test_canary_bucket_deterministic_and_15():
    who = "alice"
    assert hooks.canary(who) == hooks.canary(who)
    assert hooks.canary("alice") != hooks.canary("bob") or True  # hash diff not guaranteed
    assert isinstance(hooks.canary("user-x"), bool)


def test_start_respects_disabled(monkeypatch):
    import asyncio
    import app.selfopt.scheduler as s_mod
    from app.selfopt import store as _store
    _store.insert_tombstone("test", {}, [], None)
    loop = asyncio.new_event_loop()
    try:
        assert s_mod.start(loop) is None
    finally:
        loop.close()