"""Administrator dashboard, platform analytics and appointment oversight.

Everything here is a count or an average over many people, and none of it names a student:

* wellbeing figures for the whole institution come from ``cohort_stats`` and so follow the same
  rules as a teacher's (opt-in only, a minimum number of contributors, rounded, completed weeks
  only, stored once a window closes);
* weekly activity counts over the same completed weeks show "fewer than 5" instead of a number
  from 1 to 4, so a quiet week cannot point at one person;
* appointment oversight sees how many appointments there were and how the booking system is
  coping, never who attended or why. Reasons, notes and session content are not read at all.
"""

import dataclasses
import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Date, Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import cohort_stats, teacher_portal
from app.application.admin_common import audit, count
from app.application.errors import InvalidInput
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal
from app.domain.wellness import cohort
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AlertStatus,
    AppointmentStatus,
    AuditOutcome,
    ResourceType,
    UserRole,
    UserStatus,
    VerificationStatus,
)

SMALL_COUNT = 5
WINDOWS = (4, 8, 12)
STALE_REQUEST = dt.timedelta(hours=48)
LICENCE_WARNING = dt.timedelta(days=30)


def check_weeks(weeks: int | None) -> int:
    chosen = weeks or 8
    if chosen not in WINDOWS:
        raise InvalidInput("Choose 4, 8 or 12 weeks.")
    return chosen


def small_safe(n: int) -> int | None:
    """The count, or ``None`` ("fewer than 5") when it is 1 to 4. Zero is shown as zero."""
    return None if 0 < n < SMALL_COUNT else n


@dataclasses.dataclass(frozen=True)
class WeekCount:
    week_start: dt.date
    count: int | None


def _week(column: Any) -> Any:
    return cast(func.date_trunc("week", func.timezone("UTC", column)), Date)


def _bounds(weeks: int) -> tuple[list[dt.date], dt.datetime, dt.datetime]:
    starts = cohort.week_starts(now_utc().date(), weeks)
    begin = dt.datetime.combine(starts[0], dt.time.min, tzinfo=dt.UTC)
    end = dt.datetime.combine(starts[-1] + dt.timedelta(weeks=1), dt.time.min, tzinfo=dt.UTC)
    return starts, begin, end


async def _weekly(
    db: AsyncSession, column: Any, filters: list[Any], starts: list[dt.date], begin: dt.datetime,
    end: dt.datetime,
) -> list[WeekCount]:  # fmt: skip
    wk = _week(column)
    rows = await db.execute(
        select(wk, func.count()).where(column >= begin, column < end, *filters).group_by(wk)
    )
    found = {week: n for week, n in rows.all()}
    return [WeekCount(s, small_safe(found.get(s, 0))) for s in starts]


# ---- dashboard -------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AccountCounts:
    role: UserRole
    active: int
    invited: int
    suspended: int


@dataclasses.dataclass(frozen=True)
class Dashboard:
    accounts: list[AccountCounts]
    pending_verifications: int
    licences_expiring: int
    draft_resources: int
    alerts_awaiting: int
    alerts_overdue: int
    denied_last_7_days: int
    generated_at: dt.datetime


async def account_counts(db: AsyncSession, institution_id: uuid.UUID) -> list[AccountCounts]:
    rows = await db.execute(
        select(m.User.role, m.User.status, func.count())
        .where(m.User.institution_id == institution_id, m.User.deleted_at.is_(None))
        .group_by(m.User.role, m.User.status)
    )
    tally: dict[UserRole, dict[UserStatus, int]] = {r: {} for r in UserRole}
    for role, status, n in rows.all():
        tally[role][status] = n
    return [
        AccountCounts(
            role,
            by.get(UserStatus.ACTIVE, 0),
            by.get(UserStatus.INVITED, 0),
            by.get(UserStatus.SUSPENDED, 0),
        )
        for role, by in tally.items()
    ]


async def dashboard(db: AsyncSession, actor: Principal) -> Dashboard:
    inst = actor.institution_id
    now = now_utc()
    pending = await count(
        db,
        select(func.count())
        .select_from(m.Therapist)
        .join(m.User, m.User.id == m.Therapist.user_id)
        .where(
            m.Therapist.institution_id == inst,
            m.Therapist.verification_status == VerificationStatus.PENDING,
            m.User.deleted_at.is_(None),
        ),
    )
    expiring = await count(
        db,
        select(func.count())
        .select_from(m.Therapist)
        .where(
            m.Therapist.institution_id == inst,
            m.Therapist.verification_status == VerificationStatus.VERIFIED,
            m.Therapist.licence_expires_on.is_not(None),
            m.Therapist.licence_expires_on <= (now + LICENCE_WARNING).date(),
        ),
    )
    drafts = await count(
        db,
        select(func.count())
        .select_from(m.Resource)
        .where(m.Resource.institution_id == inst, m.Resource.is_published.is_(False)),
    )
    awaiting = await count(
        db,
        select(func.count())
        .select_from(m.RiskAlert)
        .where(m.RiskAlert.institution_id == inst, m.RiskAlert.status == AlertStatus.OPEN),
    )
    overdue = await count(
        db,
        select(func.count())
        .select_from(m.RiskAlert)
        .where(
            m.RiskAlert.institution_id == inst,
            m.RiskAlert.status == AlertStatus.OPEN,
            m.RiskAlert.sla_ack_due_at < now,
        ),
    )
    denied = await count(
        db,
        select(func.count())
        .select_from(m.AuditLog)
        .where(
            m.AuditLog.institution_id == inst,
            m.AuditLog.outcome == AuditOutcome.DENIED,
            m.AuditLog.occurred_at >= now - dt.timedelta(days=7),
        ),
    )
    await audit(db, actor, "admin_dashboard.read", resource_type="dashboard")
    await db.commit()
    return Dashboard(
        await account_counts(db, inst), pending, expiring, drafts, awaiting, overdue, denied, now
    )


# ---- platform analytics ----------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PlatformAnalytics:
    weeks: int
    accounts: list[AccountCounts]
    wellbeing: teacher_portal.GroupView
    appointments_booked: list[WeekCount]
    alerts_raised: list[WeekCount]
    resources_published: dict[ResourceType, int]
    generated_at: dt.datetime


async def platform_analytics(
    db: AsyncSession, actor: Principal, weeks: int | None
) -> PlatformAnalytics:
    chosen = check_weeks(weeks)
    inst = actor.institution_id
    starts, begin, end = _bounds(chosen)

    institution = await db.get(m.Institution, inst)
    members: Select[Any] = select(m.Student.user_id).where(m.Student.institution_id == inst)
    figures = await cohort_stats.frozen_figures(
        db, inst, kind="institution", group=inst, members=members, weeks=chosen
    )
    view = teacher_portal.GroupView(
        institution.name if institution else "Institution",
        "institution",
        chosen,
        figures,
        now_utc(),
    )
    booked = await _weekly(
        db,
        m.Appointment.created_at,
        [m.Appointment.institution_id == inst],
        starts,
        begin,
        end,
    )
    raised = await _weekly(
        db, m.RiskAlert.created_at, [m.RiskAlert.institution_id == inst], starts, begin, end
    )
    published = {
        rtype: n
        for rtype, n in (
            await db.execute(
                select(m.Resource.resource_type, func.count())
                .where(
                    m.Resource.is_published.is_(True),
                    (m.Resource.institution_id == inst) | m.Resource.institution_id.is_(None),
                )
                .group_by(m.Resource.resource_type)
            )
        ).all()
    }
    await audit(
        db,
        actor,
        "platform_analytics.read",
        resource_type="analytics",
        weeks=chosen,
        result=figures.analytics.state,
    )
    await db.commit()
    return PlatformAnalytics(
        chosen, await account_counts(db, inst), view, booked, raised, published, now_utc()
    )


# ---- appointment oversight -------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class StatusCount:
    status: AppointmentStatus
    count: int | None


@dataclasses.dataclass(frozen=True)
class TherapistLoad:
    therapist_id: uuid.UUID
    full_name: str
    upcoming: int
    completed: int
    no_shows: int
    cancelled: int


@dataclasses.dataclass(frozen=True)
class Oversight:
    weeks: int
    by_status: list[StatusCount]
    weekly_scheduled: list[WeekCount]
    upcoming_week: int | None
    stale_requests: int
    therapists: list[TherapistLoad]
    generated_at: dt.datetime


async def appointment_oversight(db: AsyncSession, actor: Principal, weeks: int | None) -> Oversight:
    chosen = check_weeks(weeks)
    inst = actor.institution_id
    now = now_utc()
    starts, begin, end = _bounds(chosen)
    in_window = [
        m.Appointment.institution_id == inst,
        m.Appointment.starts_at >= begin,
        m.Appointment.starts_at < end,
    ]
    tally = {
        status: n
        for status, n in (
            await db.execute(
                select(m.Appointment.status, func.count())
                .where(*in_window)
                .group_by(m.Appointment.status)
            )
        ).all()
    }
    weekly = await _weekly(
        db, m.Appointment.starts_at, [m.Appointment.institution_id == inst], starts, begin, end
    )
    next_week = await count(
        db,
        select(func.count())
        .select_from(m.Appointment)
        .where(
            m.Appointment.institution_id == inst,
            m.Appointment.status == AppointmentStatus.CONFIRMED,
            m.Appointment.starts_at >= now,
            m.Appointment.starts_at < now + dt.timedelta(days=7),
        ),
    )
    stale = await count(
        db,
        select(func.count())
        .select_from(m.Appointment)
        .where(
            m.Appointment.institution_id == inst,
            m.Appointment.status == AppointmentStatus.REQUESTED,
            m.Appointment.created_at < now - STALE_REQUEST,
            m.Appointment.starts_at >= now,
        ),
    )
    loads: list[TherapistLoad] = []
    for tid, name in (
        await db.execute(
            select(m.Therapist.user_id, m.User.full_name)
            .join(m.User, m.User.id == m.Therapist.user_id)
            .where(m.Therapist.institution_id == inst, m.User.deleted_at.is_(None))
            .order_by(m.User.full_name)
        )
    ).all():
        by = {
            status: n
            for status, n in (
                await db.execute(
                    select(m.Appointment.status, func.count())
                    .where(*in_window, m.Appointment.therapist_id == tid)
                    .group_by(m.Appointment.status)
                )
            ).all()
        }
        upcoming = await count(
            db,
            select(func.count())
            .select_from(m.Appointment)
            .where(
                m.Appointment.institution_id == inst,
                m.Appointment.therapist_id == tid,
                m.Appointment.status.in_(
                    (AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED)
                ),
                m.Appointment.starts_at >= now,
            ),
        )
        loads.append(
            TherapistLoad(
                tid,
                name,
                upcoming,
                by.get(AppointmentStatus.COMPLETED, 0),
                by.get(AppointmentStatus.NO_SHOW, 0),
                by.get(AppointmentStatus.CANCELLED, 0),
            )
        )
    await audit(db, actor, "appointment_oversight.read", resource_type="appointments", weeks=chosen)
    await db.commit()
    return Oversight(
        chosen,
        [StatusCount(s, small_safe(tally.get(s, 0))) for s in AppointmentStatus],
        weekly,
        small_safe(next_week),
        stale,
        loads,
        now,
    )
