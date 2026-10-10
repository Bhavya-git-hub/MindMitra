"""Self-report wellbeing instrument served by the API and scored on the server.

The five-item WHO-5 Well-Being Index (World Health Organization, 1998) may be used freely with
attribution. A score is a *snapshot of how someone felt over two weeks*. It is never presented
as a diagnosis, and the bands below deliberately use supportive, non-clinical wording.
"""

import dataclasses
from collections.abc import Mapping

INSTRUMENT_ID = "wellbeing_index_5"  # matches the identifier already used by the seed data
INSTRUMENT_VERSION = "1"
INSTRUMENT_TITLE = "Wellbeing check (WHO-5)"
INSTRUMENT_INTRO = (
    "For each statement, choose the answer that is closest to how you have been feeling "
    "over the last two weeks."
)
ATTRIBUTION = "World Health Organization (1998), Well-Being Index (WHO-5)."
DISCLAIMER = (
    "This is a short self-reflection tool. It is not a diagnosis and not a substitute for "
    "talking to a professional. If you are worried about how you feel, a counsellor is happy to "
    "talk with you."
)

OPTIONS: tuple[tuple[int, str], ...] = (
    (0, "At no time"),
    (1, "Some of the time"),
    (2, "Less than half of the time"),
    (3, "More than half of the time"),
    (4, "Most of the time"),
    (5, "All of the time"),
)


@dataclasses.dataclass(frozen=True)
class Question:
    key: str
    text: str


QUESTIONS: tuple[Question, ...] = (
    Question("q1", "I have felt cheerful and in good spirits"),
    Question("q2", "I have felt calm and relaxed"),
    Question("q3", "I have felt active and vigorous"),
    Question("q4", "I woke up feeling fresh and rested"),
    Question("q5", "My daily life has been filled with things that interest me"),
)

MAX_SCORE = 5 * len(QUESTIONS)


class InvalidResponses(ValueError):
    """Answers are missing, unknown or out of range."""


def score(responses: Mapping[str, int]) -> int:
    expected = {q.key for q in QUESTIONS}
    if set(responses) != expected:
        raise InvalidResponses("Please answer every question.")
    total = 0
    for key, value in responses.items():
        if isinstance(value, bool) or not 0 <= value <= 5:
            raise InvalidResponses(f"Answer for {key} must be between 0 and 5.")
        total += value
    return total


def percentage(raw_score: float) -> int:
    """WHO-5 convention: raw score x 4 gives a 0-100 scale."""
    return round(raw_score * 100 / MAX_SCORE)


@dataclasses.dataclass(frozen=True)
class Band:
    key: str
    label: str
    message: str


def band(raw_score: float) -> Band:
    pct = raw_score * 100 / MAX_SCORE
    if pct >= 68:
        return Band("doing_well", "Doing well", "You've been feeling fairly good lately.")
    if pct >= 52:
        return Band("mixed", "Mixed", "Some good days and some harder ones, which is common.")
    return Band(
        "lower",
        "Lower lately",
        "It sounds like things have felt heavier. Talking with someone can help, and you "
        "don't have to wait for a crisis to ask.",
    )
