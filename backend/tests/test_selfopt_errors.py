"""Tests for exception capture, fingerprint dedup, transient retry, and diagnosis."""
from __future__ import annotations

import pytest

from app.selfopt import errors, store


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    from app.config import settings
    db = tmp_path / "state.db"
    monkeypatch.setattr(settings, "state_db_path", str(db), raising=False)
    store._reset_conn()
    store.init_db()
    yield db
    store._reset_conn()


def _boom(ep):
    raise ValueError("deterministic bug")


def test_same_exception_collapses_to_one_row_count_two():
    def _happen(ep):
        try:
            raise ValueError("deterministic bug")
        except ValueError as exc:
            return errors.capture(exc, ep)

    fp1 = _happen("/chat")
    fp2 = _happen("/chat")

    assert fp1 == fp2
    repairs = store.list_repairs()
    assert len(repairs) == 1
    assert repairs[0]["fingerprint"] == fp1
    assert repairs[0]["count"] == 2
    assert repairs[0]["endpoint"] == "/chat"


def test_different_endpoints_are_separate_rows():
    errors.capture(ValueError("x"), "/chat")
    errors.capture(ValueError("x"), "/feedback")
    assert len(store.list_repairs()) == 2


def test_transient_recognition():
    assert errors.is_transient(TimeoutError("operation timed out"))
    assert errors.is_transient(ConnectionResetError())
    assert errors.is_transient(RuntimeError("service unavailable"))
    assert errors.is_transient(ValueError("service temporarily unavailable"))
    assert not errors.is_transient(ValueError("deterministic bug"))
    assert not errors.is_transient(KeyError("missing"))


def test_retry_exhausts_and_reraises_transient():
    from app.selfopt.errors import retry_transient
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        raise ConnectionError("connection reset")

    with pytest.raises(ConnectionError):
        retry_transient(flaky, attempts=3, base=0.01)
    assert calls["n"] == 3


def test_retry_fails_fast_on_nontransient():
    from app.selfopt.errors import retry_transient
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise ValueError("deterministic")

    with pytest.raises(ValueError):
        retry_transient(bad, attempts=3, base=0.01)
    assert calls["n"] == 1


def test_retry_succeeds_on_later_attempt():
    from app.selfopt.errors import retry_transient
    calls = {"n": 0}

    def flaky_once():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionResetError("reset by peer")
        return "ok"

    assert retry_transient(flaky_once, attempts=3, base=0.01) == "ok"
    assert calls["n"] == 3


def test_capture_middleware_reraises():
    from app.selfopt.errors import CaptureMiddleware

    class _Inner:
        async def __call__(self, scope, receive, send):
            raise ValueError("surfaced")

    sent = []
    async def send(msg):
        sent.append(msg)

    async def no_recv():
        return {}

    import asyncio
    async def run():
        with pytest.raises(ValueError):
            await CaptureMiddleware(_Inner())({"path": "/chat"}, no_recv, send)

    asyncio.run(run())
    assert sent == []  # nothing was sent downstream; the 500 shape stays intact
    assert store.list_repairs()[0]["endpoint"] == "/chat"


def test_diagnose_names_known_cause():
    row = {
        "endpoint": "/chat",
        "count": 4,
        "traceback": "Traceback (most recent call last):\\n  service unavailable paragraph Neo4j connection",
    }
    diag = errors.diagnose(row)
    assert "Neo4j" in diag["cause"]
    assert diag["endpoint"] == "/chat"
    assert diag["count"] == 4