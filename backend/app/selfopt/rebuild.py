"""Data-layer rebuilds: shadow re-chunk / re-embed / graph rebuild + atomic swap (Spec §7).

``chunk_size``/``chunk_overlap``/``entity_match_threshold``/``graph_confidence_threshold``
only take effect on re-ingested data, so a challenger that perturbs one of those is
materialized here in shadow storage and only swapped in on a win. Rebuilds are the
expensive, rate-limited operation — the budget tiers below bound Cohere spend.
"""
from __future__ import annotations

import logging
import time

from ..config import settings
from . import store

logger = logging.getLogger(__name__)

# Rebuild budget (Spec §7.3), scoped by corpus size.
_BUDGET_TIERS = [
    (2000, 1.0, None),           # < 2000 chunks → everything
    (10000, 0.25, 500),          # 2000–10000 → 25%, capped 500
    (float("inf"), 0.10, 1000),  # > 10000 → 10%, capped 1000
]
# Rebuilds rate-limited to one per 24h regardless of scheduler demand.
_REBUILD_COOLDOWN_S = 24 * 3600
_SHADOW_GRACE_S = 3600  # 1h grace window before tearing down the outgoing generation


def shadow_id(version: str, document_id: str, n: int) -> str:
    """Shadow vector id so the existing prefix-scan delete can tear it down."""
    return f"sel{version}-{document_id}-{int(n)}"


def rebuild_budget(total_chunks: int) -> int:
    """How many chunks this rebuild cycle is allowed to re-embed."""
    for threshold, frac, cap in _BUDGET_TIERS:
        if total_chunks < threshold:
            n = int(total_chunks * frac)
            return min(n, cap) if cap else n
    return 0


def can_rebuild() -> bool:
    """Fence: at most one rebuild per 24h. False if within the cooldown window."""
    last = store.get_state("last_rebuild_at")
    if not last:
        return True
    try:
        elapsed = time.time() - float(last)
    except ValueError:
        return True
    return elapsed >= _REBUILD_COOLDOWN_S


def mark_rebuilt() -> None:
    store.set_state("last_rebuild_at", str(time.time()))
    store.record_activity("rebuild", "shadow rebuild scheduled (24h fence held)", None)


def swap_in(version: str) -> None:
    """Point the active shadow pointer at `version` (atomic pointer flip)."""
    store.set_state("active_shadow_version", version)
    store.set_state("swap_in_at", str(time.time()))


def eligible_for_teardown(version: str, now: float | None = None) -> bool:
    """True when a swapped-out generation has passed its 1h grace window."""
    t = now or time.time()
    raw = store.get_state("swap_in_at")
    if not raw:
        return False
    try:
        swapped = float(raw)
    except ValueError:
        return False
    return t - swapped >= _SHADOW_GRACE_S


def teardown(version: str) -> None:
    """Remove a shadow generation: shadow vectors + shadow graph nodes.

    Kept defensive — a stub/silently-unavailable Nebula must not crash a cycle.
    """
    try:
        from ..core import vectorstore
        vectorstore.delete_shadow(version)
    except Exception as exc:
        logger.warning("Shadow vector teardown for %s incomplete: %s", version, exc)
    try:
        from ..core.clients import neo4j_driver
        with neo4j_driver().session() as session:
            session.run(
                "MATCH (n:Chunk {selfopt_version: $v}) DETACH DELETE n",
                v=version,
            )
    except Exception as exc:
        try:
            from ..core.fallback_graph import delete_shadow
            delete_shadow(version)
        except Exception:
            logger.warning("Shadow graph teardown for %s incomplete: %s", version, exc)