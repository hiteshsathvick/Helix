import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from opentelemetry.trace import Span
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.metrics import (
    llm_cost_usd_total,
    llm_request_duration_seconds,
    llm_requests_total,
    llm_tokens_total,
)
from app.core.tenancy import set_tenant_context
from app.core.tracing import tracer
from app.modules.ai.providers import (
    Message,
    TextDelta,
    ToolCall,
    ToolCompletionResult,
    ToolSpec,
    UsageInfo,
    compute_cost,
    get_provider,
)
from app.modules.ai.schemas import OrgAIConfigUpdate
from app.modules.audit import service as audit_service
from app.modules.orgs import service as orgs_service

logger = logging.getLogger("helix.ai")

__all__ = [
    "Message",
    "TextDelta",
    "UsageInfo",
    "ToolSpec",
    "ToolCall",
    "ToolCompletionResult",
    "compute_cost",
    "resolve_org_ai_config",
    "update_org_ai_config",
    "stream_completion",
    "complete_with_tools",
    "tool_result_messages",
    "OrgAIConfig",
]


@dataclass(frozen=True)
class OrgAIConfig:
    provider: str
    model: str
    monthly_cost_cap_usd: float | None


def _record_usage(span: Span, provider_name: str, model_name: str, usage: UsageInfo) -> None:
    """Shared by stream_completion and complete_with_tools -- the one place
    a call's token/cost numbers become both span attributes and Prometheus
    counters, so the two never drift out of sync with each other."""
    cost = compute_cost(model_name, usage.input_tokens, usage.output_tokens)
    span.set_attribute("ai.input_tokens", usage.input_tokens)
    span.set_attribute("ai.output_tokens", usage.output_tokens)
    span.set_attribute("ai.cost_usd", cost)
    llm_tokens_total.labels(provider_name, model_name, "input").inc(usage.input_tokens)
    llm_tokens_total.labels(provider_name, model_name, "output").inc(usage.output_tokens)
    llm_cost_usd_total.labels(provider_name, model_name).inc(cost)


def _default_model_for(provider: str, settings: Settings) -> str:
    return {
        "anthropic": settings.llm_model,
        "openai": settings.openai_model,
        "ollama": settings.ollama_model,
        # MockProvider (ai/providers.py, Phase 20) ignores the model name
        # entirely -- this placeholder just has to be a non-empty string so
        # AI_DEFAULT_PROVIDER=mock doesn't KeyError here.
        "mock": "mock-model",
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
    db: AsyncSession, org_id: uuid.UUID, update: OrgAIConfigUpdate, actor_id: uuid.UUID
) -> OrgAIConfig:
    patch: dict[str, str | float | None] = {}
    if update.provider is not None:
        patch["ai_provider"] = update.provider
    if update.model is not None:
        patch["ai_model"] = update.model
    if "monthly_cost_cap_usd" in update.model_fields_set:
        patch["ai_monthly_cost_cap_usd"] = update.monthly_cost_cap_usd
    await orgs_service.update_org_settings(db, org_id, patch)
    # update_org_settings already committed (it's a shared utility other
    # callers -- e.g. billing's plan-cap reset -- also use, so it isn't
    # this function's place to hold that commit open) -- a fresh commit
    # here for the audit row is the simplest correct option, at the cost
    # of one extra round trip for a config change, not a hot path.
    await set_tenant_context(db, org_id)
    await audit_service.record(
        db,
        org_id,
        actor_id,
        "ai_config.updated",
        resource_type="org",
        resource_id=org_id,
        metadata=patch,
    )
    await db.commit()
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
    start = time.perf_counter()
    status = "error"
    with tracer.start_as_current_span("ai.stream_completion") as span:
        span.set_attribute("ai.provider", provider_name)
        span.set_attribute("ai.model", model_name)
        try:
            async for event in llm.stream(system, messages, model_name, max_tokens):
                if isinstance(event, UsageInfo):
                    _record_usage(span, provider_name, model_name, event)
                yield event
            status = "success"
        finally:
            llm_request_duration_seconds.labels(provider_name, model_name).observe(
                time.perf_counter() - start
            )
            llm_requests_total.labels(provider_name, model_name, status).inc()


async def complete_with_tools(
    system: str,
    messages: list[Message],
    max_tokens: int,
    tools: list[ToolSpec],
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ToolCompletionResult:
    """One non-streaming, tool-calling-capable turn (SPEC.md §19 agent
    runtime) via the resolved provider."""
    settings = get_settings()
    provider_name = provider or settings.ai_default_provider
    model_name = model or _default_model_for(provider_name, settings)
    llm = get_provider(provider_name)
    start = time.perf_counter()
    status = "error"
    with tracer.start_as_current_span("ai.complete_with_tools") as span:
        span.set_attribute("ai.provider", provider_name)
        span.set_attribute("ai.model", model_name)
        try:
            result = await llm.complete_with_tools(system, messages, model_name, max_tokens, tools)
            _record_usage(span, provider_name, model_name, result.usage)
            status = "success"
            return result
        finally:
            llm_request_duration_seconds.labels(provider_name, model_name).observe(
                time.perf_counter() - start
            )
            llm_requests_total.labels(provider_name, model_name, status).inc()


def tool_result_messages(
    provider: str, tool_calls: list[ToolCall], results: dict[str, dict[str, Any]]
) -> list[Message]:
    return get_provider(provider).tool_result_messages(tool_calls, results)
