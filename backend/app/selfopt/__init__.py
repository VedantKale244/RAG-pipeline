"""Self-optimization subsystem for adaptive RAG pipeline tuning."""
from __future__ import annotations

import logging

from ..config import settings
from . import overrides, store

logger = logging.getLogger(__name__)


def init() -> None:
    """One-time startup wiring. Safe to call repeatedly.

    Order matters: the tombstone-gate runs *before* overrides install, so a
    dead instance drops straight to pass-through (spec §8.3.5) and never
    re-installs an override layer.
    """
    store.init_db()

    if store.get_tombstone() is not None:
        settings.selfopt_enabled = False
        logger.warning("selfopt tombstoned; optimizer disabled and overrides dropped")
        overrides.release_all()
        return

    if not settings.selfopt_enabled:
        return

    overrides.install()
    overrides.sync_champion_changes()


def shutdown() -> None:
    """Release the override layer (drop-to-pass-through)."""
    overrides.release_all()