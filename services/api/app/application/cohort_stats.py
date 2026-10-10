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
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from sqlalchemy import Date, Select, and_, cast, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.timeutil import now_utc
from app.domain.wellness import cohort, instruments
from app.domain.wellness.cohort import Action, Analytics, Share, StudentWeek, WeekCell
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
        key = (sid, cohort.monday_of(at.astimezone(dt.UTC).date()))
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
    until = _utc_start(starts[-1] + dt.timedelta(weeks=1))
    rows = await db.execute(
        select(m.WellnessAssessment.student_id, m.WellnessAssessment.score)
        .ext(distinct_on(m.WellnessAssessment.student_id))
        .where(
            m.WellnessAssessment.student_id.in_(people.scalar_subquery()),
            m.WellnessAssessment.instrument == instruments.INSTRUMENT_ID,
            m.WellnessAssessment.completed_at >= since,
            m.WellnessAssessment.completed_at < until,
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


# ---- frozen windows --------------------------------------------------------------------------

SNAPSHOT_CONSTRAINT = "uq_group_snapshots_window"


def last_closed_week() -> dt.date:
    """The Monday of the most recent completed week. Every window ends here, never later."""
    return cohort.week_starts(now_utc().date(), 1)[0]


async def _stored(
    db: AsyncSession, institution_id: uuid.UUID, view: str, kind: str, group: uuid.UUID, weeks: int
) -> dict[str, Any] | None:
    return await db.scalar(
        select(m.GroupSnapshot.payload).where(
            m.GroupSnapshot.institution_id == institution_id,
            m.GroupSnapshot.view == view,
            m.GroupSnapshot.group_kind == kind,
            m.GroupSnapshot.group_id == group,
            m.GroupSnapshot.last_week == last_closed_week(),
            m.GroupSnapshot.weeks == weeks,
        )
    )


async def frozen[T](
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    view: str,
    kind: str,
    group: uuid.UUID,
    weeks: int,
    compute: Callable[[], Awaitable[T]],
    encode: Callable[[T], dict[str, Any]],
    decode: Callable[[dict[str, Any]], T],
) -> T:
    """Return the stored result for this closed window, computing and storing it on first read.

    The first read after a window closes decides what that window shows from then on. Concurrent
    first reads race on the unique key, and the row that was stored first wins.
    """
    stored = await _stored(db, institution_id, view, kind, group, weeks)
    if stored is None:
        value = await compute()
        await db.execute(
            pg_insert(m.GroupSnapshot)
            .values(
                institution_id=institution_id,
                view=view,
                group_kind=kind,
                group_id=group,
                last_week=last_closed_week(),
                weeks=weeks,
                payload=encode(value),
            )
            .on_conflict_do_nothing(constraint=SNAPSHOT_CONSTRAINT)
        )
        stored = await _stored(db, institution_id, view, kind, group, weeks)
        if stored is None:  # invalidated again in the meantime: answer from this computation
            return value
    return decode(stored)


async def invalidate_for_student(
    db: AsyncSession, institution_id: uuid.UUID, student_id: uuid.UUID
) -> None:
    """Forget stored windows that may include this student, after a consent or status change.

    Deletes the institution-wide figures too, because any student could be in them.
    """
    department = select(m.Student.department_id).where(m.Student.user_id == student_id)
    courses = select(m.CourseEnrollment.course_id).where(
        m.CourseEnrollment.student_id == student_id
    )
    await db.execute(
        delete(m.GroupSnapshot).where(
            m.GroupSnapshot.institution_id == institution_id,
            or_(
                m.GroupSnapshot.group_kind == "institution",
                and_(
                    m.GroupSnapshot.group_kind == "department",
                    m.GroupSnapshot.group_id == department.scalar_subquery(),
                ),
                and_(
                    m.GroupSnapshot.group_kind == "class",
                    m.GroupSnapshot.group_id.in_(courses),
                ),
            ),
        )
    )


def _share_out(s: Share) -> dict[str, Any]:
    return {"state": s.state, "percent": s.percent}


def _share_in(d: dict[str, Any]) -> Share:
    return Share(d["state"], d["percent"])


def encode_figures(f: GroupFigures) -> dict[str, Any]:
    a = f.analytics
    return {
        "state": a.state,
        "contributors_band": a.contributors_band,
        "weeks": [
            {
                "week_start": w.week_start.isoformat(),
                "reporting_band": w.reporting_band,
                "mood": w.mood,
                "energy": w.energy,
                "stress": w.stress,
                "sleep_hours": w.sleep_hours,
                "sleep_quality": w.sleep_quality,
                "check_in": _share_out(w.check_in),
                "academic_stress": _share_out(w.academic_stress),
                "strain": _share_out(w.strain),
            }
            for w in a.weeks
        ],
        "stressors": [[name, _share_out(s)] for name, s in a.stressors],
        "actions": [{"key": x.key, "title": x.title, "message": x.message} for x in a.actions],
        "wellbeing": [
            {"key": b.key, "label": b.label, "share": _share_out(b.share)} for b in f.wellbeing
        ],
        "starts": [d.isoformat() for d in f.starts],
    }


def decode_figures(d: dict[str, Any]) -> GroupFigures:
    weeks = [
        WeekCell(
            week_start=dt.date.fromisoformat(w["week_start"]),
            reporting_band=w["reporting_band"],
            mood=w["mood"],
            energy=w["energy"],
            stress=w["stress"],
            sleep_hours=w["sleep_hours"],
            sleep_quality=w["sleep_quality"],
            check_in=_share_in(w["check_in"]),
            academic_stress=_share_in(w["academic_stress"]),
            strain=_share_in(w["strain"]),
        )
        for w in d["weeks"]
    ]
    analytics = Analytics(
        state=d["state"],
        contributors_band=d["contributors_band"],
        weeks=weeks,
        stressors=[(name, _share_in(s)) for name, s in d["stressors"]],
        actions=[Action(x["key"], x["title"], x["message"]) for x in d["actions"]],
    )
    wellbeing = [WellbeingBand(b["key"], b["label"], _share_in(b["share"])) for b in d["wellbeing"]]
    return GroupFigures(
        analytics=analytics,
        wellbeing=wellbeing,
        starts=[dt.date.fromisoformat(s) for s in d["starts"]],
    )


async def frozen_figures(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    kind: str,
    group: uuid.UUID,
    members: Select[Any],
    weeks: int,
) -> GroupFigures:
    """``figures`` for a closed window, stored once it closes (see ``frozen``)."""
    return await frozen(
        db,
        institution_id,
        view="figures",
        kind=kind,
        group=group,
        weeks=weeks,
        compute=lambda: figures(db, institution_id, members, weeks),
        encode=encode_figures,
        decode=decode_figures,
    )
