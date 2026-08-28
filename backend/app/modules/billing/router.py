import logging
import uuid

import stripe
from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_db
from app.core.errors import UnauthorizedError
from app.modules.billing import service, stripe_client
from app.modules.billing.schemas import (
    BillingSummary,
    CheckoutRequest,
    CheckoutResponse,
    UsageSummary,
)
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_BILLING_MANAGE

logger = logging.getLogger("helix.billing")

router = APIRouter(prefix="/orgs/{org_id}", tags=["billing"])


@router.get("/billing", response_model=BillingSummary)
async def get_billing(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_BILLING_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> BillingSummary:
    return await service.get_billing_summary(db, org_id)


@router.post("/billing/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutRequest,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_BILLING_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    checkout_url = await service.start_checkout(db, org_id, body.plan)
    return CheckoutResponse(checkout_url=checkout_url)


@router.post("/billing/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_billing(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_BILLING_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.cancel_subscription(db, org_id)


@router.get("/usage", response_model=UsageSummary)
async def get_usage(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_BILLING_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> UsageSummary:
    return await service.get_usage_summary(db, org_id)


# A single, global endpoint -- Stripe doesn't know our org_id URL scheme,
# and one webhook signing secret covers the whole Stripe account. org_id is
# resolved from event payload metadata instead (billing/service.py). Same
# "unauthenticated but verified" shape as workflows' webhook router, just
# with Stripe's HMAC-timestamp scheme instead of a per-workflow secret
# header.
webhooks_router = APIRouter(prefix="/webhooks/stripe", tags=["billing"])


@webhooks_router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
) -> None:
    payload = await request.body()
    settings = get_settings()
    try:
        event = stripe_client.construct_webhook_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        logger.warning("rejected Stripe webhook: %s", exc)
        raise UnauthorizedError("invalid Stripe webhook signature") from exc

    await service.handle_webhook_event(db, event)
