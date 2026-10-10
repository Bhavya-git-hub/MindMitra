"""Aggregated, de-identified wellness insights for teachers and administrators.

No individual record ever leaves this module: results are counts and averages, and any cohort
smaller than ``MIN_COHORT_SIZE`` is suppressed (SECURITY_ARCHITECTURE.md INV-4). Teachers are
limited to their own department; administrators may query any department of their institution.
"""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import cohort_stats
from app.application.access import NotFound, enforce
from app.application.timeutil import now_utc
from app.domain.auth.permissions import Role
from app.domain.auth.policies import Principal, allow, deny
from app.domain.wellness import cohort
from app.infrastructure.db import models as m

MIN_COHORT_SIZE = cohort.MIN_COHORT
WEEKS = 4


@dataclasses.dataclass(frozen=True)
class MoodSummary:
    department_id: uuid.UUID | None
    window_days: int
    cohort_size: int | None  # None when suppressed (the exact small number is also hidden)
    average_mood: float | None
    suppressed: bool


async def mood_summary(
    db: AsyncSession, actor: Principal, department_id: uuid.UUID | None
) -> MoodSummary:
    if actor.role is Role.TEACHER:
        teacher = await db.get(m.Teacher, actor.user_id)
        if teacher is None:
            raise NotFound
        if department_id is None:
            department_id = teacher.department_id
        decision = (
            allow("own_department")
            if department_id == teacher.department_id
            else deny("other_department")
        )
    elif actor.role is Role.ADMIN:
        decision = allow("institution_admin")
    else:
        decision = deny("role_not_permitted")
    enforce(
        decision,
        action="insights.mood_summary",
        resource_type="department",
        resource_id=department_id,
    )

    if department_id is not None:
        dept = await db.get(m.Department, department_id)
        if dept is None or dept.institution_id != actor.institution_id:
            raise NotFound

    # The last WEEKS completed calendar weeks, stored once they close. The week in progress is
    # never included: a rolling window would let a teacher see one check-in move the average.
    kind, group = (
        ("department", department_id) if department_id else ("institution", actor.institution_id)
    )
    stored = await cohort_stats.frozen(
        db,
        actor.institution_id,
        view="mood_summary",
        kind=kind,
        group=group,
        weeks=WEEKS,
        compute=lambda: _mood_counts(db, actor.institution_id, department_id),
        encode=lambda c: {"students": c.students, "average": c.average},
        decode=lambda d: _Counts(d["students"], d["average"]),
    )
    await db.commit()  # keep the stored window even though this request only reads
    if stored.students < MIN_COHORT_SIZE:
        return MoodSummary(department_id, WEEKS * 7, None, None, True)
    return MoodSummary(department_id, WEEKS * 7, stored.students, stored.average, False)


@dataclasses.dataclass(frozen=True)
class _Counts:
    students: int
    average: float | None  # rounded; None when no entries


async def _mood_counts(
    db: AsyncSession, institution_id: uuid.UUID, department_id: uuid.UUID | None
) -> _Counts:
    starts = cohort.week_starts(now_utc().date(), WEEKS)
    since = dt.datetime.combine(starts[0], dt.time.min, tzinfo=dt.UTC)
    until = dt.datetime.combine(starts[-1] + dt.timedelta(weeks=1), dt.time.min, tzinfo=dt.UTC)
    members = select(m.Student.user_id).where(m.Student.institution_id == institution_id)
    if department_id is not None:
        members = members.where(m.Student.department_id == department_id)
    # Only students who opted in to anonymous aggregates are counted, whoever asks.
    people = cohort_stats.contributors(institution_id, members)
    stmt = select(
        func.count(func.distinct(m.MoodEntry.student_id)), func.avg(m.MoodEntry.mood_score)
    ).where(
        m.MoodEntry.student_id.in_(people.scalar_subquery()),
        m.MoodEntry.logged_at >= since,
        m.MoodEntry.logged_at < until,
    )
    students, avg = (await db.execute(stmt)).one()
    return _Counts(int(students), round(float(avg), 1) if avg is not None else None)
