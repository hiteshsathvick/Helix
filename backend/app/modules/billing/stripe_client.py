"""Thin wrapper around the `stripe` SDK (SPEC.md §16) -- every call site in
service.py goes through here, never `import stripe` directly, so tests can
monkeypatch these few functions instead of mocking the SDK's own client
objects. Unlike ai/providers.py's LLMProvider, this isn't a swappable
interface (there's exactly one payment processor here) -- just enough
indirection to keep tests offline, mirroring how notifications/providers.py
wraps smtplib for the same reason.
"""

import uuid
from typing import Any

import stripe

from app.core.config import get_settings


def _client() -> Any:
    stripe.api_key = get_settings().stripe_secret_key
    return stripe


def create_customer(org_id: uuid.UUID, org_name: str) -> str:
    customer = _client().Customer.create(name=org_name, metadata={"org_id": str(org_id)})
    return customer.id


def create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    org_id: uuid.UUID,
    plan: str,
    success_url: str,
    cancel_url: str,
) -> tuple[str, str]:
    """Returns (session_id, checkout_url). Metadata is set on both the
    Session (read by checkout.session.completed) and the Subscription it
    creates (read by customer.subscription.* -- Stripe doesn't copy
    Session metadata onto the Subscription automatically), so every event
    type billing/service.py handles can resolve org_id/plan without a
    price-ID reverse lookup.
    """
    session = _client().checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(org_id),
        metadata={"org_id": str(org_id), "plan": plan},
        subscription_data={"metadata": {"org_id": str(org_id), "plan": plan}},
    )
    return session.id, session.url


def cancel_subscription_at_period_end(subscription_id: str) -> None:
    _client().Subscription.modify(subscription_id, cancel_at_period_end=True)


def construct_webhook_event(payload: bytes, signature_header: str, webhook_secret: str) -> Any:
    """Raises stripe.error.SignatureVerificationError on a tampered or
    stale payload -- the router translates that into a 400."""
    return stripe.Webhook.construct_event(payload, signature_header, webhook_secret)
