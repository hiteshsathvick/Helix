import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from app.core.config import get_settings

logger = logging.getLogger("helix.ai")


@dataclass
class TextDelta:
    text: str


@dataclass
class UsageInfo:
    input_tokens: int
    output_tokens: int


# $ per million tokens (input, output). Verified against
# https://platform.claude.com/docs/en/about-claude/pricing on 2026-08-26.
# Phase 11's real provider abstraction replaces this with something that
# doesn't need updating by hand.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (2.0, 10.0),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = MODEL_PRICING.get(model, (0.0, 0.0))
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


@lru_cache
def _get_client() -> AsyncAnthropic:
    settings = get_settings()
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


async def stream_completion(
    system: str, messages: list[MessageParam], max_tokens: int
) -> AsyncIterator[TextDelta | UsageInfo]:
    """Streams a single completion. Yields `TextDelta`s as they arrive,
    then exactly one final `UsageInfo` once the model is done — callers
    that only care about the text can ignore anything that isn't a
    `TextDelta`; callers that need cost/token accounting (assistant.service,
    for persisting `messages.tokens`/`messages.cost`) get it without a
    second round trip.
    """
    settings = get_settings()
    client = _get_client()

    async with client.messages.stream(
        model=settings.llm_model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield TextDelta(text)
        final_message = await stream.get_final_message()
        yield UsageInfo(
            input_tokens=final_message.usage.input_tokens,
            output_tokens=final_message.usage.output_tokens,
        )
