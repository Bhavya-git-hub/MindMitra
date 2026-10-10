"""When to *show support information* after a check-in or a message.

This is not triage: it only decides whether the confirmation screen leads with kind words and
a link to help. It never creates an alert or contacts anyone. It errs on the side of showing
the prompt (any crisis rule, including the gentle tier, counts), and a missed phrase is never a
reason to think someone is fine.
"""

from app.domain.safety.crisis_rules import detect

_PHRASES = (
    "kill myself",
    "end my life",
    "end it all",
    "suicid",
    "want to die",
    "don't want to be here",
    "do not want to be here",
    "hurt myself",
    "harm myself",
    "self harm",
    "self-harm",
    "no reason to live",
    "better off without me",
)


def show_support_prompt(*, mood_score: int, stress_level: int | None, note: str | None) -> bool:
    if mood_score <= 1:
        return True
    if stress_level is not None and stress_level >= 5:
        return True
    if note:
        lowered = note.lower()
        return any(p in lowered for p in _PHRASES) or detect(note).show_resources
    return False
