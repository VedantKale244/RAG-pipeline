"""Shared slowapi rate limiter.

One process-global limiter keyed by client IP. `main.py` registers it on the app
and wires the 429 handler; the write/expensive routers import `limiter` to decorate
their handlers. In-memory storage is fine for a single-instance deploy — swap in a
Redis storage URI here if this ever runs multi-worker.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# ponytail: in-memory store, single instance. Point at Redis if scaled horizontally.
limiter = Limiter(key_func=get_remote_address)
