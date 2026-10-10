"""One companion turn: safety layer, then (maybe) the model, then the safety layer again.

    message -> crisis rules -> input guard -> topic + context -> prompt -> provider
            -> output guard (+ crisis rules on the draft) -> reply

The model is never called for a crisis, a diagnosis or medication request, or an attempt to
change the companion's rules; those get fixed replies (crisis replies are written by the API,
next to the crisis contacts). A model reply that fails any check is replaced, never trimmed.
A provider failure gives a fixed "try again" reply; it never hides a crisis, because the crisis
rules ran first.
"""

import dataclasses
import enum
from collections.abc import Sequence

from app.companion.context import Turn, build_context
from app.companion.prompts import build_system_prompt
from app.companion.topics import Topic, detect_topic
from app.providers.base import GenerationRequest, LLMProvider, ProviderError
from safety import templates
from safety.crisis_rules import CrisisResult, detect
from safety.input_guard import Intent, guard_input
from safety.output_guard import check_output


class ReplyKind(enum.StrEnum):
    REPLY = "reply"  # from the model, checked
    CRISIS = "crisis"  # no reply here: the API answers with resources and alerts a person
    REDIRECT = "redirect"  # a fixed reply to something the companion must not answer
    FALLBACK = "fallback"  # the model's reply failed a check and was replaced
    UNAVAILABLE = "unavailable"  # the model could not be reached


@dataclasses.dataclass(frozen=True)
class TurnResult:
    kind: ReplyKind
    reply: str | None
    crisis: CrisisResult
    topic: Topic
    flags: tuple[str, ...]
    model_id: str | None


_REDIRECTS = {
    Intent.DIAGNOSIS_REQUEST: templates.DIAGNOSIS_REQUEST,
    Intent.MEDICATION_REQUEST: templates.MEDICATION_REQUEST,
    Intent.PROMPT_INJECTION: templates.PROMPT_INJECTION,
}


async def respond(
    provider: LLMProvider, message: str, history: Sequence[Turn], *, max_tokens: int
) -> TurnResult:
    crisis = detect(message)
    if crisis.crisis:
        return TurnResult(ReplyKind.CRISIS, None, crisis, Topic.GENERAL, ("crisis",), None)

    guarded = guard_input(message)
    earlier = [t.content for t in history if t.role == "user"]
    topic = detect_topic(guarded.text, earlier)
    flags = list(guarded.flags)
    if crisis.show_resources:
        flags.append("support_resources")

    redirect = _REDIRECTS.get(guarded.intent)
    if redirect is not None:
        return TurnResult(ReplyKind.REDIRECT, redirect, crisis, topic, tuple(flags), None)

    context = build_context(history, guarded.text)
    if context.trimmed:
        flags.append("context_trimmed")
    if context.suggest_human_support:
        flags.append("suggest_human_support")
    request = GenerationRequest(
        system=build_system_prompt(topic, suggest_human_support=context.suggest_human_support),
        messages=context.messages,
        max_tokens=max_tokens,
        topic=topic,
    )
    try:
        draft = await provider.generate(request)
    except ProviderError:
        flags.append("provider_error")
        return TurnResult(
            ReplyKind.UNAVAILABLE, templates.UNAVAILABLE, crisis, topic, tuple(flags), None
        )

    check = check_output(draft)
    violations = list(check.violations)
    if detect(draft).crisis:
        violations.append("crisis_language")
    if violations:
        flags.extend(f"output_guard:{v}" for v in violations)
        return TurnResult(
            ReplyKind.FALLBACK,
            templates.SAFE_FALLBACK,
            crisis,
            topic,
            tuple(flags),
            provider.model_id,
        )
    return TurnResult(ReplyKind.REPLY, draft, crisis, topic, tuple(flags), provider.model_id)
