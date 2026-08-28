import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import TenantScopedMixin, TimestampMixin, UUIDPKMixin


class Subscription(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    """One row per org (org_id unique below), tracking the Stripe side of
    billing. `plan` here is the pending/Stripe-confirmed value during a
    checkout round trip; `Organization.plan` (Phase 6, unused until now) is
    the fast-path field every quota/cap check reads -- the webhook handler
    updates both together so they never drift.
    """

    __tablename__ = "subscriptions"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, unique=True, index=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), default=None)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), default=None)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    # Stripe subscription quantity -- 1 for v1's flat-rate plans (see
    # plans.py), not a per-seat metered price. Kept as its own column
    # (mirrors SPEC.md §10) rather than always reading `1` so a later move
    # to per-seat pricing doesn't need a schema change.
    seats: Mapped[int] = mapped_column(default=1)
    # "none" (never subscribed) | Stripe's own subscription statuses
    # ("active", "trialing", "past_due", "canceled", "incomplete", ...)
    status: Mapped[str] = mapped_column(String(50), default="none")


class UsageEvent(UUIDPKMixin, TenantScopedMixin, Base):
    """Append-only usage ledger (SPEC.md §10) -- one row per completed
    AI-costing unit of work (an assistant query, a finished agent run, one
    workflow AI-node execution), written at the same point each producing
    module already persists its own cost onto its own row. This table is
    what finally gives the org a *single* cross-surface total (see
    service.py::get_monthly_usage_usd) instead of the three independent,
    only-sees-its-own-table sums assistant/agents/workflows each used
    before this phase.

    No TimestampMixin: `occurred_at` (attributable to the actual usage
    instant, not row-insert time -- they're the same in practice today
    since every producer records synchronously, but keeping the concept
    distinct costs nothing and matches SPEC.md §10's column name) is this
    table's own timestamp instead.
    """

    __tablename__ = "usage_events"

    # "assistant_query" | "agent_run" | "workflow_ai_node"
    kind: Mapped[str] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(default=0)  # total tokens for AI kinds
    cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
