"""Static plan registry (SPEC.md §16). Stripe's dashboard is the source of
truth for *pricing* -- this just maps a plan slug to the seat limit and
default AI cost cap it grants, and (for paid plans) the Stripe Price ID a
Checkout Session should sell. Flat-rate subscriptions, not per-seat metered
pricing -- the simplest Stripe setup that still satisfies "plans, seats,
quotas" for a v1 built by one person.

Not a DB table: these change only when a developer edits pricing/tiers,
never per-org -- a table would just be a slower way to read a constant.
"""

from dataclasses import dataclass

from app.core.config import get_settings

FREE_PLAN = "free"
PRO_PLAN = "pro"
ENTERPRISE_PLAN = "enterprise"


@dataclass(frozen=True)
class PlanConfig:
    seats_limit: int | None  # None = unlimited
    default_monthly_cost_cap_usd: float | None  # None = unlimited
    stripe_price_id: str | None  # None for the free plan -- no Stripe object needed


def get_plans() -> dict[str, PlanConfig]:
    """A function, not a module-level constant: the enterprise/pro Price
    IDs come from Settings (env-configured, differ per Stripe account), so
    this can't be resolved at import time the way a plain dict could.
    """
    settings = get_settings()
    return {
        FREE_PLAN: PlanConfig(
            seats_limit=3, default_monthly_cost_cap_usd=5.0, stripe_price_id=None
        ),
        PRO_PLAN: PlanConfig(
            seats_limit=20,
            default_monthly_cost_cap_usd=100.0,
            stripe_price_id=settings.stripe_price_id_pro or None,
        ),
        ENTERPRISE_PLAN: PlanConfig(
            seats_limit=None,
            default_monthly_cost_cap_usd=None,
            stripe_price_id=settings.stripe_price_id_enterprise or None,
        ),
    }


def get_plan(plan: str) -> PlanConfig:
    plans = get_plans()
    return plans.get(plan, plans[FREE_PLAN])
