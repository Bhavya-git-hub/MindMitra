"""SafetyClassifier: turns words and check-in numbers into a risk level (ADR 0013).

Two inputs, both deterministic and explainable:

- **Language.** The crisis phrase rules (``crisis_rules.detect``) decide HIGH or IMMEDIATE; their
  gentle tier and a short list of support phrases decide MODERATE. Imminence words (a plan,
  means, a time, a note), an explicit emergency ("please call an ambulance") and a weapon on
  campus make it IMMEDIATE.
- **Behaviour.** The lowest mood or stress today, or four of the last seven days at a mood of 2
  or lower, is MODERATE. Numbers alone never go higher: a pattern is a reason to offer help,
  not a reason to alert someone about a student.

Recall comes first, so the rules flag some messages that are not crises (a person reviews every
alert and can dismiss it), and they cannot understand meaning, so they also miss some. A LOW
result is never a statement that someone is fine.

The assessment keeps which rules matched (``signals``) for tests and in-memory decisions only;
nothing outside this process stores them, and nothing here keeps the text.
"""

import dataclasses
import logging
from typing import Final

from app.domain.safety import crisis_rules
from app.domain.safety.risk import Concern, Detector, RiskLevel

log = logging.getLogger("mindmitra.safety")

# Rules whose match means immediate danger even without an imminence word.
IMMEDIATE_RULES: Final = frozenset({"AD-HELP-NOW", "HO-WEAPON"})

LOW_MOOD: Final = 1  # the lowest point on the 1-5 mood scale
HIGH_STRESS: Final = 5  # the highest point on the 1-5 stress scale
SUSTAINED_WINDOW_DAYS: Final = 7
SUSTAINED_LOW_MOOD_MAX: Final = 2  # a "low" day: the day's lowest mood is 2 or less
SUSTAINED_LOW_DAYS: Final = 4  # low days within the window that count as a pattern

_CONCERN = {
    "suicidal_ideation": Concern.SUICIDAL_LANGUAGE,
    "self_harm": Concern.SELF_HARM_LANGUAGE,
    "harm_to_others": Concern.HARM_TO_OTHERS,
    "abuse_or_unsafe_situation": Concern.UNSAFE_SITUATION,
    "acute_distress": Concern.ACUTE_DISTRESS,
    "distress_signal": Concern.DISTRESS_LANGUAGE,
    "concern_for_other": Concern.CONCERN_FOR_OTHER,
}

# Phrases that earn kind words and contacts even when no crisis rule matches ("I don't want
# to be here" may mean a lecture, so it is MODERATE, not HIGH). Matched on normalised text.
_SUPPORT_PHRASES: Final = tuple(
    crisis_rules.normalise(p)
    for p in (
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
)


@dataclasses.dataclass(frozen=True)
class BehaviourSnapshot:
    """Today's check-in numbers and the shape of the last seven days (today included)."""

    mood_today: int | None = None  # 1-5
    stress_today: int | None = None  # 1-5
    low_mood_days: int = 0  # days in the window whose lowest mood was 2 or less


@dataclasses.dataclass(frozen=True)
class SafetyAssessment:
    level: RiskLevel
    concern: Concern | None = None
    detector: Detector | None = None
    about_someone_else: bool = False
    # "moderate" | "high" | "imminent": how urgently an alert, if raised, is due.
    alert_severity: str | None = None
    signals: tuple[str, ...] = ()  # rule ids and behaviour codes; never stored
    rules_version: str | None = None


NOTHING_FOUND: Final = SafetyAssessment(RiskLevel.LOW)

# If the rules themselves fail, show support rather than nothing (fail safe), but do not
# alert anyone on a guess.
_FAILED: Final = SafetyAssessment(
    RiskLevel.MODERATE, Concern.DISTRESS_LANGUAGE, Detector.RULES, signals=("classifier_error",)
)


class SafetyClassifier:
    def assess_text(self, text: str | None) -> SafetyAssessment:
        if not text or not text.strip():
            return NOTHING_FOUND
        try:
            return self._assess_text(text)
        except Exception:  # never let a bad input hide the support a student may need
            log.exception("crisis rules failed; showing support resources instead")
            return _FAILED

    def assess_behaviour(self, snapshot: BehaviourSnapshot | None) -> SafetyAssessment:
        if snapshot is None:
            return NOTHING_FOUND
        found: list[tuple[Concern, str]] = []
        if snapshot.mood_today is not None and snapshot.mood_today <= LOW_MOOD:
            found.append((Concern.LOW_MOOD_TODAY, "BH-LOWEST-MOOD"))
        if snapshot.low_mood_days >= SUSTAINED_LOW_DAYS:
            found.append((Concern.SUSTAINED_LOW_MOOD, "BH-SUSTAINED-LOW"))
        if snapshot.stress_today is not None and snapshot.stress_today >= HIGH_STRESS:
            found.append((Concern.HIGH_STRESS_TODAY, "BH-HIGHEST-STRESS"))
        if not found:
            return NOTHING_FOUND
        return SafetyAssessment(
            RiskLevel.MODERATE,
            found[0][0],
            Detector.BEHAVIOUR,
            signals=tuple(code for _, code in found),
        )

    def assess(
        self, *, text: str | None = None, behaviour: BehaviourSnapshot | None = None
    ) -> SafetyAssessment:
        """The more urgent of the two. On a tie the words name the concern, since they say
        more than numbers do."""
        words = self.assess_text(text)
        numbers = self.assess_behaviour(behaviour)
        if numbers.level.rank > words.level.rank:
            first, second = numbers, words
        else:
            first, second = words, numbers
        if second.level is RiskLevel.LOW:
            return first
        return dataclasses.replace(first, signals=first.signals + second.signals)

    def from_ai_service(
        self, *, action: str, category: str | None, severity: str | None, classifier: bool
    ) -> SafetyAssessment:
        """A crisis the AI service reported (its own rules or a classifier)."""
        detector = Detector.CLASSIFIER if classifier else Detector.RULES
        if action == "escalate":
            immediate = severity == "imminent"
            return SafetyAssessment(
                RiskLevel.IMMEDIATE if immediate else RiskLevel.HIGH,
                _CONCERN.get(category or "", Concern.ACUTE_DISTRESS),
                detector,
                alert_severity="imminent" if immediate else (severity or "high"),
                signals=("ai_service",),
            )
        if action == "review":
            return SafetyAssessment(
                RiskLevel.MODERATE,
                _CONCERN.get(category or "", Concern.DISTRESS_LANGUAGE),
                detector,
                about_someone_else=category == "concern_for_other",
                signals=("ai_service",),
            )
        return NOTHING_FOUND

    # ---- language -------------------------------------------------------------------------

    def _assess_text(self, text: str) -> SafetyAssessment:
        result = crisis_rules.detect(text)
        version = crisis_rules.rules_version()
        if result.crisis:
            immediate = result.severity is crisis_rules.Severity.IMMINENT or bool(
                IMMEDIATE_RULES.intersection(result.rules)
            )
            severity = result.severity.value if result.severity else "high"
            return SafetyAssessment(
                RiskLevel.IMMEDIATE if immediate else RiskLevel.HIGH,
                _CONCERN.get(result.category or "", Concern.ACUTE_DISTRESS),
                Detector.RULES,
                alert_severity="imminent" if immediate else severity,
                signals=result.rules,
                rules_version=version,
            )
        if result.show_resources:
            return SafetyAssessment(
                RiskLevel.MODERATE,
                _CONCERN.get(result.category or "", Concern.DISTRESS_LANGUAGE),
                Detector.RULES,
                about_someone_else=result.third_person,
                signals=result.rules,
                rules_version=version,
            )
        plain = crisis_rules.normalise(text)
        if any(p in plain for p in _SUPPORT_PHRASES):
            return SafetyAssessment(
                RiskLevel.MODERATE,
                Concern.DISTRESS_LANGUAGE,
                Detector.RULES,
                signals=("SUPPORT-PHRASE",),
                rules_version=version,
            )
        return NOTHING_FOUND


CLASSIFIER: Final = SafetyClassifier()
