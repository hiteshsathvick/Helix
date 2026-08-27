"""Cost/limit guard (SPEC.md §17). Pure config-resolution + comparison —
callers own querying their own tables for `spent_usd` (CLAUDE.md §3: a
module never queries another module's tables directly, so `assistant` sums
its own `messages.cost` and passes the total in here, rather than this
module importing `assistant.models.Message`).
"""

from app.core.config import get_settings
from app.core.errors import QuotaExceededError


def resolve_monthly_cost_cap(org_settings: dict) -> float | None:
    cap = org_settings.get("ai_monthly_cost_cap_usd")
    if cap is not None:
        return float(cap)
    return get_settings().ai_default_monthly_cost_cap_usd


def enforce_cost_cap(spent_usd: float, cap_usd: float | None) -> None:
    if cap_usd is not None and spent_usd >= cap_usd:
        raise QuotaExceededError(
            "organization AI usage cap reached for this billing period",
            details={"cap_usd": cap_usd, "spent_usd": spent_usd},
        )
