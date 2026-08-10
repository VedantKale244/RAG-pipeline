"""Tests for the selfopt persistence layer.

Every test runs against a tmp database: the fixture repoints
``settings.state_db_path`` and resets the module's cached connection, so no test
touches the real `.data/state.db` and order does not matter.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from app.config import settings
from app.selfopt import store


@pytest.fixture(autouse=True)
def tmp_state_db(tmp_path, monkeypatch):
    """Point the store at a throwaway DB and reset its connection cache."""
    db_path = tmp_path / ".data" / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db_path), raising=False)
    store._reset_conn()
    store.init_db()
    yield db_path
    store._reset_conn()


_TABLES = {
    "config_versions",
    "selfopt_metrics",
    "selfopt_tunable_stats",
    "selfopt_lock",
    "selfopt_baseline",
    "selfopt_state",
    "selfopt_tombstone",
    "selfopt_archive",
    "repair_queue",
}


def test_init_db_is_idempotent(tmp_state_db):
    # Fixture already called it once; a second call must not raise.
    store.init_db()

    rows = store.get_db().execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    names = {r["name"] for r in rows}

    assert _TABLES <= names
    assert tmp_state_db.exists()


def test_state_roundtrip():
    store.set_state("lifecycle_stage", "normal")
    assert store.get_state("lifecycle_stage") == "normal"

    # Overwriting replaces rather than duplicating.
    store.set_state("lifecycle_stage", "hibernating")
    assert store.get_state("lifecycle_stage") == "hibernating"

    row = store.get_db().execute(
        "SELECT COUNT(*) AS n FROM selfopt_state WHERE key = 'lifecycle_stage'"
    ).fetchone()
    assert row["n"] == 1

    assert store.get_state("never_set") is None
    assert store.get_state("never_set", "fallback") == "fallback"


def test_get_champion_returns_none_when_empty():
    assert store.get_champion() is None
    assert store.get_champion_version() is None


def test_champion_id_and_params_come_from_the_same_row():
    store.insert_version("v1", None, {"k": 1}, {})
    store.update_version("v1", status="champion", promoted_at=time.time())
    store.insert_version("v2", "v1", {"k": 2}, {})

    assert store.get_champion_version() == "v1"
    assert store.get_champion() == {"k": 1}

    # Promoting v2 moves both together; there is no second pointer to update.
    store.update_version("v1", status="retired")
    store.update_version("v2", status="champion", promoted_at=time.time())
    assert store.get_champion_version() == "v2"
    assert store.get_champion() == {"k": 2}


def test_second_champion_is_rejected_by_the_database():
    # Not a convention the promotion code is trusted to follow: the partial
    # unique index makes a second champion row impossible to commit. Without it
    # _champion_row()'s ORDER BY ... LIMIT 1 would silently pick the newest.
    store.insert_version("v1", None, {"k": 1}, {})
    store.update_version("v1", status="champion", promoted_at=time.time())
    store.insert_version("v2", "v1", {"k": 2}, {})

    with pytest.raises(sqlite3.IntegrityError):
        store.update_version("v2", status="champion", promoted_at=time.time())

    # The rejected promotion left the incumbent untouched.
    assert store.get_champion_version() == "v1"

    # Retire-then-promote — the legal sequence — must still work.
    store.update_version("v1", status="retired")
    store.update_version("v2", status="champion", promoted_at=time.time())
    assert store.get_champion_version() == "v2"
    assert store.get_champion() == {"k": 2}


def test_retired_and_proposed_rows_are_not_constrained():
    # The index is partial: only 'champion' is unique. Many versions share every
    # other status, and constraining them would break normal lineage.
    for v in ("v1", "v2", "v3"):
        store.insert_version(v, None, {"k": v}, {})
    for v in ("v1", "v2"):
        store.update_version(v, status="retired")

    assert store.get_champion_version() is None
    assert len(store.get_all_versions()) == 3


def test_insert_and_fetch_version():
    params = {"retrieval_top_k": 12, "rerank_top_n": 5, "temperature": 0.2}
    changes = {"retrieval_top_k": [10, 12]}
    store.insert_version("v1", None, params, changes)

    row = store.get_version("v1")
    assert row["parameters_json"] == params
    assert row["changes_json"] == changes
    assert row["parent_version"] is None
    assert row["status"] == "proposed"

    # Champion only appears once the version is promoted.
    assert store.get_champion() is None
    store.update_version("v1", status="champion", promoted_at=time.time(), composite_score=0.81)
    assert store.get_champion() == params
    assert store.get_version("v1")["composite_score"] == 0.81


def test_update_version_rejects_unknown_columns():
    store.insert_version("v1", None, {}, {})
    with pytest.raises(ValueError):
        store.update_version("v1", bogus_column="x")


def test_recent_metrics_is_newest_first_and_limited():
    for i in range(250):
        store.record_metric("v1", "composite", float(i))

    values = store.recent_metrics("v1", "composite")
    assert len(values) == 200
    assert values[0] == 249.0  # newest first
    assert store.count_metrics("v1", "composite") == 250

    assert store.recent_metrics("v1", "composite", limit=10) == [
        float(i) for i in range(249, 239, -1)
    ]
    # Scoped to the version/metric pair.
    assert store.recent_metrics("v2", "composite") == []
    assert store.recent_metrics("v1", "latency_p95") == []


def test_metrics_since_filters_by_timestamp():
    conn = store.get_db()
    now = time.time()
    with conn:
        conn.executemany(
            "INSERT INTO selfopt_metrics (version, ts, metric, value) VALUES (?, ?, ?, ?)",
            [
                ("v1", now - 7200, "composite", 0.1),  # old
                ("v1", now - 60, "composite", 0.5),
                ("v2", now - 30, "composite", 0.7),
            ],
        )

    recent = store.metrics_since("composite", now - 600)
    assert sorted(recent) == [0.5, 0.7]
    assert 0.1 not in recent

    assert store.metrics_since("composite", now - 600, version="v1") == [0.5]
    assert store.metrics_since("composite", now + 60) == []


def test_lock_is_exclusive():
    assert store.acquire_lock("cycle-a") is True
    assert store.acquire_lock("cycle-b") is False
    # The holder can re-enter / refresh its own lock.
    assert store.acquire_lock("cycle-a") is True

    store.release_lock("cycle-a")
    assert store.acquire_lock("cycle-b") is True


def test_lock_expires_after_ttl():
    # A crashed cycle must not deadlock the optimizer forever. Fails if the TTL
    # comparison is removed: a live lock must still block a different holder.
    assert store.acquire_lock("crashed-cycle", ttl_s=0.05) is True
    assert store.acquire_lock("next-cycle") is False

    time.sleep(0.1)
    assert store.acquire_lock("next-cycle") is True

    row = store.get_db().execute("SELECT holder FROM selfopt_lock WHERE id = 1").fetchone()
    assert row["holder"] == "next-cycle"


def test_lock_with_zero_ttl_is_immediately_expired():
    # Boundary: expires_at == now, and the liveness check is a strict <.
    assert store.acquire_lock("crashed-cycle", ttl_s=0) is True
    assert store.acquire_lock("next-cycle") is True


def test_release_lock_is_holder_scoped():
    assert store.acquire_lock("cycle-a") is True

    store.release_lock("cycle-b")  # wrong holder — must not free it
    assert store.acquire_lock("cycle-b") is False

    store.release_lock("cycle-a")
    assert store.acquire_lock("cycle-b") is True


def test_tombstone_roundtrip():
    assert store.get_tombstone() is None

    store.insert_tombstone(
        "3 consecutive floor breaches",
        {"composite": 0.41},
        [{"cycle": 7, "reason": "faithfulness floor"}],
        "v9",
    )

    tomb = store.get_tombstone()
    assert tomb["reason"] == "3 consecutive floor breaches"
    assert tomb["final_metrics_json"] == {"composite": 0.41}
    assert tomb["failure_history_json"] == [{"cycle": 7, "reason": "faithfulness floor"}]
    assert tomb["restored_version"] == "v9"


def test_purge_keeps_champion_and_tombstone():
    store.insert_version("v1", None, {"k": 1}, {})
    store.update_version("v1", status="champion", promoted_at=time.time())
    store.insert_version("v2", "v1", {"k": 2}, {})
    store.record_metric("v2", "composite", 0.5)
    store.insert_tombstone("floors", {}, [], "v1")

    store.purge_experiments()

    assert store.get_champion() == {"k": 1}
    assert store.get_version("v2") is None
    assert store.recent_metrics("v2", "composite") == []
    assert store.get_tombstone() is not None


def test_purge_never_leaves_a_champion_pointer_without_its_row():
    # The divergence this design rules out: purge drops the experiment rows,
    # and whatever get_champion_version() reports must still resolve.
    store.insert_version("v3", None, {"k": 3}, {})
    store.update_version("v3", status="retired")
    store.insert_version("v7", "v3", {"k": 7}, {})
    store.update_version("v7", status="champion", promoted_at=time.time())
    store.insert_version("v8", "v7", {"k": 8}, {})  # in-flight challenger

    store.purge_experiments()

    version = store.get_champion_version()
    assert version == "v7"
    assert store.get_version(version) is not None
    assert store.get_version("v8") is None


def test_tunable_stats_upsert():
    assert store.get_tunable_stat("retrieval_top_k") is None

    store.update_tunable_stat("retrieval_top_k", wins=1, attempts=1)
    stat = store.get_tunable_stat("retrieval_top_k")
    assert (stat["wins"], stat["attempts"], stat["frozen_until"]) == (1, 1, 0)

    # Partial update leaves untouched columns alone.
    store.update_tunable_stat("retrieval_top_k", attempts=2)
    stat = store.get_tunable_stat("retrieval_top_k")
    assert (stat["wins"], stat["attempts"]) == (1, 2)

    assert [s["field"] for s in store.get_all_tunable_stats()] == ["retrieval_top_k"]


def test_repair_queue_dedupes_by_fingerprint():
    store.record_repair("abc123", "/chat", "Traceback: boom")
    store.record_repair("abc123", "/chat", "Traceback: boom again")

    repairs = store.list_repairs()
    assert len(repairs) == 1
    assert repairs[0]["count"] == 2
    assert repairs[0]["status"] == "open"
    assert store.list_repairs(status="closed") == []


def test_baseline_roundtrip():
    assert store.get_baseline("graph_edges") is None
    store.set_baseline("graph_edges", "4210")
    assert store.get_baseline("graph_edges") == "4210"
    store.set_baseline("graph_edges", "4400")
    assert store.get_baseline("graph_edges") == "4400"


def test_get_all_versions_is_newest_first():
    store.insert_version("v1", None, {"k": 1}, {})
    time.sleep(0.01)
    store.insert_version("v2", "v1", {"k": 2}, {})

    versions = store.get_all_versions()
    assert [v["version"] for v in versions] == ["v2", "v1"]
    assert versions[0]["parameters_json"] == {"k": 2}


def test_archive_stores_blob():
    store.insert_archive(b"\x1f\x8bgzipped")
    row = store.get_db().execute("SELECT payload FROM selfopt_archive").fetchone()
    assert row["payload"] == b"\x1f\x8bgzipped"


def test_promote_is_atomic_retire_then_champion():
    store.insert_version("v1", None, {"k": 1}, {})
    store.promote("v1", composite=0.80)
    assert store.get_champion_version() == "v1"
    assert store.get_champion() == {"k": 1}

    # Promote a successor: the outgoing must be retired, never left a champion.
    store.insert_version("v2", "v1", {"k": 2}, {})
    store.promote("v2", composite=0.82)

    assert store.get_champion_version() == "v2"
    assert store.get_version("v1")["status"] == "retired"
    assert store.get_version("v2")["status"] == "champion"
    assert store.get_version("v2")["composite_score"] == 0.82
    assert store.get_version("v2")["promoted_at"] is not None


def test_promote_nonexistent_version_is_noop():
    store.promote("ghost", composite=0.5)
    assert store.get_champion_version() is None


def test_get_last_champion_is_most_recent_retired():
    assert store.get_last_champion() is None

    store.insert_version("v1", None, {"k": 1}, {})
    store.promote("v1", composite=0.0)
    # v1 is still champion — there is no retired predecessor yet.
    assert store.get_last_champion() is None

    # The *current* champion is not the last retired one.
    store.insert_version("v2", "v1", {"k": 2}, {})
    store.promote("v2", composite=0.81)
    assert store.get_last_champion()["version"] == "v1"
    assert store.get_champion_version() == "v2"


def test_increment_state_is_atomic_and_returns_value():
    assert store.get_state("query_count") is None

    assert store.increment_state("query_count") == 1
    assert store.increment_state("query_count") == 2
    assert store.increment_state("query_count", by=5) == 7
    # Back to a plain read: the stored value is an integer string, not "1234".
    assert store.get_state("query_count") == "7"


def test_clear_tombstone_revives_system():
    store.insert_tombstone("died", {}, [], "v1")
    assert store.get_tombstone() is not None

    store.clear_tombstone()
    assert store.get_tombstone() is None
