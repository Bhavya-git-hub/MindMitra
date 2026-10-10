"""Loading weekly figures for a group of students, only from students who opted in.

The only thing that leaves this module is a ``domain.wellness.cohort.Analytics`` (or a
``WellbeingMix``), which has already been through the privacy rules. Student ids are used to
count distinct people and are dropped before anything is returned.

A student counts toward a group's figures only while they have an active
``anonymous_aggregate_research`` consent, their account is active, and they belong to the group.
Withdrawing consent removes their past entries from the next request's figures as well.
"""

import dataclasses
import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Date, Select, cast, exists, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.timeutil import now_utc
from app.domain.wellness import cohort, instruments
from app.domain.wellness.cohort import Analytics, Share, StudentWeek
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import ConsentScope, UserStatus


@dataclasses.dataclass(frozen=True)
class WellbeingBand:
    key: str
    label: str
    share: Share


@dataclasses.dataclass(frozen=True)
class GroupFigures:
    analytics: Analytics
    wellbeing: list[WellbeingBand]
    starts: list[dt.date]


def contributors(actor_institution: uuid.UUID, members: Select[Any]) -> Select[Any]:
    """The members of a group who may be counted: consenting, active, in this institution."""
    consented = exists().where(
        m.Consent.user_id == m.Student.user_id,
        m.Consent.scope == ConsentScope.ANONYMOUS_AGGREGATE_RESEARCH,
        m.Consent.revoked_at.is_(None),
    )
    return (
        select(m.Student.user_id)
        .join(m.User, m.User.id == m.Student.user_id)
        .where(
            m.Student.user_id.in_(members),
            m.Student.institution_id == actor_institution,
            m.User.status == UserStatus.ACTIVE,
            m.User.deleted_at.is_(None),
            consented,
        )
    )


def _week(column: Any) -> Any:
    """The Monday (UTC) of the week a timestamp falls in."""
    return cast(func.date_trunc("week", func.timezone("UTC", column)), Date)


def _utc_start(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC)


async def _rows(
    db: AsyncSession, people: Select[Any], starts: Sequence[dt.date]
) -> list[StudentWeek]:
    first = starts[0] - dt.timedelta(weeks=1)  # one earlier week feeds the two-week strain average
    after = starts[-1] + dt.timedelta(weeks=1)
    lo, hi = _utc_start(first), _utc_start(after)
    ids = people.scalar_subquery()

    mood_week = _week(m.MoodEntry.logged_at)
    moods = await db.execute(
        select(
            m.MoodEntry.student_id,
            mood_week,
            func.avg(m.MoodEntry.mood_score),
            func.avg(m.MoodEntry.energy_level),
        )
        .where(
            m.MoodEntry.student_id.in_(ids),
            m.MoodEntry.logged_at >= lo,
            m.MoodEntry.logged_at < hi,
        )
        .group_by(m.MoodEntry.student_id, mood_week)
    )
    sleep_week = cast(func.date_trunc("week", cast(m.SleepEntry.sleep_date, Date)), Date)
    sleeps = await db.execute(
        select(
            m.SleepEntry.student_id,
            sleep_week,
            func.avg(m.SleepEntry.duration_minutes),
            func.avg(m.SleepEntry.quality),
        )
        .where(
            m.SleepEntry.student_id.in_(ids),
            m.SleepEntry.sleep_date >= first,
            m.SleepEntry.sleep_date < after,
        )
        .group_by(m.SleepEntry.student_id, sleep_week)
    )
    stresses = await db.execute(
        select(
            m.StressAssessment.student_id,
            m.StressAssessment.completed_at,
            m.StressAssessment.perceived_stress_level,
            m.StressAssessment.stressors,
        ).where(
            m.StressAssessment.student_id.in_(ids),
            m.StressAssessment.completed_at >= lo,
            m.StressAssessment.completed_at < hi,
        )
    )

    cells: dict[tuple[uuid.UUID, dt.date], dict[str, Any]] = defaultdict(dict)
    for sid, week, mood, energy in moods:
        cells[(sid, week)].update(
            mood=float(mood),
            energy=float(energy) if energy is not None else None,
            checked_in=True,
        )
    for sid, week, minutes, quality in sleeps:
        cells[(sid, week)].update(sleep_minutes=float(minutes), sleep_quality=float(quality))
    levels: dict[tuple[uuid.UUID, dt.date], list[int]] = defaultdict(list)
    named: dict[tuple[uuid.UUID, dt.date], set[str]] = defaultdict(set)
    for sid, at, level, stressors in stresses:
        key = (
            sid,
            at.astimezone(dt.UTC).date() - dt.timedelta(days=at.astimezone(dt.UTC).weekday()),
        )
        levels[key].append(level)
        named[key].update(s.lower() for s in stressors)
    for key, values in levels.items():
        cells[key].update(
            stress=sum(values) / len(values),
            stressors=frozenset(named[key]),
            academic_stress=bool(named[key] & cohort.ACADEMIC_STRESSORS),
        )
    return [
        StudentWeek(key=sid, week_start=week, **values) for (sid, week), values in cells.items()
    ]


async def _wellbeing(
    db: AsyncSession, people: Select[Any], starts: Sequence[dt.date]
) -> list[WellbeingBand]:
    """Where students' latest wellbeing check in the window falls, as shares of the group."""
    since = _utc_start(starts[0])
    rows = await db.execute(
        select(m.WellnessAssessment.student_id, m.WellnessAssessment.score)
        .ext(distinct_on(m.WellnessAssessment.student_id))
        .where(
            m.WellnessAssessment.student_id.in_(people.scalar_subquery()),
            m.WellnessAssessment.instrument == instruments.INSTRUMENT_ID,
            m.WellnessAssessment.completed_at >= since,
        )
        .order_by(m.WellnessAssessment.student_id, m.WellnessAssessment.completed_at.desc())
    )
    bands = [instruments.band(float(score)) for _, score in rows]
    if len(bands) < cohort.MIN_COHORT:
        return []
    order = ["doing_well", "mixed", "lower"]
    labels = {b.key: b.label for b in bands}
    labels.setdefault("doing_well", "Doing well")
    labels.setdefault("mixed", "Mixed")
    labels.setdefault("lower", "Lower lately")
    return [
        WellbeingBand(
            key, labels[key], cohort.share(sum(1 for b in bands if b.key == key), len(bands))
        )
        for key in order
    ]


async def figures(
    db: AsyncSession, institution_id: uuid.UUID, members: Select[Any], weeks: int
) -> GroupFigures:
    """Everything a teacher may see about one group, already through the privacy rules."""
    starts = cohort.week_starts(now_utc().date(), weeks)
    people = contributors(institution_id, members)
    count = await db.scalar(select(func.count()).select_from(people.subquery())) or 0
    if count < cohort.MIN_COHORT:
        return GroupFigures(cohort.analyse([], count, starts), [], starts)
    analytics = cohort.analyse(await _rows(db, people, starts), count, starts)
    return GroupFigures(analytics, await _wellbeing(db, people, starts), starts)
