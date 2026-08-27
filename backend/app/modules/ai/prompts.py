"""Versioned, templated prompts (SPEC.md §17 PromptRegistry). Prompts stay
plain Python — reviewable in a PR diff like any other code — addressed by
(name, version) instead of being ad-hoc constants scattered per module, so
a caller can pin a version and old versions stay available (e.g. for an
in-flight conversation, or an eval run pinned to what it was scored
against) after a new one ships.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    template: str

    def render(self, **variables: str) -> str:
        return self.template.format(**variables)


ASSISTANT_SYSTEM_PROMPT_V1 = Prompt(
    name="assistant_system",
    version=1,
    template="""You are the Helix assistant. Answer the user's question using ONLY \
the numbered context below, drawn from documents in their organization. Cite sources inline \
using [n], matching the context numbering. If the context does not contain enough information \
to answer, say so plainly instead of guessing or using outside knowledge.

Context:
{context}""",
)

NO_CONTEXT_PLACEHOLDER = (
    "(No relevant documents were found in the knowledge base for this question.)"
)

_REGISTRY: dict[str, dict[int, Prompt]] = {
    "assistant_system": {1: ASSISTANT_SYSTEM_PROMPT_V1},
}

# The version actually used for new completions. Bump this (and add a new
# Prompt above, never edit one in place) when the prompt text changes.
ASSISTANT_SYSTEM_PROMPT_CURRENT = ASSISTANT_SYSTEM_PROMPT_V1


def get_prompt(name: str, version: int) -> Prompt:
    try:
        return _REGISTRY[name][version]
    except KeyError as exc:
        raise ValueError(f"unknown prompt {name!r} version {version}") from exc
