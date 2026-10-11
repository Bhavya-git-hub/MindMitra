"""SafetyPolicy: what happens at each risk level, and when a person is asked to reach out.

| Level     | Student sees                       | Suggestions | A person is asked          |
|-----------|------------------------------------|-------------|----------------------------|
| LOW       | nothing extra (Get help is always on) | as usual | no                         |
| MODERATE  | kind words, contacts, counsellor   | as usual    | no (one tap to ask)        |
| HIGH      | guidance, contacts, counsellor     | paused      | where the basis allows     |
| IMMEDIATE | emergency number first, guidance   | paused      | yes                        |

The basis for asking a person, at HIGH and IMMEDIATE:

- **Companion**: always. Students are told, before they start and in the consent text, that a
  crisis in the companion asks the counselling team to reach out (ADR 0010).
- **Message to their own therapist**: always. The student wrote to their care team, and the
  alert only makes sure someone sees it in time.
- **Check-in note**: with the "Check my journal and notes for safety concerns" consent. Without
  it, only IMMEDIATE (a vital-interest exception the consent text states); at HIGH the student
  gets everything else and a one-tap way to ask for outreach themselves.

The person told never sees what was written: an alert carries the category and urgency only.
"""

import dataclasses
import enum
from typing import Final

from app.domain.safety.classifier import SafetyAssessment
from app.domain.safety.risk import RiskLevel, Source


class EscalationBasis(enum.StrEnum):
    CONSENT = "consent"  # the student allows a safety check of their notes
    VITAL_INTEREST = "vital_interest"  # immediate danger: asked whatever the consent
    CARE_TEAM_MESSAGE = "care_team_message"  # written to their own therapist
    COMPANION_NOTICE = "companion_notice"  # the companion always asks (students are told)
    NO_CONSENT = "no_consent"  # not asked: no consent, and not immediate
    NOT_NEEDED = "not_needed"  # below the level that asks a person

    @property
    def escalates(self) -> bool:
        return self in _ESCALATING


_ESCALATING: Final = frozenset(
    {
        EscalationBasis.CONSENT,
        EscalationBasis.VITAL_INTEREST,
        EscalationBasis.CARE_TEAM_MESSAGE,
        EscalationBasis.COMPANION_NOTICE,
    }
)


@dataclasses.dataclass(frozen=True)
class SafetyDecision:
    level: RiskLevel
    show_resources: bool
    pause_recommendations: bool
    escalate: bool
    basis: EscalationBasis
    emergency_first: bool  # lead with the emergency number
    offer_outreach: bool  # offer "ask someone to reach out" (nobody was asked automatically)


@dataclasses.dataclass(frozen=True)
class SafetyPolicy:
    escalate_at: RiskLevel = RiskLevel.HIGH
    pause_at: RiskLevel = RiskLevel.HIGH
    resources_at: RiskLevel = RiskLevel.MODERATE
    # How long normal suggestions stay paused after a HIGH or IMMEDIATE concern. A person
    # resolving or dismissing the alert ends the pause sooner.
    hold_hours: int = 72
    # A still-open alert from the same place within this window is raised again, not repeated.
    alert_reuse_hours: int = 24

    def needs_consent(self, assessment: SafetyAssessment, source: Source) -> bool:
        """Whether ``decide`` will look at the student's consent (so it is only read then)."""
        return source is Source.CHECK_IN and assessment.level.at_least(self.escalate_at)

    def decide(
        self, assessment: SafetyAssessment, *, source: Source, scanning_consent: bool = False
    ) -> SafetyDecision:
        level = assessment.level
        basis = self._basis(level, source, scanning_consent)
        escalate = basis.escalates
        return SafetyDecision(
            level=level,
            show_resources=level.at_least(self.resources_at),
            pause_recommendations=level.at_least(self.pause_at),
            escalate=escalate,
            basis=basis,
            emergency_first=level is RiskLevel.IMMEDIATE,
            offer_outreach=level.at_least(self.resources_at) and not escalate,
        )

    def _basis(self, level: RiskLevel, source: Source, consent: bool) -> EscalationBasis:
        if not level.at_least(self.escalate_at):
            return EscalationBasis.NOT_NEEDED
        if source is Source.COMPANION:
            return EscalationBasis.COMPANION_NOTICE
        if source is Source.MESSAGE:
            return EscalationBasis.CARE_TEAM_MESSAGE
        if consent:
            return EscalationBasis.CONSENT
        if level is RiskLevel.IMMEDIATE:
            return EscalationBasis.VITAL_INTEREST
        return EscalationBasis.NO_CONSENT


DEFAULT_POLICY: Final = SafetyPolicy()
