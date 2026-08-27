"""Provider-agnostic LLM interface (SPEC.md §17). Every provider implements
the same `stream()` contract; nothing outside this module ever imports a
provider SDK directly (CLAUDE.md §7).

`tools()` from SPEC.md §17 is deliberately not part of `LLMProvider` yet —
nothing calls it until the Agents phase, and adding it now would be unused
surface area (CLAUDE.md §2: implement only the current phase's scope).
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam as AnthropicMessageParam
from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger("helix.ai")

# {"role": "user" | "assistant", "content": str} — the same shape
# assistant/service.py already builds from Message history; both the
# Anthropic and OpenAI-compatible SDKs accept this directly.
Message = dict[str, str]


@dataclass
class TextDelta:
    text: str


@dataclass
class UsageInfo:
    input_tokens: int
    output_tokens: int


# $ per million tokens (input, output), verified against each provider's
# pricing page on 2026-08-27. Models absent from this table cost $0 in
# compute_cost() below — true for local Ollama models, and a safe default
# (not an inflated one) for anything else not yet priced here.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (2.0, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = MODEL_PRICING.get(model, (0.0, 0.0))
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def stream(
        self, system: str, messages: list[Message], model: str, max_tokens: int
    ) -> AsyncIterator[TextDelta | UsageInfo]:
        """Streams a single completion. Yields `TextDelta`s as they arrive,
        then exactly one final `UsageInfo` once the model is done."""


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    async def stream(
        self, system: str, messages: list[Message], model: str, max_tokens: int
    ) -> AsyncIterator[TextDelta | UsageInfo]:
        anthropic_messages = cast("list[AnthropicMessageParam]", messages)
        async with self._client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=anthropic_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield TextDelta(text)
            final_message = await stream.get_final_message()
            yield UsageInfo(
                input_tokens=final_message.usage.input_tokens,
                output_tokens=final_message.usage.output_tokens,
            )


class OpenAIProvider(LLMProvider):
    """Also backs `OllamaProvider` below — Ollama's local server speaks the
    same OpenAI-compatible Chat Completions API, so a second SDK isn't
    needed just to talk to it (CLAUDE.md §3: don't add a dependency for
    something an existing one already covers)."""

    name = "openai"

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key or "unused", base_url=base_url)

    async def stream(
        self, system: str, messages: list[Message], model: str, max_tokens: int
    ) -> AsyncIterator[TextDelta | UsageInfo]:
        openai_messages = [{"role": "system", "content": system}, *messages]
        stream = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            # `Message` is deliberately the generic {"role", "content"} shape
            # shared by every provider (see the module docstring), not
            # OpenAI's own granular ChatCompletionMessageParam union — this
            # is the one place that generic shape gets handed to a
            # provider-specific SDK call.
            messages=openai_messages,  # type: ignore[call-overload]
            stream=True,
            stream_options={"include_usage": True},
        )
        input_tokens = 0
        output_tokens = 0
        async for chunk in stream:
            if chunk.usage is not None:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
            if chunk.choices and chunk.choices[0].delta.content:
                yield TextDelta(chunk.choices[0].delta.content)
        yield UsageInfo(input_tokens=input_tokens, output_tokens=output_tokens)


class OllamaProvider(OpenAIProvider):
    name = "ollama"

    def __init__(self, base_url: str) -> None:
        # Ollama's OpenAI-compatible endpoint ignores the API key but the
        # SDK requires a non-empty value to construct the client.
        super().__init__(api_key="ollama", base_url=base_url)


@lru_cache
def get_provider(name: str) -> LLMProvider:
    settings = get_settings()
    if name == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key)
    if name == "openai":
        return OpenAIProvider(settings.openai_api_key)
    if name == "ollama":
        return OllamaProvider(settings.ollama_base_url)
    raise ValueError(f"unknown AI provider: {name!r}")
