"""Immediate-support guidance: fixed wording, written once and reviewed, never generated.

It points to people (emergency services, helplines, the counselling team, someone the student
trusts) and to simple first steps. It never diagnoses, never names a condition or a
medication, and never tries to be emergency treatment. Tests check every text for that.
"""

import dataclasses
from typing import Final

from app.domain.safety.risk import Concern, RiskLevel

DISCLAIMER: Final = (
    "MindMitra is not an emergency service and does not replace emergency services, doctors "
    "or qualified counsellors. It cannot diagnose or treat anyone. If you or someone else is "
    "in immediate danger, call your local emergency number now."
)

EMERGENCY_NOW: Final = (
    "If you or anyone else is in immediate danger, call your local emergency number now."
)

_OPENING: Final = {
    Concern.UNSAFE_SITUATION: (
        "Thank you for telling us. No one has the right to hurt or threaten you, and it is not "
        "your fault. Your safety comes first."
    ),
    Concern.HARM_TO_OTHERS: (
        "It sounds like things feel really intense right now. If you can, step away from the "
        "situation and talk to someone now."
    ),
}
_DEFAULT_OPENING: Final = (
    "Thank you for telling us. What you're going through matters, and you deserve support from "
    "a person right now."
)
_ABOUT_SOMEONE_ELSE: Final = (
    "It sounds like you're worried about someone. You can help them get support, and you "
    "don't have to do it alone."
)


@dataclasses.dataclass(frozen=True)
class Guidance:
    title: str
    message: str
    steps: tuple[str, ...]


_REACH_OUT = "Call or message one of the contacts below. You don't have to explain everything."
_COUNSELLOR = "You can message your counsellor or book one through MindMitra."
_TRUSTED = "Tell someone you trust how you're feeling, and stay with them if you can."

_IMMEDIATE_STEPS: Final = {
    Concern.UNSAFE_SITUATION: (
        EMERGENCY_NOW,
        "If you can, go somewhere safe, near other people you trust.",
        _REACH_OUT,
        _COUNSELLOR,
    ),
    Concern.HARM_TO_OTHERS: (
        EMERGENCY_NOW,
        "If you can, step away from the situation and anything that could be used to hurt someone.",
        _REACH_OUT,
        _COUNSELLOR,
    ),
}
_IMMEDIATE_DEFAULT: Final = (
    EMERGENCY_NOW,
    "If you can, move away from anything you could use to hurt yourself, and go to where "
    "other people are.",
    _REACH_OUT,
    _TRUSTED,
)
_HIGH_STEPS: Final = (
    "Please talk to a person today: one of the contacts below, your counsellor, or someone you "
    "trust.",
    "If things get worse, or you feel you might act on these thoughts, call your local "
    "emergency number.",
    _COUNSELLOR,
)
_MODERATE_STEPS: Final = (
    "Talking to someone can help, even briefly: a friend, family, or one of the contacts below.",
    _COUNSELLOR,
    "If things start to feel unsafe, use Get help now at any time.",
)
_SOMEONE_ELSE_STEPS: Final = (
    "If they might be in danger now, call emergency services or campus security for them.",
    "If it is safe, stay with them or keep in touch until help arrives.",
    "Encourage them to talk to a counsellor. You don't have to handle this alone: the "
    "contacts below can advise you too.",
)


def guidance_for(
    level: RiskLevel, concern: Concern | None, *, about_someone_else: bool = False
) -> Guidance:
    if about_someone_else:
        return Guidance(
            "Support for someone you're worried about", _ABOUT_SOMEONE_ELSE, _SOMEONE_ELSE_STEPS
        )
    opening = _OPENING.get(concern, _DEFAULT_OPENING) if concern else _DEFAULT_OPENING
    if level is RiskLevel.IMMEDIATE:
        steps = _IMMEDIATE_STEPS.get(concern, _IMMEDIATE_DEFAULT) if concern else _IMMEDIATE_DEFAULT
        return Guidance("Please talk to a person now", opening, steps)
    if level is RiskLevel.HIGH:
        return Guidance("Please reach out to a person", opening, _HIGH_STEPS)
    return Guidance(
        "Support is here if you need it",
        "Thank you for telling us. If things feel heavy, you don't have to carry them alone.",
        _MODERATE_STEPS,
    )
