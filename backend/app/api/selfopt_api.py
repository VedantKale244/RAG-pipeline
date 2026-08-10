"""Admin self-optimization API (Spec §11). All routes sit behind the admin passcode.

Read-only status/diagnostics plus deliberate manual-control knobs: rollback,
baseline re-pin, pause/resume, wake-from-hibernation, and tombstone revival.
Every side effect is explicit and auditable through the same store.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..selfopt import experiment, guardian, scheduler, store
from .admin import verify_admin_access

router = APIRouter(tags=["selfopt"])


@router.get("/admin/selfopt/status")
async def status(request: Request) -> dict:
    await verify_admin_access(request)
    from ..selfopt import overrides

    return {
        "enabled": store.get_tombstone() is None,
        "tombstoned": store.get_tombstone() is not None,
        "champion_version": store.get_champion_version(),
        "champion": store.get_champion(),
        "lifecycle_stage": guardian.get_lifecycle_stage(),
        "consecutive_failures": _failure_count(),
        "active_version": overrides.active_version(),
        "next_trigger": _next_trigger(),
        "rebuild_fence_clear": _rebuild_fence_clear(),
    }


def _rebuild_fence_clear() -> bool:
    try:
        from ..selfopt import rebuild
        return rebuild.can_rebuild()
    except Exception:
        return False


def _failure_count() -> int:
    try:
        return int(store.get_state(guardian._STATE_FAILURES) or 0)
    except (TypeError, ValueError):
        return 0


def _next_trigger() -> str | None:
    try:
        fired = scheduler.evaluate_triggers()
        return " | ".join(fired) if fired else None
    except Exception:
        return None


@router.get("/admin/selfopt/history")
async def history(request: Request) -> dict:
    await verify_admin_access(request)
    return {"versions": await run_in_threadpool(store.get_all_versions)}


@router.get("/admin/selfopt/metrics")
async def metrics_ts(request: Request, version: str | None = None) -> dict:
    await verify_admin_access(request)
    return {
        "composite": store.recent_metrics(version, "composite"),
        "latency_p95_ms": store.recent_metrics(version, "latency_p95_ms"),
    }


@router.get("/admin/selfopt/errors")
async def errors_report(request: Request) -> dict:
    await verify_admin_access(request)
    return {"repairs": await run_in_threadpool(store.list_repairs)}


@router.get("/admin/selfopt/activity")
async def activity_feed(request: Request, limit: int = 200) -> dict:
    await verify_admin_access(request)
    return {"activities": await run_in_threadpool(store.list_activities, limit)}


@router.post("/admin/selfopt/rollback/{version}")
async def rollback_version(request: Request, version: str) -> dict:
    await verify_admin_access(request)
    if store.get_version(version) is None:
        raise HTTPException(404, f"no version {version}")
    restored = await run_in_threadpool(experiment.rollback, version, "admin-initiated")
    store.record_activity("admin", f"manual rollback to {version}", version)
    return {"status": "rolled_back", "restored": restored}


@router.post("/admin/selfopt/baseline")
async def repin_baseline(request: Request, value: float) -> dict:
    await verify_admin_access(request)
    store.set_baseline("edge_baseline", str(value))
    store.record_activity("admin", f"edge baseline deliberately re-pinned to {value}")
    return {"status": "re-pinned", "edge_baseline": value}


@router.post("/admin/selfopt/pause")
async def pause(request: Request) -> dict:
    await verify_admin_access(request)
    store.set_state(guardian._STATE_PAUSED, "1")
    store.record_activity("admin", "optimizer paused by operator")
    return {"status": "paused"}


@router.post("/admin/selfopt/resume")
async def resume(request: Request) -> dict:
    await verify_admin_access(request)
    store.set_state(guardian._STATE_PAUSED, "0")
    store.record_activity("admin", "optimizer resumed by operator")
    return {"status": "resumed"}


@router.post("/admin/selfopt/wake")
async def wake(request: Request) -> dict:
    await verify_admin_access(request)
    store.set_state(guardian._STATE_STAGE, guardian.STAGE_HEALTHY)
    store.set_state(guardian._STATE_FAILURES, "0")
    store.record_activity("admin", "woken from hibernation by operator")
    return {"status": "woken", "lifecycle_stage": guardian.STAGE_HEALTHY}


@router.delete("/admin/selfopt/tombstone")
async def revive(request: Request) -> dict:
    await verify_admin_access(request)
    store.clear_tombstone()
    store.record_activity("admin", "self-destruct tombstone cleared; optimizer revived")
    return {"status": "revived", "tombstoned": False}