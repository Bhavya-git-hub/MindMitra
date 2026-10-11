"""EmergencyResource: a place to get help now, in the order a risk level calls for.

Contacts are data (``safety.crisis_contacts``, per institution or national), so an institution
keeps them current without a code change. This module only orders them and makes sure the list
is never empty: if nothing is configured, or the lookup fails, the student still sees the
built-in "call your local emergency number" entry.
"""

import dataclasses
import uuid
from collections.abc import Iterable
from typing import Final

from app.domain.safety.risk import RiskLevel


@dataclasses.dataclass(frozen=True)
class EmergencyResource:
    label: str
    kind: str  # "emergency" | "helpline" | "campus"
    phone: str | None = None
    url: str | None = None
    description: str | None = None
    hours: str | None = None
    id: uuid.UUID | None = None  # None for the built-in fallback


FALLBACK: Final = EmergencyResource(
    label="Local emergency services",
    kind="emergency",
    description=(
        "Call your local emergency number, or go to the nearest hospital emergency department."
    ),
    hours="24 hours",
)

_URGENT_ORDER: Final = ("emergency", "helpline", "campus")
_GENTLE_ORDER: Final = ("helpline", "campus", "emergency")


def arrange(resources: Iterable[EmergencyResource], level: RiskLevel) -> list[EmergencyResource]:
    """Emergency contacts first at HIGH and above, helplines first below. The institution's
    own order is kept within each kind. At HIGH and above an emergency entry is always there."""
    rows = list(resources)
    order = _URGENT_ORDER if level.at_least(RiskLevel.HIGH) else _GENTLE_ORDER
    rank = {kind: i for i, kind in enumerate(order)}
    rows.sort(key=lambda r: rank.get(r.kind, len(order)))  # stable: keeps admin order
    urgent = level.at_least(RiskLevel.HIGH)
    if not rows or (urgent and not any(r.kind == "emergency" for r in rows)):
        rows.insert(0, FALLBACK)
    return rows
