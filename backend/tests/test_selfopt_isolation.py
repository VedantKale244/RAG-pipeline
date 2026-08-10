"""Tests for rebuild budgeting, teardown/swap pointers, and shadow/live isolation."""
from __future__ import annotations

import time

import pytest

from app.config import settings
from app.selfopt import rebuild, store
from app.core.vectorstore import _build_filter


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db), raising=False)
    store._reset_conn()
    store.init_db()
    yield
    store._reset_conn()


def test_rebuild_budget_three_tiers():
    assert rebuild.rebuild_budget(1500) == 1500          # < 2000 → all
    assert rebuild.rebuild_budget(1999) == 1999
    assert rebuild.rebuild_budget(5000) == 500           # 25% → cap 500
    assert rebuild.rebuild_budget(20000) == 1000         # 10% → cap 1000
    # Boundary at 2000 drops into the 25%-tier.
    assert rebuild.rebuild_budget(2000) == 500
    assert rebuild.rebuild_budget(0) == 0


def test_rebuild_24h_gate():
    assert rebuild.can_rebuild() is True
    rebuild.mark_rebuilt()
    assert rebuild.can_rebuild() is False
    store.set_state("last_rebuild_at", str(time.time() - rebuild._REBUILD_COOLDOWN_S - 1))
    assert rebuild.can_rebuild() is True


def test_shadow_id_format():
    assert rebuild.shadow_id("v9", "doc-7", 3) == "selv9-doc-7-3"


def test_swap_in_flips_pointer_and_starts_grace():
    rebuild.swap_in("v9")
    assert store.get_state("active_shadow_version") == "v9"
    assert rebuild.eligible_for_teardown("v9", now=time.time() + 7200) is True
    assert rebuild.eligible_for_teardown("v9", now=time.time() + 1) is False


def test_build_filter_excludes_shadow_in_live_mode():
    f = _build_filter("usr_1")          # version=None ⇒ live
    assert f["user_id"] == "usr_1"
    # Pinecone has no null index: live must be "$exists": False, not {"$eq": None}.
    assert f["selfopt_version"] == {"$exists": False}


def test_build_filter_targets_one_version_in_shadow_mode():
    f = _build_filter("usr_1", "v9")
    assert f["user_id"] == "usr_1"
    assert f["selfopt_version"] == "v9"


def test_upsert_and_teardown_call_shadow_prefix(monkeypatch):
    import app.core.vectorstore as vs
    upserts = []
    deletes = []

    class _Index:
        def upsert(self, vectors):
            upserts.extend(vectors)

        def list(self, prefix, limit=100):
            if prefix.startswith("selv9-"):
                return [["selv9-doc-1-0"]]
            if prefix.startswith("doc-1-"):
                return [["doc-1-cityid-0"]]
            return []

        def delete(self, ids=None, filter=None):
            deletes.extend(ids or [])

    monkeypatch.setattr(vs, "pinecone_index", lambda: _Index())
    monkeypatch.setattr(vs, "safe_embed_documents", lambda texts: [[1.0] * settings.cohere_embed_dim for _ in texts])

    vs.upsert_chunks(
        [{"chunk_id": "orig-1", "text": "t", "source": "s", "document_id": "doc-1", "user_id": "usr_1"}],
        version="v9",
    )
    shadow = upserts[0]
    assert shadow["id"].startswith("selv9-")
    assert shadow["metadata"]["selfopt_version"] == "v9"

    # Live upserts are untouched (original chunk_id, no selfopt_version tag).
    upserts.clear()
    vs.upsert_chunks(
        [{"chunk_id": "orig-1", "text": "t", "source": "s", "document_id": "doc-1", "user_id": "usr_1"}]
    )
    assert upserts[0]["id"] == "orig-1"
    assert "selfopt_version" not in upserts[0]["metadata"]

    # Shadow teardown uses the prefix scan and issues the delete.
    vs.delete_shadow("v9")
    assert any(d.startswith("selv9-") for d in deletes)