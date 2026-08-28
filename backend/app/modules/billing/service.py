import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError
from app.core.tenancy import set_tenant_context
from app.modules.billing import stripe_client
from app.modules.billing.models import Subscription, UsageEvent
from app.modules.billing.plans import get_plan
from app.modules.billing.schemas import BillingSummary, UsageByKind, UsageSummary
from app.modules.orgs import service as orgs_service

logger = logging.getLogger("helix.billing")


def _month_start() -> datetime:
    return datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _get_or_create_subscription(db: AsyncSession, org_id: uuid.UUID) -> Subscription:
    await set_tenant_context(db, org_id)
    result = await db.execute(select(Subscription).where(Subscription.org_id == org_id))
    subscription = result.scalar_one_or_none()
    if subscription is not None:
        return subscription

    subscription = Subscription(org_id=org_id)
    db.add(subscription)
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(subscription)
    return subscription


async def get_billing_summary(db: AsyncSession, org_id: uuid.UUID) -> BillingSummary:
    org = await orgs_service.get_organization(db, org_id)
    subscription = await _get_or_create_subscription(db, org_id)
    members = await orgs_service.list_org_members(db, org_id)
    plan_config = get_plan(org.plan)
    ai_config = await orgs_service.get_org_settings(db, org_id)
    cap = ai_config.get("ai_monthly_cost_cap_usd")
    cap_usd = float(cap) if cap is not None else plan_config.default_monthly_cost_cap_usd
    return BillingSummary(
        plan=org.plan,
        status=subscription.status,
        seats_used=len(members),
        seats_limit=plan_config.seats_limit,
        monthly_cost_cap_usd=cap_usd,
    )


async def start_checkout(db: AsyncSession, org_id: uuid.UUID, plan: str) -> str:
    org = await orgs_service.get_organization(db, org_id)
    plan_config = get_plan(plan)
    if plan_config.stripe_price_id is None:
        raise ConflictError(
            f"plan {plan!r} has no Stripe price configured "
            "(set STRIPE_PRICE_ID_PRO / STRIPE_PRICE_ID_ENTERPRISE)"
        )

    subscription = await _get_or_create_subscription(db, org_id)
    if subscription.stripe_customer_id is None:
        subscription.stripe_customer_id = stripe_client.create_customer(org_id, org.name)
        await db.commit()

    settings = get_settings()
    _session_id, checkout_url = stripe_client.create_checkout_session(
        customer_id=subscription.stripe_customer_id,
        price_id=plan_config.stripe_price_id,
        org_id=org_id,
        plan=plan,
        success_url=settings.stripe_checkout_success_url.format(org_id=org_id),
        cancel_url=settings.stripe_checkout_cancel_url.format(org_id=org_id),
    )
    return checkout_url


async def cancel_subscription(db: AsyncSession, org_id: uuid.UUID) -> None:
    subscription = await _get_or_create_subscription(db, org_id)
    if subscription.stripe_subscription_id is None:
        raise ConflictError("organization has no active Stripe subscription to cancel")
    stripe_client.cancel_subscription_at_period_end(subscription.stripe_subscription_id)
    logger.info("subscription cancellation scheduled: org=%s", org_id)


async def _apply_plan(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    plan: str,
    status: str,
    stripe_customer_id: str | None,
    stripe_subscription_id: str | None,
    seats: int,
) -> None:
    """Single place a webhook event lands a plan change -- keeps
    `subscriptions` (the Stripe-linked record) and `Organization.plan` (the
    fast path every quota/cap check reads) in sync, and resets the org's AI
    cost cap to the new plan's included amount so upgrading actually raises
    what the org can spend without a separate admin action. An admin can
    still tighten it further afterward via the existing PUT /ai-config.
    """
    await set_tenant_context(db, org_id)
    result = await db.execute(select(Subscription).where(Subscription.org_id == org_id))
    subscription = result.scalar_one_or_none()
    if subscription is None:
        subscription = Subscription(org_id=org_id)
        db.add(subscription)

    subscription.plan = plan
    subscription.status = status
    subscription.seats = seats
    if stripe_customer_id is not None:
        subscription.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id is not None:
        subscription.stripe_subscription_id = stripe_subscription_id
    await db.commit()

    await orgs_service.update_org_plan(db, org_id, plan)
    plan_config = get_plan(plan)
    await orgs_service.update_org_settings(
        db, org_id, {"ai_monthly_cost_cap_usd": plan_config.default_monthly_cost_cap_usd}
    )
    logger.info("org %s plan updated to %s (status=%s)", org_id, plan, status)


def _resolve_org_id(obj: Any) -> uuid.UUID | None:
    """Every Session/Subscription object this app creates carries org_id in
    its own metadata (stripe_client.py sets it on both) -- deliberately the
    *only* way a webhook resolves which org it belongs to. A customer-id
    lookup on `subscriptions` would need to run before that org's RLS
    context is known, i.e. with no tenant context set at all, which the
    table's FORCE ROW LEVEL SECURITY policy would silently turn into "no
    rows" -- not a real fallback, just a confusing way to drop the event.
    A subscription edited directly in the Stripe dashboard (bypassing our
    Checkout flow, so no metadata) is out of scope for v1: the event is
    logged and ignored rather than guessed at.
    """
    metadata = obj.get("metadata") or {}
    raw = metadata.get("org_id")
    return uuid.UUID(raw) if raw else None


async def handle_webhook_event(db: AsyncSession, event: Any) -> None:
    """Dispatches a verified Stripe event (router.py already checked the
    signature). Unknown event types are ignored, not errors -- Stripe sends
    far more event types than we subscribe to; erroring on the rest would
    turn "we don't care about this one" into a retried failure on Stripe's
    side.
    """
    event_type = event["type"]
    obj = event["data"]["object"]

    org_id = _resolve_org_id(obj)
    if org_id is None:
        logger.warning("%s with no org_id metadata, ignoring", event_type)
        return
    await set_tenant_context(db, org_id)

    if event_type == "checkout.session.completed":
        plan = (obj.get("metadata") or {}).get("plan", "free")
        await _apply_plan(
            db,
            org_id,
            plan=plan,
            status="active",
            stripe_customer_id=obj.get("customer"),
            stripe_subscription_id=obj.get("subscription"),
            seats=1,
        )

    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        plan = (obj.get("metadata") or {}).get("plan")
        if plan is None:
            # No metadata to trust for the plan slug -- keep whatever plan
            # is already on file rather than guessing from the price ID.
            existing = await db.execute(select(Subscription).where(Subscription.org_id == org_id))
            row = existing.scalar_one_or_none()
            plan = row.plan if row is not None else "free"
        items = (obj.get("items") or {}).get("data") or [{}]
        seats = items[0].get("quantity", 1) if items else 1
        await _apply_plan(
            db,
            org_id,
            plan=plan,
            status=obj.get("status", "active"),
            stripe_customer_id=obj.get("customer"),
            stripe_subscription_id=obj.get("id"),
            seats=seats,
        )

    elif event_type == "customer.subscription.deleted":
        await _apply_plan(
            db,
            org_id,
            plan="free",
            status="canceled",
            stripe_customer_id=obj.get("customer"),
            stripe_subscription_id=None,
            seats=1,
        )

    else:
        logger.info("ignoring unhandled Stripe event type: %s", event_type)


async def record_usage(
    db: AsyncSession, org_id: uuid.UUID, kind: str, quantity: int, cost: float
) -> None:
    """Callers add this row and let their own already-imminent commit
    persist it -- see UsageEvent's docstring. Must run inside a session
    whose tenant context is already set (every call site is deep inside an
    already org-scoped flow)."""
    db.add(
        UsageEvent(
            org_id=org_id, kind=kind, quantity=quantity, cost=cost, occurred_at=datetime.now(UTC)
        )
    )


async def get_monthly_usage_usd(db: AsyncSession, org_id: uuid.UUID) -> float:
    """The org-wide total this phase introduces -- replaces the three
    independent, only-sees-its-own-table sums assistant/agents/workflows
    each used before (see their `_get_monthly_spend` helpers, now removed
    in favor of this)."""
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(func.coalesce(func.sum(UsageEvent.cost), 0.0)).where(
            UsageEvent.org_id == org_id, UsageEvent.occurred_at >= _month_start()
        )
    )
    return float(result.scalar_one())


async def get_usage_summary(db: AsyncSession, org_id: uuid.UUID) -> UsageSummary:
    await set_tenant_context(db, org_id)
    month_start = _month_start()
    result = await db.execute(
        select(
            UsageEvent.kind,
            func.coalesce(func.sum(UsageEvent.quantity), 0),
            func.coalesce(func.sum(UsageEvent.cost), 0.0),
        )
        .where(UsageEvent.org_id == org_id, UsageEvent.occurred_at >= month_start)
        .group_by(UsageEvent.kind)
    )
    rows = result.all()
    items = [
        UsageByKind(kind=kind, quantity=int(quantity), cost_usd=float(cost))
        for kind, quantity, cost in rows
    ]
    org = await orgs_service.get_organization(db, org_id)
    org_settings = await orgs_service.get_org_settings(db, org_id)
    cap = org_settings.get("ai_monthly_cost_cap_usd")
    cap_usd = float(cap) if cap is not None else get_plan(org.plan).default_monthly_cost_cap_usd
    return UsageSummary(
        month=month_start.strftime("%Y-%m"),
        items=items,
        total_cost_usd=sum(item.cost_usd for item in items),
        monthly_cost_cap_usd=cap_usd,
    )
