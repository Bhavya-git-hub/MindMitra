"""What a student's own feedback says about which suggestions suit them.

Every "Helpful" or "Not helpful" (and, more weakly, finishing or setting aside a suggestion)
nudges how likely similar suggestions are to come up again. The nudge is a simple, inspectable
sum, not a trained model: for each thing a suggestion was (the idea itself, its format, the
exact resource, its topics) we count recent helpful and unhelpful responses, with older ones
counting for less, and turn the counts into a multiplier around 1.0.

* No feedback leaves the multiplier at exactly 1.0.
* Three "not helpful" on one idea take it to about 0.4, so it rarely comes back; three
  "helpful" take it to 1.6.
* The reason a student gives decides what is blamed: "wrong format" counts against the format,
  not the idea; "already doing this" and "not now" count against nothing.

It learns only from this student's own responses. Nothing is pooled across students.
"""

import dataclasses
import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Final, Literal

HALF_LIFE_DAYS: Final = 60.0
IMPLICIT_WEIGHT: Final = 0.25  # finishing or dismissing without a rating counts for this much
MULTIPLIER_MIN, MULTIPLIER_MAX = 0.15, 1.8

Kind = Literal["helpful", "not_helpful", "completed", "dismissed"]
Dimension = Literal["idea", "format", "resource", "tag"]


@dataclasses.dataclass(frozen=True)
class Response:
    """One thing a student did with a past suggestion, and what that suggestion was."""

    kind: Kind
    at: dt.datetime
    intervention_key: str | None
    resource_format: str | None
    resource_id: uuid.UUID | None
    tags: tuple[str, ...]
    # not_relevant | wrong_format | too_long | already_doing_this | not_now
    reason: str | None = None


def _decay(age_days: float) -> float:
    return float(0.5 ** (max(age_days, 0.0) / HALF_LIFE_DAYS))


def _multiplier(helpful: float, unhelpful: float) -> float:
    posterior = (helpful + 1.0) / (helpful + unhelpful + 2.0)
    return float(min(MULTIPLIER_MAX, max(MULTIPLIER_MIN, 2.0 * posterior)))


class Affinity:
    """Multipliers (1.0 means no opinion) for the parts of a candidate suggestion."""

    def __init__(self, responses: Iterable[Response], now: dt.datetime) -> None:
        self._counts: dict[Dimension, dict[str, list[float]]] = {
            d: defaultdict(lambda: [0.0, 0.0]) for d in ("idea", "format", "resource", "tag")
        }
        for r in responses:
            self._add(r, _decay((now - r.at).total_seconds() / 86400))

    def _bump(self, dim: Dimension, key: str | None, positive: bool, weight: float) -> None:
        if key is None:
            return
        self._counts[dim][key][0 if positive else 1] += weight

    def _add(self, r: Response, decay: float) -> None:
        if r.kind in ("helpful", "completed"):
            weight = decay * (1.0 if r.kind == "helpful" else IMPLICIT_WEIGHT)
            self._bump("idea", r.intervention_key, True, weight)
            self._bump("format", r.resource_format, True, weight)
            self._bump(
                "resource", None if r.resource_id is None else str(r.resource_id), True, weight
            )
            for tag in r.tags:
                self._bump("tag", tag, True, weight)
            return
        weight = decay * (1.0 if r.kind == "not_helpful" else IMPLICIT_WEIGHT)
        reason = r.reason if r.kind == "not_helpful" else None
        if reason in ("already_doing_this", "not_now"):
            return  # says nothing about whether the idea or format suits them
        resource = None if r.resource_id is None else str(r.resource_id)
        if reason == "wrong_format":
            self._bump("format", r.resource_format, False, weight)
            return
        if reason == "too_long":
            self._bump("resource", resource, False, weight)
            return
        self._bump("idea", r.intervention_key, False, weight)
        self._bump("resource", resource, False, weight)
        self._bump("format", r.resource_format, False, weight * 0.5)
        for tag in r.tags:
            self._bump("tag", tag, False, weight * 0.5)

    def _m(self, dim: Dimension, key: str | None) -> float:
        if key is None or key not in self._counts[dim]:
            return 1.0
        helpful, unhelpful = self._counts[dim][key]
        return _multiplier(helpful, unhelpful)

    def idea(self, key: str) -> float:
        return self._m("idea", key)

    def of_resource(
        self, resource_id: uuid.UUID, resource_format: str | None, tags: Sequence[str]
    ) -> float:
        tag_values = [self._m("tag", t) for t in tags if t in self._counts["tag"]]
        tag_m = sum(tag_values) / len(tag_values) if tag_values else 1.0
        combined = (
            self._m("resource", str(resource_id)) ** 0.5
            * self._m("format", resource_format) ** 0.6
            * tag_m**0.4
        )
        return float(min(2.0, max(0.1, combined)))
