import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.ai.providers import Message, TextDelta, UsageInfo, compute_cost, get_provider
from app.modules.ai.schemas import OrgAIConfigUpdate
from app.modules.orgs import service as orgs_service

logger = logging.getLogger("helix.ai")

__all__ = [
    "TextDelta",
    "UsageInfo",
    "compute_cost",
    "resolve_org_ai_config",
    "update_org_ai_config",
    "stream_completion",
    "OrgAIConfig",
]


@dataclass(frozen=True)
class OrgAIConfig:
    provider: str
    model: str
    monthly_cost_cap_usd: float | None


def _default_model_for(provider: str, settings: Settings) -> str:
    return {
        "anthropic": settings.llm_model,
        "openai": settings.openai_model,
        "ollama": settings.ollama_model,
    }[provider]


async def resolve_org_ai_config(db: AsyncSession, org_id: uuid.UUID) -> OrgAIConfig:
    settings = get_settings()
    org_settings = await orgs_service.get_org_settings(db, org_id)
    provider = org_settings.get("ai_provider") or settings.ai_default_provider
    model = org_settings.get("ai_model") or _default_model_for(provider, settings)
    # A key present with value None (an org that explicitly cleared its
    # override — OrgAIConfigUpdate's docstring) falls through to the global
    # default exactly like a missing key, via `or` rather than `.get(key,
    # default)` which would only catch the missing-key case.
    org_cap = org_settings.get("ai_monthly_cost_cap_usd")
    cap = org_cap if org_cap is not None else settings.ai_default_monthly_cost_cap_usd
    return OrgAIConfig(
        provider=provider, model=model, monthly_cost_cap_usd=cap if cap is None else float(cap)
    )


async def update_org_ai_config(
    db: AsyncSession, org_id: uuid.UUID, update: OrgAIConfigUpdate
) -> OrgAIConfig:
    patch: dict[str, str | float | None] = {}
    if update.provider is not None:
        patch["ai_provider"] = update.provider
    if update.model is not None:
        patch["ai_model"] = update.model
    if "monthly_cost_cap_usd" in update.model_fields_set:
        patch["ai_monthly_cost_cap_usd"] = update.monthly_cost_cap_usd
    await orgs_service.update_org_settings(db, org_id, patch)
    return await resolve_org_ai_config(db, org_id)


async def stream_completion(
    system: str,
    messages: list[Message],
    max_tokens: int,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> AsyncIterator[TextDelta | UsageInfo]:
    """Streams a single completion via the resolved provider. Yields
    `TextDelta`s as they arrive, then exactly one final `UsageInfo` — callers
    that only care about the text can ignore anything that isn't a
    `TextDelta`; callers that need cost/token accounting (assistant.service,
    for persisting `messages.tokens`/`messages.cost`) get it without a second
    round trip.
    """
    settings = get_settings()
    provider_name = provider or settings.ai_default_provider
    model_name = model or _default_model_for(provider_name, settings)
    llm = get_provider(provider_name)
    async for event in llm.stream(system, messages, model_name, max_tokens):
        yield event
