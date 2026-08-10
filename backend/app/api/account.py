"""Plan gating & usage endpoints: GET /usage, POST /account/plan."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..core import user_db
from ..core.quota import usage_snapshot

router = APIRouter(tags=["account"])


class PlanRequest(BaseModel):
    plan: str


def _bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    return auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""


def _resolve_usage_user(request: Request) -> str:
    """Return the user_id the caller's requests are charged against."""
    token = _bearer_token(request)
    if token:
        return user_db.resolve_user_id(token)
    return "guest_sess_anon_usage"


@router.get("/usage")
def get_usage(request: Request):
    """Return the caller's plan plus today's remaining counters for the HUD."""
    return usage_snapshot(_resolve_usage_user(request))


@router.post("/account/plan")
def set_plan(request: Request, body: PlanRequest):
    """Set the caller's plan. Only ``free`` (downgrade) is allowed here — paid
    plans are granted exclusively by the Stripe webhook after real payment."""
    token = _bearer_token(request)
    if not token:
        raise HTTPException(401, "Authentication required")
    usr = user_db.get_session_user(token)
    if not usr:
        raise HTTPException(401, "Invalid or expired session token")

    plan = body.plan.strip().lower()
    if plan != "free":
        raise HTTPException(403, "Paid plans require Stripe checkout - see POST /account/checkout")

    if not user_db.set_user_plan(usr["id"], "free"):
        raise HTTPException(404, "Account not found")
    return {"status": "ok", "plan": "free"}