"""Providers that misbehave on purpose, to prove the safety layer holds."""

from app.providers.base import GenerationRequest, ProviderError


class ScriptedProvider:
    """Replies with whatever it is told to, and records what it was asked."""

    model_id = "scripted-1"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> str:
        self.requests.append(request)
        return self.reply

    async def aclose(self) -> None:
        return None


class BrokenProvider:
    model_id = "broken-1"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: GenerationRequest) -> str:
        self.calls += 1
        raise ProviderError("provider timed out")

    async def aclose(self) -> None:
        return None
