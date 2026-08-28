from typing import Literal

from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    plan: Literal["pro", "enterprise"]


class CheckoutResponse(BaseModel):
    checkout_url: str


class BillingSummary(BaseModel):
    plan: str
    status: str
    seats_used: int
    seats_limit: int | None
    monthly_cost_cap_usd: float | None


class UsageByKind(BaseModel):
    kind: str
    quantity: int
    cost_usd: float


class UsageSummary(BaseModel):
    month: str  # "2026-08"
    items: list[UsageByKind]
    total_cost_usd: float
    monthly_cost_cap_usd: float | None
