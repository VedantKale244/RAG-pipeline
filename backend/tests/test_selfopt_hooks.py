"""Tests for live-traffic hooks: canary bucketing, scoping, and metric attribution."""
from __future__ import annotations

import pytest

from app.config import settings
from app.selfopt import hooks, store


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db), raising=False)
    store._reset_conn()
    store.init_db()
    yield
    store._reset_conn()


def test_canary_is_bool_and_sticky():
    assert isinstance(hooks.canary("anyone"), bool)
    assert hooks.canary("alice") == hooks.canary("alice")


def test_canary_scope_serves_challenger_only_in_bucket(monkeypatch):
    from app.selfopt import overrides

    # An experiment is live: active version "v9", bucketing picks "in" only.
    monkeypatch.setattr(hooks, "active_version_ctx", lambda: "v9")
    monkeypatch.setattr(hooks, "canary", lambda who: who == "in")
    store.insert_version("v9", None, {"retrieve_top_k": 12}, {"perturbed": ["retrieve_top_k"]})

    with hooks.canary_scope("in") as v:
        assert v == "v9"
        assert overrides.active_version() == "v9"  # challenger is active here

    # A non-canary user never enters the challenger context.
    with hooks.canary_scope("out") as v:
        assert v is None
    assert overrides.active_version() is None


def test_canary_scope_no_override_without_active_challenge(monkeypatch):
    monkeypatch.setattr(hooks, "active_version_ctx", lambda: None)
    monkeypatch.setattr(hooks, "canary", lambda who: True)
    with hooks.canary_scope("anyone") as v:
        assert v is None


def test_observe_records_metrics_only_in_canary(monkeypatch):
    from app.selfopt import metrics as metrics_mod

    records = []
    monkeypatch.setattr(metrics_mod, "record_request", lambda version, latency: records.append((version, latency)))
    monkeypatch.setattr(hooks, "active_version_ctx", lambda: "v9")
    monkeypatch.setattr(hooks, "canary", lambda who: who == "in")

    hooks.observe(who="in", latency_ms=123)
    hooks.observe(who="out", latency_ms=999)
    assert records == [("v9", 123)]


def test_observe_feedback_attribution(monkeypatch):
    from app.selfopt import metrics as metrics_mod

    votes = []
    monkeypatch.setattr(metrics_mod, "record_vote", lambda version, positive, rating=None: votes.append((version, positive)))
    monkeypatch.setattr(hooks, "active_version_ctx", lambda: "v9")
    monkeypatch.setattr(hooks, "canary", lambda who: who == "in")

    hooks.observe_feedback(who="in", thumbs_up=True, rating=5.0)
    hooks.observe_feedback(who="out", thumbs_up=True)
    assert votes == [("v9", True)]