"""API-key auth dependency.

Fail-open when no key is configured (so local dev isn't broken); enforce a 401
only once ``settings.api_key`` is set. The key may arrive either as an
``X-API-Key`` header (normal fetch calls) or an ``api_key`` query param — the
latter is required for the SSE endpoint, since the browser EventSource API
cannot send custom headers.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Request

from .config import settings

logger = logging.getLogger("app")
_warned = False


async def verify_api_key(request: Request) -> None:
    expected = settings.api_key
    if not expected:
        global _warned
        if not _warned:
            logger.warning("API_KEY is not set — API endpoints are unauthenticated.")
            _warned = True
        return

    provided = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(401, "Invalid or missing API key")
