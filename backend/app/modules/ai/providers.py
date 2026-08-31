"""Provider-agnostic LLM interface (SPEC.md §17). Every provider implements
the same `stream()`/`complete_with_tools()` contract; nothing outside this
module ever imports a provider SDK directly (CLAUDE.md §7).
"""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam as AnthropicMessageParam
from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger("helix.ai")

# {"role": ..., "content": ...} — usually {"role": "user"|"assistant",
# "content": str} (assistant/service.py's shape), but a value can also be a
# provider-native structured block list: the agents module (Phase 12) never
# builds these by hand, it only ever appends what
# `complete_with_tools`/`tool_result_messages` below hand back, so each
# provider's own format round-trips through its own calls untouched.
Message = dict[str, Any]


@dataclass
class TextDelta:
    text: str


@dataclass
class UsageInfo:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the tool's input object


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolCompletionResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The exact message to append to history representing this turn, in
    # whichever provider-native shape produced it — see the `Message` note
    # above.
    assistant_message: Message = field(default_factory=dict)
    usage: UsageInfo = field(default_factory=lambda: UsageInfo(0, 0))


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

    @abstractmethod
    async def complete_with_tools(
        self,
        system: str,
        messages: list[Message],
        model: str,
        max_tokens: int,
        tools: list[ToolSpec],
    ) -> ToolCompletionResult:
        """One non-streaming turn with tool-calling available (SPEC.md §19
        agent runtime). Never streamed — the agents loop needs the complete
        set of tool calls before it can execute any of them."""

    @abstractmethod
    def tool_result_messages(
        self, tool_calls: list[ToolCall], results: dict[str, dict[str, Any]]
    ) -> list[Message]:
        """Builds the message(s) representing tool results, in whatever
        shape this provider's API expects them fed back as (a single
        multi-block message for Anthropic, one message per call for
        OpenAI-shaped APIs — hence a list, not one `Message`). `results` maps
        `ToolCall.id` to that call's JSON-serializable result."""


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

    async def complete_with_tools(
        self,
        system: str,
        messages: list[Message],
        model: str,
        max_tokens: int,
        tools: list[ToolSpec],
    ) -> ToolCompletionResult:
        anthropic_tools = [
            {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
            for tool in tools
        ]
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=cast("list[AnthropicMessageParam]", messages),
            tools=anthropic_tools,  # type: ignore[arg-type]
        )
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id, name=block.name, arguments=cast("dict[str, Any]", block.input)
                    )
                )
        return ToolCompletionResult(
            text="".join(text_parts),
            tool_calls=tool_calls,
            assistant_message={
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            },
            usage=UsageInfo(
                input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens
            ),
        )

    def tool_result_messages(
        self, tool_calls: list[ToolCall], results: dict[str, dict[str, Any]]
    ) -> list[Message]:
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": json.dumps(results[call.id]),
                    }
                    for call in tool_calls
                ],
            }
        ]


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

    async def complete_with_tools(
        self,
        system: str,
        messages: list[Message],
        model: str,
        max_tokens: int,
        tools: list[ToolSpec],
    ) -> ToolCompletionResult:
        openai_messages = [{"role": "system", "content": system}, *messages]
        openai_tools: list[dict[str, Any]] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]
        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=openai_messages,  # type: ignore[arg-type]
            tools=openai_tools,  # type: ignore[arg-type]
        )
        choice = response.choices[0].message
        # Only "function" tool calls are possible here — every tool advertised
        # above is function-typed, so the SDK's "custom" tool-call variant
        # (which lacks `.function`) never actually occurs in a response.
        tool_calls = [
            ToolCall(
                id=call.id, name=call.function.name, arguments=json.loads(call.function.arguments)
            )
            for call in (choice.tool_calls or [])
            if call.type == "function"
        ]
        assistant_message: Message = {"role": "assistant", "content": choice.content or ""}
        if choice.tool_calls:
            assistant_message["tool_calls"] = [call.model_dump() for call in choice.tool_calls]
        usage = response.usage
        return ToolCompletionResult(
            text=choice.content or "",
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            usage=UsageInfo(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
        )

    def tool_result_messages(
        self, tool_calls: list[ToolCall], results: dict[str, dict[str, Any]]
    ) -> list[Message]:
        return [
            {"role": "tool", "tool_call_id": call.id, "content": json.dumps(results[call.id])}
            for call in tool_calls
        ]


class OllamaProvider(OpenAIProvider):
    name = "ollama"

    def __init__(self, base_url: str) -> None:
        # Ollama's OpenAI-compatible endpoint ignores the API key but the
        # SDK requires a non-empty value to construct the client.
        super().__init__(api_key="ollama", base_url=base_url)


class MockProvider(LLMProvider):
    """Deterministic, zero-cost provider for e2e/load-testing (Phase 20) --
    exercises the real streaming/tool-calling wiring end-to-end without a
    real LLM call. Reachable only via the operator-level
    AI_DEFAULT_PROVIDER setting: `ai/schemas.py`'s KNOWN_PROVIDERS
    deliberately excludes "mock", so no org can ever select it through
    `PUT /orgs/{id}/ai-config` -- this is a test/CI-only knob, not a
    user-facing option."""

    name = "mock"
    _ANSWER = "This is a mock response from the test LLM provider."

    async def stream(
        self, system: str, messages: list[Message], model: str, max_tokens: int
    ) -> AsyncIterator[TextDelta | UsageInfo]:
        for word in self._ANSWER.split(" "):
            yield TextDelta(word + " ")
        yield UsageInfo(input_tokens=10, output_tokens=len(self._ANSWER.split(" ")))

    async def complete_with_tools(
        self,
        system: str,
        messages: list[Message],
        model: str,
        max_tokens: int,
        tools: list[ToolSpec],
    ) -> ToolCompletionResult:
        # Always answers directly, never calls a tool -- keeps agent/
        # workflow-AI-node runs a deterministic single step, matching the
        # default mock in test_agents.py/test_workflows.py.
        return ToolCompletionResult(
            text=self._ANSWER,
            tool_calls=[],
            assistant_message={"role": "assistant", "content": self._ANSWER},
            usage=UsageInfo(input_tokens=10, output_tokens=len(self._ANSWER.split(" "))),
        )

    def tool_result_messages(
        self, tool_calls: list[ToolCall], results: dict[str, dict[str, Any]]
    ) -> list[Message]:
        # Never actually invoked (complete_with_tools above never returns a
        # tool call to run), but required by the LLMProvider interface.
        return [
            {"role": "tool", "tool_call_id": call.id, "content": json.dumps(results[call.id])}
            for call in tool_calls
        ]


@lru_cache
def get_provider(name: str) -> LLMProvider:
    settings = get_settings()
    if name == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key)
    if name == "openai":
        return OpenAIProvider(settings.openai_api_key)
    if name == "ollama":
        return OllamaProvider(settings.ollama_base_url)
    if name == "mock":
        return MockProvider()
    raise ValueError(f"unknown AI provider: {name!r}")
