"""LangSmith observability setup.

LangChain reads LangSmith configuration from process environment variables, so we mirror
the pydantic settings into `os.environ` once at startup. Import and call
`init_observability()` from the FastAPI lifespan.
"""
from __future__ import annotations

import os

from .config import settings


def init_observability() -> bool:
    """Wire LangSmith tracing. Returns True if tracing is active."""
    if not (settings.langchain_tracing_v2 and settings.langchain_api_key):
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint
    return True
