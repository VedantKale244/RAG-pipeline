"""Tests for the Stripe subscription billing endpoints — no network.

The recipe: register a user (real SQLite store), log in, then exercise the
checkout + webhook flows while monkeypatching the ``stripe`` module so nothing
hits the network. The webhook test constructs a fake event dict and a fake
Stripe module whose ``Webhook.construct_event`` returns it.
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi.testclient import TestClient

from app.api import billing
from app.core import user_db
from app.main import app

client = TestClient(app)
_EMAIL = "billing@example.test"
_PW = "secret123"


@pytest.fixture(autouse=True)
def _stripe_settings(monkeypatch):
    monkeypatch.setattr(billing.settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(billing.settings, "stripe_webhook_secret", "whsec_test")
    monkeypatch.setattr(billing.settings, "stripe_pro_price_id", "price_test_pro")
    monkeypatch.setattr(billing.settings, "stripe_pro_yearly_price_id", "price_test_yearly")


@pytest.fixture(autouse=True)
def _clean_user():
    # Ensure a deterministic user every run regardless of previous test state.
    with user_db._get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id LIKE '%usr_bill%'")
        conn.execute("DELETE FROM users WHERE email = ?", (_EMAIL,))
        conn.commit()
    yield
    with user_db._get_db() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users WHERE email = ?", (_EMAIL,))
        conn.commit()


def _register_and_login() -> str:
    try:
        user_db.create_user("Billing Tester", _EMAIL, _PW)
    except ValueError:
        pass
    user_id = user_db.verify_user(_EMAIL, _PW)["id"]
    token = user_db.create_session(user_id)
    return token


def _fake_stripe_module(monkeypatch, event: dict | None = None):
    mod = types.ModuleType("stripe")
    mod.api_key = None
    mod.SignatureVerificationError = type("SignatureVerificationError", (Exception,), {})

    captured: dict = {}

    class _Session:
        @staticmethod
        def create(*args, **kwargs):
            captured["session_kwargs"] = kwargs
            return _Session()

        def __init__(self, *args, **kwargs):
            self.id = "cs_test_1"
            self.url = "https://checkout.stripe.test/pro"

    class _Checkout:
        Session = _Session

    mod.checkout = _Checkout()

    class _Webhook:
        @staticmethod
        def construct_event(payload, signature, secret):
            if secret != "whsec_test" or not signature:
                raise mod.SignatureVerificationError("invalid signature")
            return event or {}

    mod.Webhook = _Webhook
    monkeypatch.setitem(sys.modules, "stripe", mod)
    import stripe

    assert stripe is mod
    return captured


# ── POST /account/checkout ──────────────────────────────────────────────


class TestCheckout:
    def test_requires_auth(self):
        r = client.post("/account/checkout", json={"plan": "pro"})
        assert r.status_code == 401

    def test_rejects_unavailable_plan(self):
        token = _register_and_login()
        r = client.post(
            "/account/checkout",
            json={"plan": "enterprise"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400

    def test_returns_503_when_stripe_unconfigured(self, monkeypatch):
        monkeypatch.setattr(billing.settings, "stripe_secret_key", "")
        token = _register_and_login()
        r = client.post(
            "/account/checkout",
            json={"plan": "pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 503

    def test_creates_subscription_session(self, monkeypatch):
        captured = _fake_stripe_module(monkeypatch)
        token = _register_and_login()
        r = client.post(
            "/account/checkout",
            json={"plan": "pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["url"] == "https://checkout.stripe.test/pro"
        assert body["session_id"] == "cs_test_1"
        assert body["plan"] == "pro"
        assert captured["session_kwargs"]["mode"] == "subscription"
        assert captured["session_kwargs"]["line_items"] == [
            {"price": "price_test_pro", "quantity": 1}
        ]

    def test_yearly_uses_yearly_price(self, monkeypatch):
        captured = _fake_stripe_module(monkeypatch)
        token = _register_and_login()
        r = client.post(
            "/account/checkout",
            json={"plan": "pro_yearly"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["plan"] == "pro_yearly"
        assert captured["session_kwargs"]["line_items"] == [
            {"price": "price_test_yearly", "quantity": 1}
        ]

    def test_only_free_allowed_on_direct_plan_endpoint(self):
        # The old insurance: POST /account/plan must NOT grant paid plans.
        token = _register_and_login()
        r = client.post(
            "/account/plan",
            json={"plan": "pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
        r = client.post(
            "/account/plan",
            json={"plan": "free"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["plan"] == "free"


# ── POST /stripe/webhook ─────────────────────────────────────────────────


class TestWebhook:
    def test_503_when_webhook_secret_missing(self, monkeypatch):
        monkeypatch.setattr(billing.settings, "stripe_webhook_secret", "")
        r = client.post("/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "x"})
        assert r.status_code == 503

    def test_unverifiable_signature_rejected(self, monkeypatch):
        _fake_stripe_module(monkeypatch, event={})
        r = client.post(
            "/stripe/webhook",
            content=b'{"type":"checkout.session.completed"}',
            headers={"Stripe-Signature": ""},
        )
        assert r.status_code in (400, 401)

    def test_checkout_completed_grants_plan(self, monkeypatch):
        user_id = _register_and_login_as_user()
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "payment_status": "paid",
                    "metadata": {"user_id": user_id, "plan": "pro"},
                    "customer": "cus_123",
                    "subscription": "sub_456",
                }
            },
        }
        _fake_stripe_module(monkeypatch, event=event)
        r = client.post(
            "/stripe/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "signed"},
        )
        assert r.status_code == 200
        assert user_db.get_user_plan(user_id) == "pro"

    def test_subscription_deleted_downgrades_to_free(self, monkeypatch):
        user_id = _register_and_login_as_user()
        user_db.set_user_plan(user_id, "pro")
        user_db.set_stripe_account_links(user_id, "cus_123", "sub_456")
        event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"status": "canceled", "customer": "cus_123", "id": "sub_456"}},
        }
        _fake_stripe_module(monkeypatch, event=event)
        r = client.post(
            "/stripe/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "signed"},
        )
        assert r.status_code == 200
        assert user_db.get_user_plan(user_id) == "free"


def _register_and_login_as_user() -> str:
    try:
        user_db.create_user("Billing Tester", _EMAIL, _PW)
    except ValueError:
        pass
    return user_db.verify_user(_EMAIL, _PW)["id"]