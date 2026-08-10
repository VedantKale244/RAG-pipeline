"""Tests for the activity audit trail: every super-agent action is recorded and readable."""
from __future__ import annotations

import pytest

from app.config import settings
from app.selfopt import guardian, store
from app.selfopt.experiment import rollback, run_cycle


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db), raising=False)
    store._reset_conn()
    store.init_db()
    yield
    store._reset_conn()


def test_record_and_list_roundtrip_newest_first():
    store.record_activity(store.KIND_SYSTEM, "first", "v1")
    store.record_activity(store.KIND_CYCLE, "second", "v2")
    acts = store.list_activities()
    assert [a["detail"] for a in acts] == ["second", "first"]
    assert acts[0]["version"] == "v2"
    kinds = {a["kind"] for a in acts}
    assert kinds == {store.KIND_SYSTEM, store.KIND_CYCLE}


def test_list_by_kind():
    store.record_activity(store.KIND_PROMOTE, "p1")
    store.record_activity(store.KIND_REPAIR, "r1")
    assert [a["detail"] for a in store.list_activities(kind=store.KIND_PROMOTE)] == ["p1"]


def test_promotion_leaves_audit_row():
    store.insert_version("v1", None, {"retrieve_top_k": 10}, {})
    store.promote("v1", 0.91)
    acts = store.list_activities(kind=store.KIND_PROMOTE)
    assert len(acts) == 1
    assert acts[0]["version"] == "v1"
    assert "0.910" in acts[0]["detail"]


def test_rollback_leaves_audit_row():
    store.insert_version("v1", None, {}, {})
    rollback("v1", "dropped below floors")
    acts = store.list_activities(kind=store.KIND_ROLLBACK)
    assert len(acts) == 1
    assert "dropped below floors" in acts[0]["detail"]
    assert "rolled back" in acts[0]["detail"].lower()


def test_cycle_outcome_always_logged():
    result = run_cycle([])  # no golden -> skipped:no-golden-set
    assert result["status"].startswith("skipped")
    acts = store.list_activities(kind=store.KIND_CYCLE)
    assert acts and "skipped:no-golden-set" in acts[0]["detail"]


def test_guardian_stage_transition_logged():
    store.insert_version("v1", None, {}, {})
    store.promote("v1", 0.9)
    # 3 consecutive losses -> WARNING
    for _ in range(3):
        guardian.check_after_cycle("offline_fail")
    acts = store.list_activities(kind=store.KIND_GUARDIAN)
    assert acts and "WARNING" in acts[0]["detail"]


def test_repair_capture_logged():
    store.record_repair("fp-x", "/chat", "traceback...")
    acts = store.list_activities(kind=store.KIND_REPAIR)
    assert acts
    assert "fp-x" in acts[0]["detail"]


def test_record_activity_never_raises_on_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(store, "get_db", boom)
    store.record_activity(store.KIND_SYSTEM, "should not raise")