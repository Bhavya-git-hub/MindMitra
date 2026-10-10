"""What happens to a student's message before any model sees it.

- Personal details (e-mail addresses, phone numbers, links, long numbers such as roll or ID
  numbers) are replaced with placeholders, so they never reach an external model provider.
- Requests the companion must not answer, a diagnosis or medication advice, are recognised
  here and answered from a fixed template instead of by the model.
- Attempts to rewrite the companion's rules ("ignore your instructions", "pretend you are a
  doctor") are answered from a template too, so the model never has to resist them.

Names cannot be reliably found by rules, so they may pass through; the system prompt tells the
model never to repeat or ask for personal details, and nothing identifying the student (name,
ids, institution) is ever added to what is sent.
"""

import dataclasses
import enum
import re

from safety.crisis_rules import normalise

MAX_MESSAGE_CHARS = 2000


class Intent(enum.StrEnum):
    CHAT = "chat"
    DIAGNOSIS_REQUEST = "diagnosis_request"
    MEDICATION_REQUEST = "medication_request"
    PROMPT_INJECTION = "prompt_injection"


@dataclasses.dataclass(frozen=True)
class GuardedInput:
    text: str  # scrubbed, ready for a model
    intent: Intent
    flags: tuple[str, ...]


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)\+?\d(?:[\s().-]?\d){7,14}(?!\w)")
# Roll numbers, registration and ID numbers: a word of 6+ letters/digits with 5+ digits.
_LONG_NUMBER = re.compile(r"\b(?=(?:[A-Za-z]*\d){5})[A-Za-z0-9]{6,}\b")

_CONDITIONS = (
    r"(?:an? )?(?:depress\w*|clinical depression|anxiety disorder|generali[sz]ed anxiety"
    r"|social anxiety|panic disorder|bipolar|adhd|autis\w*|ocd|ptsd|eating disorder"
    r"|anorexi\w*|bulimi\w*"
    r"|schizophreni\w*|psychosis|psychotic|borderline|bpd|personality disorder|insomnia"
    r"|a (?:mental )?(?:illness|disorder|condition)|mentally ill|a mental health condition)"
)
_DIAGNOSIS = re.compile(
    r"\b(?:do|could|might|may|can) i (?:have|be suffering from|be)\s+"
    + _CONDITIONS
    + r"|\bam i\s+(?:\w+\s+)?(?:depressed|bipolar|autistic|psychotic|anorexic|mentally ill"
    r"|ocd|adhd|crazy|having a breakdown)\b"
    + r"|\bdiagnos\w*\s+me\b|\bgive me a diagnosis\b|\bwhat (?:disorder|condition|illness)"
    r" (?:do i have|is this|could this be)\b"
    + r"|\b(?:is|could) (?:this|it|that) (?:be )?"
    + _CONDITIONS
    + r"|\b(?:test|screen|assess|check) me for\b"
)
_MEDICATIONS = (
    r"(?:ssris?|snris?|sertraline|zoloft|fluoxetine|prozac|escitalopram|lexapro|citalopram"
    r"|paroxetine|venlafaxine|bupropion|wellbutrin|xanax|alprazolam|clonazepam|klonopin"
    r"|lorazepam|ativan|diazepam|valium|benzo\w*|lithium|quetiapine|seroquel|olanzapine"
    r"|risperidone|aripiprazole|melatonin|zolpidem|ambien|trazodone|adderall|ritalin"
    r"|modafinil|antidepressants?|anti-depressants?|sleeping pills?|sedatives?|tranquili[sz]ers?"
    r"|meds|medication|medicines?|pills|tablets)"
)
_MEDICATION = re.compile(
    r"\b(?:should|can|could|do|would|shall) i (?:take|try|start|stop|quit|increase|decrease"
    r"|double|skip|get|be on|use)\b[^.?!]{0,40}?\b"
    + _MEDICATIONS
    + r"\b"
    + r"|\b(?:what|which|how much|how many)\s+(?:\w+\s+){0,3}?"
    + _MEDICATIONS
    + r"\s+(?:should|can|do|could|would)\b"
    + r"|\b(?:dose|dosage|how many mg|milligrams)\b"
    + r"|\b(?:recommend|suggest|prescribe)\s+(?:me\s+)?(?:a |an |some )?"
    + _MEDICATIONS
    + r"\b"
)
_INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|your\s+|the\s+|my\s+)*"
    r"(?:previous|prior|above|earlier|system|safety|original)?\s*"
    r"(?:instructions|rules|guidelines|prompt|restrictions|programming|policies)\b"
    r"|\b(?:you are|youre) now (?:a|an|in|called|named|free|unrestricted|dan)\b"
    r"|\bpretend (?:to be|you are|youre|that you are)\b"
    r"|\b(?:act|behave|respond|roleplay|role-play) as (?:a |an |my )?(?:licensed |real )?"
    r"(?:therapist|doctor|psychiatrist|psychologist|counsell?or|human|girlfriend|boyfriend"
    r"|partner|lover|different ai|unrestricted|jailbroken)\b"
    r"|\b(?:system prompt|developer mode|jailbreak|dan mode|do anything now)\b"
    r"|\b(?:reveal|show|print|repeat) (?:your|the) (?:system )?(?:prompt|instructions)\b"
)


def scrub(text: str) -> tuple[str, bool]:
    """Replace personal details with placeholders. Returns the text and whether anything
    was replaced."""
    out = _EMAIL.sub("[email]", text)
    out = _URL.sub("[link]", out)
    out = _PHONE.sub("[phone number]", out)
    out = _LONG_NUMBER.sub("[number]", out)
    return out, out != text


def classify_intent(text: str) -> Intent:
    t = normalise(text)
    if _INJECTION.search(t):
        return Intent.PROMPT_INJECTION
    if _MEDICATION.search(t):
        return Intent.MEDICATION_REQUEST
    if _DIAGNOSIS.search(t):
        return Intent.DIAGNOSIS_REQUEST
    return Intent.CHAT


def guard_input(text: str) -> GuardedInput:
    """Trim, cap the length, scrub personal details and recognise what must not reach a model."""
    trimmed = text.strip()[:MAX_MESSAGE_CHARS]
    scrubbed, changed = scrub(trimmed)
    intent = classify_intent(trimmed)
    flags: list[str] = []
    if changed:
        flags.append("pii_scrubbed")
    if intent is not Intent.CHAT:
        flags.append(intent.value)
    return GuardedInput(scrubbed, intent, tuple(flags))
