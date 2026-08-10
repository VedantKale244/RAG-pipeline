"""Project-wide exception capture and repair queue (Spec §9).

Every unhandled exception funnels into the ``repair_queue`` table via
``capture`` / the ASGI middleware, deduplicated by a fingerprint so one fault
collapses to one row with a rising count. Only the whitelisted *transient*
classes are auto-retried; everything deterministic is surfaced on the admin
portal with a diagnosis rather than silently swallowed.

Capture is observability, not error handling: ``capture_middleware`` re-raises
so the API's 500 contract is unchanged.
"""
from __future__ import annotations

import hashlib
import logging
import time
import traceback

from fastapi import HTTPException

from . import store

logger = logging.getLogger(__name__)

# Transient-failure whitelist. Anything not matching one of these is
# deterministic and must NOT be silently retried — retrying a certainty burns
# attempts and hides the real error.
_TRANSIENT_PATTERNS = (
    "429",
    "too many requests",
    "rate limit",
    "ratelimit",
    "throttl",
    "timeout",
    "timed out",
    "503",
    "502",
    "504",
    "connection reset",
    "connectionreset",
    "connection refused",
    "reset by peer",
    "temporarily unavailable",
    "service unavailable",
    "serviceunavailable",
    "session expired",
    "sessionexpired",
    "deadlock",
    "broken pipe",
)


def _transient_token(name: str, status: int | None, msg: str) -> str:
    text = f"name:{name} status:{status} msg:{msg}".lower()
    for pat in _TRANSIENT_PATTERNS:
        if pat in text:
            return pat
    return ""


def is_transient(exc: Exception) -> bool:
    """True only for the whitelisted transient failure classes."""
    status = exc.status_code if isinstance(exc, HTTPException) else None
    return bool(_transient_token(type(exc).__name__, status, str(exc)))


def fingerprint(exc: Exception, endpoint: str | None = None) -> str:
    """Stable id for one fault type + frame. Collapses repeats of one fault."""
    last_frame = ""
    tb = getattr(exc, "__traceback__", None)
    if tb:
        while tb.tb_next:
            tb = tb.tb_next
        last_frame = str(tb.tb_frame.f_code.co_filename or "")[:16]
    material = f"{type(exc).__name__}|{endpoint or ''}|{last_frame}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def capture(exc: Exception, endpoint: str | None = None) -> str:
    """Log + record an exception into the repair queue. Returns the fingerprint."""
    fp = fingerprint(exc, endpoint)
    tb = traceback.format_exc()
    logger.warning("Captured unhandled error %s (%s): %s",
                   fp, type(exc).__name__, exc)
    try:
        store.record_repair(fp, endpoint, tb)
    except Exception as elog:
        logger.exception("Failed to persist repair record (capture is best-effort): %s", elog)
    return fp


def retry_transient(fn, *args, attempts: int = 3, base: float = 0.5, **kwargs):
    """Call ``fn``, retrying only transient failures with exponential backoff.

    Deterministic exceptions (validation ValueError, a missing import, a typed
    bug) fail fast on the first call — there is nothing to gain from retrying a
    certainty. Transient failures back off 0.5, 1.0, ... and re-raise on the
    final attempt.
    """
    for attempt in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if not is_transient(exc):
                raise
            if attempt == attempts - 1:
                raise
            delay = base * (2 ** attempt)
            logger.info("Transient %s (%s); retry %d in %.1fs",
                        type(exc).__name__, exc, attempt + 1, delay)
            # time.sleep blocks a worker thread; the caller is expected to run
            # this off the event loop (asyncio.to_thread) like the rest of the
            # optimizer's SQLite/Cohere/Neo4j work.
            time.sleep(delay)


class CaptureMiddleware:
    """ASGI middleware: capture every exception that escapes, then re-raise.

    Re-raising (never swallowing) keeps the API's 500 contract intact — the
    plan's whole point. The captured repair-queue row is observability; the
    ServerErrorMiddleware is what shapes the actual 500 response.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        endpoint = scope.get("path")
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            try:
                capture(exc, endpoint)
            except Exception:
                logger.exception("CaptureMiddleware failed to capture an exception")
            raise


def diagnose(row: dict) -> dict:
    """Turn a repair-queue row into an operator-readable diagnosis."""
    tb = (row.get("traceback") or "") if isinstance(row, dict) else str(row)
    t = tb.lower()
    if "neo4j" in t or any(k in t for k in ("connection to bolt", "bolt://")):
        cause, hint = "Neo4j connection failed", "Verify NEO4J_URI / user / password and that the DB is reachable."
    elif "pinecone" in t or "upsert" in t:
        cause, hint = "Pinecone vector-store error", "Check the index name, API key, and that dimension matches the embedding model."
    elif "cohere" in t or "429" in t or "rate" in t:
        cause, hint = "Cohere rate limit or client error", "Check the Cohere API key and quota; retry is whitelisted for transient cases."
    elif "groq" in t:
        cause, hint = "Groq judge failed", "Verify GROQ_API_KEY and quota; a dead judge makes cycles skip, not fail silently."
    elif "timeout" in t or "timed out":
        cause, hint = "Request timed out", "Consider raising the timeout or reducing fan-out."
    else:
        cause, hint = "Unclassified exception", "Inspect the traceback and the endpoint/count below."
    return {
        "cause": cause,
        "hint": hint,
        "endpoint": row.get("endpoint") if isinstance(row, dict) else None,
        "count": row.get("count") if isinstance(row, dict) else None,
    }