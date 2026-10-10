"""The interface every language-model provider implements.

Adding a provider (for example Amazon Bedrock, or a model hosted in the institution's own
account) means writing one class with ``model_id`` and ``generate`` and registering it in
``app.providers.factory``. Nothing else changes. Any provider used with real students must not
train on or retain what it is sent (see ADR 0010).
"""

import dataclasses
from typing import Protocol

from app.companion.context import Turn
from app.companion.topics import Topic


@dataclasses.dataclass(frozen=True)
class GenerationRequest:
    system: str
    messages: tuple[Turn, ...]
    max_tokens: int
    # A hint for providers that do not run a real model; real providers ignore it.
    topic: Topic = Topic.GENERAL


class ProviderError(Exception):
    """The provider failed. The message is safe to log: it never holds text or secrets."""


class LLMProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    async def generate(self, request: GenerationRequest) -> str: ...

    async def aclose(self) -> None: ...
