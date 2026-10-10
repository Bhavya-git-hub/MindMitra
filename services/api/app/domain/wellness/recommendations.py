"""Rule-based, explainable recommendations (source ``rule``; no model involved).

Each rule looks at a small summary of the student's recent self-reports and suggests an
optional, low-effort idea. Wording is supportive and never diagnostic or directive; every
suggestion states why it was made so the student can judge it for themselves.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class Facts:
    """What the rules may look at. All values describe the last 7 days of self-reports."""

    avg_mood: float | None
    avg_stress: float | None
    avg_sleep_minutes: float | None
    days_since_check_in: int | None  # None: never checked in
    has_active_goal: bool
    latest_assessment_band: str | None  # "doing_well" | "mixed" | "lower"


@dataclasses.dataclass(frozen=True)
class Suggestion:
    key: str
    title: str
    rationale: str
    tags: tuple[str, ...]  # tags to look for when choosing a resource to attach
    suggests_counselling: bool = False


def suggest(facts: Facts) -> list[Suggestion]:
    out: list[Suggestion] = []
    if facts.days_since_check_in is None or facts.days_since_check_in >= 3:
        out.append(
            Suggestion(
                "check_in_nudge",
                "Take a minute to check in",
                "You haven't checked in for a few days. A quick check-in helps you spot "
                "patterns, and it only takes a minute.",
                (),
            )
        )
    if facts.avg_stress is not None and facts.avg_stress >= 3.5:
        out.append(
            Suggestion(
                "stress_skills",
                "Try a short exercise to settle your stress",
                "Your stress has been on the higher side this week. A few minutes of "
                "breathing or grounding can take the edge off.",
                ("breathing", "grounding", "stress"),
            )
        )
    if facts.avg_sleep_minutes is not None and facts.avg_sleep_minutes < 360:
        out.append(
            Suggestion(
                "sleep_routine",
                "Ease into a better wind-down",
                "You've been sleeping under 6 hours on average this week. A steadier evening "
                "routine can help.",
                ("sleep", "routine"),
            )
        )
    low_mood = facts.avg_mood is not None and facts.avg_mood < 2.5
    low_assessment = facts.latest_assessment_band == "lower"
    if low_mood or low_assessment:
        out.append(
            Suggestion(
                "talk_to_someone",
                "Consider talking with someone",
                "Things have felt heavier lately. You don't need to wait for a crisis: the "
                "campus counselling team is there for exactly this.",
                ("counselling", "support", "campus"),
                suggests_counselling=True,
            )
        )
        out.append(
            Suggestion(
                "gentle_mindfulness",
                "Give yourself a gentle pause",
                "A short guided practice can be a kind way to reset on a heavy day.",
                ("mindfulness", "relaxation"),
            )
        )
    if not facts.has_active_goal and facts.days_since_check_in is not None:
        out.append(
            Suggestion(
                "set_a_goal",
                "Set one small wellness goal",
                "Small, specific goals are easier to keep. Pick one thing you'd like to "
                "do more of.",
                (),
            )
        )
    return out
