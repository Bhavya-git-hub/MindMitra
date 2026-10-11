"""When to *show support information* after a check-in or a message.

A thin view of ``SafetyClassifier``: support is shown at MODERATE and above (any crisis rule,
including the gentle tier, the lowest mood or the highest stress). Deciding whether a person is
alerted belongs to the safety policy (ADR 0013), not to this function, and a missed phrase is
never a reason to think someone is fine.
"""

from app.domain.safety.classifier import CLASSIFIER, BehaviourSnapshot
from app.domain.safety.risk import RiskLevel


def show_support_prompt(*, mood_score: int, stress_level: int | None, note: str | None) -> bool:
    found = CLASSIFIER.assess(
        text=note, behaviour=BehaviourSnapshot(mood_today=mood_score, stress_today=stress_level)
    )
    return found.level.at_least(RiskLevel.MODERATE)
