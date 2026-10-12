"""What the model sees of a conversation.

Only the current conversation, and only its recent part: the last ``MAX_TURNS`` messages that
fit in ``MAX_CONTEXT_CHARS``, newest kept first. Earlier conversations, check-ins, journals,
other people and any identifiers are never included (the API does not send them). Every
earlier student message is scrubbed of personal details again, since rules may have improved
since it was written. An earlier message the input guard refuses (an attempt to change the
companion's rules, a request for a diagnosis or medication advice) is left out together with
the fixed reply to it, so a refused message cannot reach the model one turn later.
"""

import dataclasses
from collections.abc import Sequence
from typing import Final, Literal

from safety.crisis_rules import Action, detect
from safety.input_guard import Intent, classify_intent, scrub

MAX_TURNS: Final = 12
MAX_CONTEXT_CHARS: Final = 8000
NUDGE_EVERY_USER_TURNS: Final = 10

Role = Literal["user", "assistant"]


@dataclasses.dataclass(frozen=True)
class Turn:
    role: Role
    content: str


@dataclasses.dataclass(frozen=True)
class Context:
    messages: tuple[Turn, ...]  # ready for a provider: starts with the user, alternates
    earlier_user_messages: tuple[str, ...]
    suggest_human_support: bool
    trimmed: bool


def _merge(turns: Sequence[Turn]) -> list[Turn]:
    """Providers expect user and assistant turns to alternate, starting with the user."""
    out: list[Turn] = []
    for t in turns:
        if out and out[-1].role == t.role:
            out[-1] = Turn(t.role, out[-1].content + "\n\n" + t.content)
        else:
            out.append(t)
    while out and out[0].role != "user":
        out.pop(0)
    return out


def _without_refused(history: Sequence[Turn]) -> list[Turn]:
    """``history`` without refused student messages and the assistant reply that follows each."""
    out: list[Turn] = []
    refused = False
    for turn in history:
        if turn.role == "user":
            refused = classify_intent(turn.content) is not Intent.CHAT
            if refused:
                continue
        elif refused:
            refused = False
            continue
        out.append(turn)
    return out


def build_context(history: Sequence[Turn], message: str) -> Context:
    """``history`` is oldest first and does not include ``message`` (already scrubbed)."""
    allowed = _without_refused(history)
    recent: list[Turn] = []
    used = len(message)
    for turn in reversed(allowed[-MAX_TURNS:]):
        content = scrub(turn.content)[0] if turn.role == "user" else turn.content
        if used + len(content) > MAX_CONTEXT_CHARS:
            break
        recent.append(Turn(turn.role, content))
        used += len(content)
    recent.reverse()
    trimmed = len(recent) < len(allowed)
    messages = _merge([*recent, Turn("user", message)])

    earlier_user = tuple(t.content for t in history if t.role == "user")
    user_turns = len(earlier_user) + 1
    distress_now = detect(message).action is Action.REVIEW
    distress_before = any(detect(t).action is not Action.NONE for t in earlier_user[-4:])
    suggest = (user_turns % NUDGE_EVERY_USER_TURNS == 0) or (distress_now and distress_before)
    return Context(tuple(messages), earlier_user, suggest, trimmed)
