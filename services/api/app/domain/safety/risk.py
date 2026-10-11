"""Risk levels and the concerns the safety system can name (ADR 0013).

Neither is a diagnosis. A level says how urgently a person should be involved; a concern says
what kind of words or pattern raised it. Nothing here describes what a student *has*.
"""

import enum


class RiskLevel(enum.StrEnum):
    # Nothing concerning was found. This is never a statement that someone is fine: the rules
    # miss things, so help stays one tap away whatever the level.
    LOW = "low"
    # Signs of distress: kind words, contacts and counsellor access. Nobody is alerted.
    MODERATE = "moderate"
    # Words suggesting the student may not be safe: normal suggestions stop, support comes
    # first, and a person is asked to reach out where the policy allows.
    HIGH = "high"
    # Signs of immediate danger (a plan, means, a time, an emergency): emergency contacts come
    # first and a person is asked to reach out.
    IMMEDIATE = "immediate"

    @property
    def rank(self) -> int:
        return _RANK[self]

    def at_least(self, other: "RiskLevel") -> bool:
        return self.rank >= other.rank


_RANK = {RiskLevel.LOW: 0, RiskLevel.MODERATE: 1, RiskLevel.HIGH: 2, RiskLevel.IMMEDIATE: 3}


class Concern(enum.StrEnum):
    """What raised the level. The first five match ``AlertCategory`` so an alert can carry
    them; the rest are never escalated on their own."""

    SUICIDAL_LANGUAGE = "suicidal_language"
    SELF_HARM_LANGUAGE = "self_harm_language"
    HARM_TO_OTHERS = "harm_to_others"
    UNSAFE_SITUATION = "unsafe_situation"
    ACUTE_DISTRESS = "acute_distress"
    DISTRESS_LANGUAGE = "distress_language"
    CONCERN_FOR_OTHER = "concern_for_other"
    LOW_MOOD_TODAY = "low_mood_today"
    HIGH_STRESS_TODAY = "high_stress_today"
    SUSTAINED_LOW_MOOD = "sustained_low_mood"


class Detector(enum.StrEnum):
    RULES = "rules"  # the crisis phrase rules (crisis_rules.py)
    CLASSIFIER = "classifier"  # the AI service reported a crisis from its own classifier
    BEHAVIOUR = "behaviour"  # check-in numbers: mood, stress and recent days


class Source(enum.StrEnum):
    """Where the words or numbers came from."""

    CHECK_IN = "check_in"
    COMPANION = "companion"
    MESSAGE = "message"
