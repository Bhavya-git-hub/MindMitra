"""Choosing what to suggest, in what order, and what to say about it.

For every idea in the catalog the score is

    need in its area  x  how first-line the idea is  x  how well the best resource fits the
    student's preferences  x  what their feedback says about it  x  freshness

and the highest scores win, within limits so the list stays short and varied: at most six
suggestions open at once, three ideas per area, and one counselling suggestion at a time. An idea is
skipped while an earlier suggestion of it is still open, was recently finished or set aside, or
was marked not helpful.

Counselling is the next step up, not the first one: it only appears when the need in its area
is high and backed by more than one signal (or a lower wellbeing check, or one overwhelming
signal), and it comes first only when the need is very high.
"""

import dataclasses
import datetime as dt
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

from app.domain.wellness.recommender.catalog import (
    BY_KEY,
    CATALOG,
    COUNSELLING,
    GOAL_FOR_AREA,
    Area,
    Intervention,
)
from app.domain.wellness.recommender.learning import Affinity, Response
from app.domain.wellness.recommender.needs import Driver, Need, assess
from app.domain.wellness.recommender.signals import Signals, ramp

MAX_OPEN: Final = 6
MAX_PER_AREA: Final = 3
SCORE_MIN: Final = 0.4
VERY_HIGH: Final = 0.85
COUNSELLING_FROM: Final = 0.6  # the area's need must be at least this for counselling to appear
GOAL_FIT: Final = 1.15
NUDGE_AFTER_DAYS: Final = 3
GOAL_NUDGE_SCORE: Final = 0.45

OPEN_STATUSES: Final = ("pending", "viewed")
# Days to leave an idea alone after the student's response.
COOLDOWN_DAYS: Final = {"completed": 21, "dismissed": 14}
NOT_HELPFUL_DAYS: Final = {"already_doing_this": 45, "not_now": 7}
NOT_HELPFUL_DEFAULT_DAYS: Final = 30
COUNSELLING_NOT_HELPFUL_DAYS: Final = 45
RESOURCE_REPEAT_DAYS: Final = 30


@dataclasses.dataclass(frozen=True)
class ResourceOption:
    id: uuid.UUID
    title: str
    resource_type: str  # article | video | exercise | audio | service
    tags: tuple[str, ...]
    minutes: int | None
    language: str | None


@dataclasses.dataclass(frozen=True)
class Preferences:
    formats: frozenset[str] = frozenset()  # preferred resource types; empty means no preference
    max_minutes: int | None = None
    muted: frozenset[str] = frozenset()  # areas, or "counselling", the student switched off
    locale: str | None = None


@dataclasses.dataclass(frozen=True)
class Past:
    """A suggestion made earlier, as far as ranking needs to know."""

    intervention_key: str | None
    resource_id: uuid.UUID | None
    created_at: dt.datetime
    status: str  # pending | viewed | completed | dismissed
    expires_at: dt.datetime | None
    responded_at: dt.datetime | None  # when it was finished or dismissed
    rating: str | None = None  # helpful | not_helpful
    reason: str | None = None
    rated_at: dt.datetime | None = None


@dataclasses.dataclass(frozen=True)
class Pick:
    intervention: Intervention
    resource: ResourceOption | None
    score: float
    need: float
    drivers: tuple[Driver, ...]
    rationale: str
    idea_affinity: float
    goal_fit: bool
    goal_category: str | None = None  # for "set a goal": the category their needs point to


def _corroborated(need: Need) -> bool:
    """Counselling needs more than one thing pointing the same way, a recent wellbeing check
    that came out lower, or a single signal that is very strong across all the data there is."""
    return (
        len(need.drivers) >= 2
        or any(d.signal == "wellbeing_check" for d in need.drivers)
        or need.score >= VERY_HIGH
    )


def _is_open(p: Past, now: dt.datetime) -> bool:
    return p.status in OPEN_STATUSES and (p.expires_at is None or p.expires_at > now)


def _days_since(at: dt.datetime | None, now: dt.datetime) -> float:
    return float("inf") if at is None else (now - at).total_seconds() / 86400


def _blocked(iv: Intervention, past: Sequence[Past], now: dt.datetime) -> bool:
    for p in past:
        other = BY_KEY.get(p.intervention_key or "")
        if other is None:
            continue
        same = other.key == iv.key or (iv.family is not None and other.family == iv.family)
        if not same:
            continue
        if _is_open(p, now):
            return True
        # A "not helpful" rating sets its own wait, which replaces the one for dismissing.
        wait = None if p.rating == "not_helpful" else COOLDOWN_DAYS.get(p.status)
        if wait is not None and _days_since(p.responded_at, now) < wait:
            return True
        if p.rating == "not_helpful":
            days = NOT_HELPFUL_DAYS.get(p.reason or "", NOT_HELPFUL_DEFAULT_DAYS)
            if other.family == COUNSELLING and p.reason != "not_now":
                days = max(days, COUNSELLING_NOT_HELPFUL_DAYS)
            if _days_since(p.rated_at, now) < days:
                return True
    return False


def _fit(opt: ResourceOption, prefs: Preferences, iv: Intervention) -> float:
    f = 1.0
    if prefs.formats and opt.resource_type not in prefs.formats and iv.family != COUNSELLING:
        f *= 0.7
    if prefs.max_minutes and opt.minutes:
        if opt.minutes > 2 * prefs.max_minutes:
            f *= 0.3
        elif opt.minutes > prefs.max_minutes:
            f *= 0.6
    if prefs.locale and opt.language:
        if opt.language.split("-")[0].lower() != prefs.locale.split("-")[0].lower():
            f *= 0.7
    return f


def _best_resource(
    iv: Intervention,
    options: Sequence[ResourceOption],
    prefs: Preferences,
    affinity: Affinity,
    past: Sequence[Past],
    now: dt.datetime,
) -> tuple[ResourceOption | None, float]:
    """The resource that best fits this idea, and how well it fits (1.0 is an ordinary fit).

    Matching more of the idea's tags makes a resource more likely to be chosen, but not
    more important: how well it suits the student is what scales the idea's score."""
    recent = {
        p.resource_id
        for p in past
        if p.resource_id is not None
        and p.rating != "helpful"
        and _days_since(p.created_at, now) < RESOURCE_REPEAT_DAYS
    }
    wanted = set(iv.tags)
    best: tuple[float, float, str, ResourceOption] | None = None
    for opt in options:
        overlap = len(wanted & set(opt.tags))
        if overlap == 0:
            continue
        quality = _fit(opt, prefs, iv) * affinity.of_resource(opt.id, opt.resource_type, opt.tags)
        if opt.id in recent:
            quality *= 0.5
        chosen_on = (1.0 + 0.25 * (overlap - 1)) * quality
        if best is None or (-chosen_on, opt.title) < (-best[0], best[2]):
            best = (chosen_on, quality, opt.title, opt)
    return (None, 1.0) if best is None else (best[3], best[1])


def _engagement_score(iv: Intervention, s: Signals) -> float:
    if iv.key == "check_in_nudge":
        if s.days_since_checkin is None:
            return 0.6
        if s.days_since_checkin >= NUDGE_AFTER_DAYS:
            return 0.4 + 0.2 * (ramp(float(s.days_since_checkin), NUDGE_AFTER_DAYS, 10.0) or 0.0)
        return 0.0
    if iv.key == "set_a_goal":
        has_history = s.days_since_checkin is not None
        return GOAL_NUDGE_SCORE if has_history and not s.active_goal_categories else 0.0
    return 0.0


def _lead(iv: Intervention, need: Need, s: Signals) -> str:
    if iv.key == "check_in_nudge":
        if s.days_since_checkin is None:
            return "You haven't checked in yet."
        return f"You haven't checked in for {s.days_since_checkin} days."
    phrases = [d.phrase for d in need.drivers[:2]]
    if not phrases:
        return ""
    return "Lately, " + " and ".join(phrases) + "."


def _rationale(iv: Intervention, need: Need, s: Signals, goal_fit: bool) -> str:
    parts = [_lead(iv, need, s), iv.why]
    if goal_fit:
        parts.append("It fits the goal you've set.")
    return " ".join(p for p in parts if p)


def rank(
    signals: Signals,
    prefs: Preferences,
    past: Sequence[Past],
    responses: Sequence[Response],
    options: Sequence[ResourceOption],
    now: dt.datetime,
) -> list[Pick]:
    """The suggestions to add now, best first. Empty when nothing is worth saying."""
    needs = assess(signals)
    affinity = Affinity(responses, now)
    open_now = [p for p in past if _is_open(p, now) and p.intervention_key in BY_KEY]
    slots = MAX_OPEN - len(open_now)
    if slots <= 0:
        return []
    per_area = Counter(
        BY_KEY[p.intervention_key].area
        for p in open_now
        if p.intervention_key and BY_KEY[p.intervention_key].family is None
    )

    candidates: list[Pick] = []
    for iv in CATALOG:
        if iv.area in prefs.muted or (iv.family == COUNSELLING and COUNSELLING in prefs.muted):
            continue
        if _blocked(iv, past, now):
            continue
        need = needs.get(iv.area, Need(iv.area, 0.0, ()))
        if iv.area == "engagement":
            base = _engagement_score(iv, signals)
        elif iv.family == COUNSELLING:
            base = 0.0
            if need.score >= COUNSELLING_FROM and _corroborated(need):
                base = need.score * (0.55 + 0.45 * (ramp(need.score, COUNSELLING_FROM, 0.9) or 0.0))
        else:
            base = need.score * iv.weight
        if base <= 0:
            continue
        resource, resource_score = _best_resource(iv, options, prefs, affinity, past, now)
        if iv.needs_resource and resource is None:
            continue
        goal_fit = bool(set(iv.goal_categories) & signals.active_goal_categories)
        idea = affinity.idea(iv.key)
        score = base * idea * resource_score * (GOAL_FIT if goal_fit else 1.0)
        if score < SCORE_MIN:
            continue
        candidates.append(
            Pick(
                iv,
                resource,
                round(min(score, 1.0), 3),
                need.score,
                need.drivers,
                _rationale(iv, need, signals, goal_fit),
                round(idea, 3),
                goal_fit,
                suggested_goal_category(needs) if iv.action == "set_goal" else None,
            )
        )

    chosen: list[Pick] = []
    families: set[str] = set()
    for pick in sorted(candidates, key=lambda c: (-c.score, c.intervention.key)):
        iv = pick.intervention
        if len(chosen) >= slots:
            break
        if iv.family is not None:
            if iv.family in families:
                continue  # one counselling suggestion at a time, whichever area it is for
            families.add(iv.family)
        elif per_area[iv.area] >= MAX_PER_AREA:
            continue
        else:
            per_area[iv.area] += 1
        chosen.append(pick)
    return chosen


def suggested_goal_category(needs: Mapping[Area, Need]) -> str | None:
    """A goal category worth proposing to someone with no goal: their most pressing area's."""
    top = max(
        ((n.score, a) for a, n in needs.items() if a in GOAL_FOR_AREA and n.score > 0),
        default=None,
    )
    return None if top is None else GOAL_FOR_AREA[top[1]]
