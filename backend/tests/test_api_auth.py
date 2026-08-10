"""HTTP-surface tests for verify_api_key + EvalRequest validation.

Uses /eval as the probe: auth is a router-level dependency, so a bad key 401s
*before* the handler runs. A passing key falls through to the handler, which
400s on empty samples — so "auth passed" reads as 400, not 401. No external
service (Cohere/Pinecone/Neo4j/ragas) is touched on either path.

TestClient is built without `with`, so the lifespan (observability + Neo4j
ensure_schema) never runs — these tests need neither.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.ratelimit import limiter

client = TestClient(app)

KEY = "secret-test-key"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    # We're testing auth, not throttling — the 5/min cap on /eval would
    # otherwise turn later requests into spurious 429s.
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(settings, "api_key", KEY)


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")


def test_missing_key_is_rejected(with_key):
    r = client.post("/eval", json={"samples": []})
    assert r.status_code == 401


def test_wrong_key_is_rejected(with_key):
    r = client.post("/eval", json={"samples": []}, headers={"x-api-key": "nope"})
    assert r.status_code == 401


def test_correct_key_header_passes_auth(with_key):
    # 400 = auth passed, handler rejected the empty golden set.
    r = client.post("/eval", json={"samples": []}, headers={"x-api-key": KEY})
    assert r.status_code == 400


def test_correct_key_query_param_passes_auth(with_key):
    # EventSource can't set headers, so the query-param path must also work.
    r = client.post("/eval?api_key=" + KEY, json={"samples": []})
    assert r.status_code == 400


def test_fail_open_when_unconfigured(no_key):
    r = client.post("/eval", json={"samples": []})
    assert r.status_code == 400  # no key set → unauthenticated, straight to handler


def test_health_is_unprotected(with_key):
    assert client.get("/health").status_code == 200


def test_eval_samples_max_length(with_key):
    too_many = [{"question": "q", "ground_truth": "a"}] * 51
    r = client.post("/eval", json={"samples": too_many}, headers={"x-api-key": KEY})
    assert r.status_code == 422
