"""Sanitized error responses — log the real exception, return an opaque ref to the client."""
from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException

logger = logging.getLogger("app")


class SearchUnavailable(RuntimeError):
    """Raised when the vector search infrastructure itself failed.

    Distinct from "retrieval returned no results": this signals the search
    service could not be reached, so an empty candidate list must NOT be
    conflated with "no relevant context found".
    """


def internal_error(exc: Exception) -> HTTPException:
    """Log the full exception under a random ref id; return a 500 that leaks nothing."""
    error_id = uuid.uuid4().hex[:12]
    logger.exception("Unhandled error (ref: %s)", error_id)
    return HTTPException(500, f"Internal error (ref: {error_id})")
