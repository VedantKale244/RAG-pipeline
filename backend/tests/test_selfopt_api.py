"""Tests for the admin self-optimization API routes (Spec §11)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.config import settings
from app.selfopt import store


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db), raising=False)
    store._reset_conn()
    store.init_db()
    monkeypatch.setattr(settings, "admin_password", "testpass", raising=False)
    yield
    store._reset_conn()


@pytest.fixture()
def client():
    from fastapi import FastAPI
    from app.api import selfopt_api
    app = FastAPI()
    app.include_router(selfopt_api.router)
    yield TestClient(app)


_AUTH = {"x-admin-password": "testpass"}


def test_status_endpoint(client):
    r = client.get("/admin/selfopt/status", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["tombstoned"] is False
    assert body["lifecycle_stage"] in {
        "HEALTHY", "WARNING", "ROLLBACK_OBSERVATION", "HIBERNATING", "TOMBSTONED"
    }


def test_status_requires_admin(client):
    r = client.get("/admin/selfopt/status")
    assert r.status_code in (401, 403)


def test_history_is_empty_then_lists_version(client):
    assert client.get("/admin/selfopt/history", headers=_AUTH).json()["versions"] == []
    store.insert_version("v1", None, {"retrieve_top_k": 10}, {})
    versions = client.get("/admin/selfopt/history", headers=_AUTH).json()["versions"]
    assert [v["version"] for v in versions] == ["v1"]


def test_metrics_series(client):
    store.insert_version("v1", None, {}, {})
    store.record_metric("v1", "composite", 0.6)
    store.record_metric("v1", "composite", 0.9)
    body = client.get("/admin/selfopt/metrics", params={"version": "v1"}, headers=_AUTH).json()
    assert body["composite"] == [0.9, 0.6]


def test_rollback_unknown_version_is_404(client):
    assert client.post("/admin/selfopt/rollback/missing", headers=_AUTH).status_code == 404


def test_baseline_repin(client):
    store.set_baseline("edge_baseline", "100")
    client.post("/admin/selfopt/baseline", params={"value": 250.0}, headers=_AUTH)
    assert float(store.get_baseline("edge_baseline")) == 250.0


def test_pause_resume_and_wake(client):
    client.post("/admin/selfopt/pause", headers=_AUTH)
    assert store.get_state("paused") == "1"
    client.post("/admin/selfopt/resume", headers=_AUTH)
    assert store.get_state("paused") == "0"


def test_revive_after_tombstone(client):
    store.insert_tombstone("test", {}, [], None)
    assert client.get("/admin/selfopt/status", headers=_AUTH).json()["tombstoned"] is True
    r = client.delete("/admin/selfopt/tombstone", headers=_AUTH)
    assert r.json()["tombstoned"] is False
    assert store.get_tombstone() is None