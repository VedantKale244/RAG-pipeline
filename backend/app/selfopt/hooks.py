"""Lifecycle hooks that feed the optimizer from live traffic (Spec §6).

These are the minimal, side-effect-safe entry points the chat/feedback API
routes call. They must never throw — a hook failure must never take down a
production answer.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import Iterator

from .overrides import active_version as active_version_ctx

_CANARY_PERCENT = 15  # selfopt_canary_percent


def canary(who: str) -> bool:
    """Deterministic, sticky 15% bucket. Beta counters key only canary traffic."""
    bucket = int(hashlib.sha256(who.encode("utf-8")).hexdigest(), 16) % 100
    return bucket < _CANARY_PERCENT


@contextmanager
def canary_scope(who: str) -> Iterator[str | None]:
    """Context that applies the challenger config for this request, if any.

    Only canary-bucketed users see the experimental challenger values; everyone
    else reads the champion. Yields the attribution version (or None when the
    request serves the live champion config).
    """
    from . import overrides, store

    version = active_version_ctx()
    if version is None:
        yield None
        return
    if not canary(who):
        yield None
        return
    stored = store.get_version(version)
    params = (stored or {}).get("parameters_json") or {}
    with overrides.challenger(params, version):
        yield version


def observe(*, who: str, latency_ms: int) -> None:
    """Attribute a production answer to the active challenger (if any) and record it."""
    from . import metrics

    version = active_version_ctx()
    if version is None:
        return  # champion traffic is covered by rolling champion metrics separately
    if not canary(who):
        return
    try:
        metrics.record_request(version, latency_ms)
    except Exception:
        pass


def observe_feedback(*, who: str, thumbs_up: bool, rating: float | None = None) -> None:
    """Attribute a feedback vote to the version that served the request."""
    from . import metrics

    version = active_version_ctx()
    if version is None or not canary(who):
        return
    try:
        metrics.record_vote(version, positive=thumbs_up, rating=rating)
    except Exception:
        pass