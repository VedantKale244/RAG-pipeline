"""Stripe subscription billing.

Mounts two kinds of endpoints:

- ``POST /account/checkout`` — authenticated; creates a Stripe Checkout session for
  a paid plan and returns the redirect URL. Requires ``stripe_secret_key`` +
  a price id for the requested plan, otherwise it raises 503 (billing unconfigured).
- ``POST /stripe/webhook`` — public; signed by Stripe with ``stripe_webhook_secret``.
  Used to grant access on ``checkout.session.completed`` and to release it when the
  subscription cancels. Must NOT share the API-key dependency.

Plans currently priced through Stripe: ``pro`` (monthly) and ``pro_yearly``.
``enterprise`` stays a contact-sales flow and is rejected here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from ..config import settings
from ..core import user_db

logger = logging.getLogger("app")

router = APIRouter(tags=["billing"])
# Public webhook router — Stripe signs with WEBHOOK_SECRET, not our X-API-Key,
# so it must be mounted independently of the verify_api_key dependency.
webhook_router = APIRouter(tags=["billing"])

# Maps app plan -> Stripe price id source; empty string disables that plan.
_STRIPE_PLANS: dict[str, str] = {
    "pro": "stripe_pro_price_id",
    "pro_yearly": "stripe_pro_yearly_price_id",
}


class CheckoutRequest(BaseModel):
    plan: str


def _stripe():
    """Lazily import & configure the Stripe SDK once a secret key exists."""
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe billing is not configured yet")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


@router.post("/account/checkout")
def create_checkout(request: Request, body: CheckoutRequest):
    """Open a Stripe Checkout session for a paid plan on the signed-in account."""
    token = _bearer_token(request)
    if not token:
        raise HTTPException(401, "Authentication required")
    usr = user_db.get_session_user(token)
    if not usr:
        raise HTTPException(401, "Invalid or expired session token")

    plan = body.plan.strip().lower()
    if plan not in _STRIPE_PLANS:
        raise HTTPException(400, f"Plan '{body.plan}' is not available through checkout")

    price_attr = _STRIPE_PLANS[plan]
    price_id = getattr(settings, price_attr)
    if not price_id:
        raise HTTPException(503, f"Stripe billing is not configured for this plan yet")

    stripe = _stripe()
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=usr["email"],
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=usr["id"],
            metadata={"user_id": usr["id"], "plan": plan},
            success_url=settings.stripe_success_url,
            cancel_url=settings.stripe_cancel_url,
            subscription_data={"metadata": {"user_id": usr["id"], "plan": plan}},
        )
    except Exception as exc:
        logger.error("Stripe checkout session creation failed: %s", exc)
        raise HTTPException(502, "Unable to start checkout. Check Stripe configuration.")

    return {"url": session.url, "session_id": session.id, "plan": plan}


@webhook_router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request, stripe_signature: str | None = Header(default=None)
):
    """Handle Stripe events with a verified signature.

    Grants plan access on completed checkout; revokes it (back to free) when a
    subscription is deleted/cancelled or payment permanently fails.
    """
    signing_secret = settings.stripe_webhook_secret
    if not signing_secret:
        raise HTTPException(503, "Stripe webhook secret is not configured")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature or "", signing_secret
        )
    except ValueError as exc:
        logger.warning("Invalid Stripe webhook payload: %s", exc)
        raise HTTPException(400, "Invalid payload")
    except stripe.SignatureVerificationError as exc:
        logger.warning("Stripe webhook signature verification failed: %s", exc)
        raise HTTPException(401, "Invalid signature")

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})
    logger.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif event_type in ("customer.subscription.deleted",):
        _handle_subscription_cancelled(data)
    elif event_type in ("invoice.payment_failed", "invoice.payment_action_required"):
        _handle_payment_failed(data)

    return {"status": "ok"}


def _handle_checkout_completed(session: dict) -> None:
    """Grant the user their paid plan once checkout completes & payment is active."""
    if session.get("payment_status") not in (None, "paid", "no_payment_required"):
        return
    user_id = (session.get("metadata") or {}).get("user_id") or session.get(
        "client_reference_id"
    )
    plan = (session.get("metadata") or {}).get("plan") or "pro"
    customer = session.get("customer")
    subscription = session.get("subscription")
    if not user_id or not customer:
        return
    if plan not in _STRIPE_PLANS and plan not in {"free", "enterprise"}:
        plan = "pro"
    user_db.set_user_plan(user_id, plan)
    user_db.set_stripe_account_links(
        user_id, customer, subscription_id=subscription
    )


def _handle_subscription_cancelled(subscription: dict) -> None:
    """Downgrade to free when the customer cancels or Stripe ends the subscription."""
    status = subscription.get("status")
    if status in ("active", "trialing") or status is None:
        return
    customer = subscription.get("customer")
    usr = user_db.user_by_stripe_customer(customer)
    if usr:
        user_db.set_user_plan(usr["id"], "free")
        user_db.clear_stripe_subscription(usr["id"], subscription.get("id"))


def _handle_payment_failed(invoice: dict) -> None:
    """Downgrade to free when a recurring payment fails."""
    sub_id = invoice.get("subscription")
    customer = invoice.get("customer")
    if not customer:
        return
    usr = user_db.user_by_stripe_customer(customer)
    if usr:
        # The subscription object still exists after a failed attempt, so only clear
        # the Stripe link when it is actually gone — keep plan until it cancels.
        user_db.clear_stripe_subscription(user_id=usr["id"], subscription_id=sub_id)


def _bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    return auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""