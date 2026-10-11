"""A therapist's own analytics: exact figures, week windows, consent and isolation.

Each test builds a private institution (so alerts that nobody is assigned to, which every
therapist of an institution may see, cannot leak in from other tests) and writes records
straight to the database at known times; the figures are read back through the real API.
"""

import dataclasses
import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import therapist_analytics as ta
from app.domain.wellness import cohort
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    AppointmentStatus,
    CareRole,
    ConsentScope,
    FollowUpKind,
    FollowUpStatus,
    RecommendationSource,
    RecommendationStatus,
    SessionMode,
    UserRole,
)
from app.infrastructure.db.ids import uuid7
from tests.api_helpers import call, token_for
from tests.api_world import Actor, Builder, World
from tests.student_helpers import Session, sign_in
from tests.teacher_helpers import wednesday

pytestmark = pytest.mark.asyncio

PATH = "/therapist/analytics"
SECRET = "SYNTHETIC-SECRET-TEXT"
NOW = dt.datetime.now(dt.UTC)
APPT = AppointmentStatus
ALERT = AlertStatus


@dataclasses.dataclass
class Clinic:
    """A private institution with one signed-in, verified therapist."""

    db: AsyncSession
    builder: Builder
    inst: uuid.UUID
    dept: uuid.UUID
    therapist: Session
    client: httpx.AsyncClient
    password: str


async def clinic(
    client: httpx.AsyncClient, db: AsyncSession, world: World, *, verified: bool = True
) -> Clinic:
    builder = Builder(db, world.password)
    inst, dept = await builder.institution(uuid.uuid4().hex[:8])
    actor = await builder.user(inst, UserRole.THERAPIST, verified=verified)
    await db.commit()
    session = await sign_in(client, actor, world.password)
    return Clinic(db, builder, inst, dept, session, client, world.password)


async def colleague(c: Clinic, *, inst: uuid.UUID | None = None) -> Actor:
    actor = await c.builder.user(inst or c.inst, UserRole.THERAPIST)
    await c.db.commit()
    return actor


async def student(
    c: Clinic,
    *,
    link: bool | Actor = True,
    consent: bool = True,
    ended: bool = False,
    inst: uuid.UUID | None = None,
    dept: uuid.UUID | None = None,
) -> Actor:
    """A student. ``link=True`` puts them on ``c.therapist``'s care team; an ``Actor`` puts
    them on that therapist's instead. ``ended`` makes the link a past one."""
    where = inst or c.inst
    s = await c.builder.user(where, UserRole.STUDENT, department_id=dept or c.dept)
    owner = c.therapist.id if link is True else link.user_id if isinstance(link, Actor) else None
    if owner is not None:
        c.db.add(
            m.CareTeamMember(
                institution_id=where,
                student_id=s.user_id,
                therapist_id=owner,
                role=CareRole.PRIMARY,
                starts_at=NOW - dt.timedelta(days=60),
                ends_at=NOW - dt.timedelta(days=1) if ended else None,
            )
        )
    if consent:
        c.db.add(
            m.Consent(
                institution_id=where,
                user_id=s.user_id,
                scope=ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
                policy_version="test",
                granted_at=NOW - dt.timedelta(days=30),
            )
        )
    await c.db.commit()
    return s


def when(weeks_ago: int, *, hours: int = 0) -> dt.datetime:
    """Noon UTC on the Wednesday ``weeks_ago`` weeks back (1 = the last completed week)."""
    return wednesday(weeks_ago) + dt.timedelta(hours=hours)


def add_mood(c: Clinic, s: Actor, weeks_ago: int, score: int, *, hours: int = 0) -> None:
    c.db.add(
        m.MoodEntry(
            institution_id=_inst(c, s),
            student_id=s.user_id,
            mood_score=score,
            emotions=["calm"],
            note=f"{SECRET}-mood-note",
            logged_at=when(weeks_ago, hours=hours),
        )
    )


def add_stress(c: Clinic, s: Actor, weeks_ago: int, level: int) -> None:
    c.db.add(
        m.StressAssessment(
            institution_id=_inst(c, s),
            student_id=s.user_id,
            scale="daily_stress_check",
            score=Decimal(level),
            max_score=Decimal(5),
            perceived_stress_level=level,
            stressors=[],
            completed_at=when(weeks_ago),
        )
    )


def add_sleep(c: Clinic, s: Actor, weeks_ago: int, hours: float, *, day_offset: int = 0) -> None:
    wake = when(weeks_ago).replace(hour=6) + dt.timedelta(days=day_offset)
    c.db.add(
        m.SleepEntry(
            institution_id=_inst(c, s),
            student_id=s.user_id,
            sleep_date=wake.date(),
            bedtime=wake - dt.timedelta(hours=hours),
            wake_time=wake,
            duration_minutes=round(hours * 60),
            quality=3,
        )
    )


def _inst(c: Clinic, s: Actor) -> uuid.UUID:
    return s.institution_id


def add_appointment(
    c: Clinic,
    s: Actor,
    status: AppointmentStatus,
    starts_at: dt.datetime,
    *,
    mode: SessionMode = SessionMode.VIDEO,
    therapist: uuid.UUID | None = None,
) -> None:
    c.db.add(
        m.Appointment(
            id=uuid7(),
            institution_id=s.institution_id,
            student_id=s.user_id,
            therapist_id=therapist or c.therapist.id,
            starts_at=starts_at,
            ends_at=starts_at + dt.timedelta(minutes=50),
            mode=mode,
            status=status,
            cancelled_at=starts_at if status is APPT.CANCELLED else None,
        )
    )


def add_recommendation(
    c: Clinic,
    s: Actor,
    status: RecommendationStatus,
    created: dt.datetime,
    *,
    author: uuid.UUID | None = None,
    source: RecommendationSource = RecommendationSource.THERAPIST,
) -> None:
    c.db.add(
        m.Recommendation(
            id=uuid7(),
            institution_id=s.institution_id,
            student_id=s.user_id,
            source=source,
            status=status,
            title=f"{SECRET}-title",
            rationale=f"{SECRET}-rationale",
            authored_by=author or c.therapist.id,
            created_at=created,
        )
    )


def add_follow_up(
    c: Clinic,
    s: Actor,
    status: FollowUpStatus,
    created: dt.datetime,
    due_on: dt.date,
    *,
    completed_at: dt.datetime | None = None,
    kind: FollowUpKind = FollowUpKind.CHECK_IN,
    therapist: uuid.UUID | None = None,
) -> None:
    c.db.add(
        m.FollowUp(
            id=uuid7(),
            institution_id=s.institution_id,
            therapist_id=therapist or c.therapist.id,
            student_id=s.user_id,
            kind=kind,
            status=status,
            due_on=due_on,
            note=f"{SECRET}-follow-up-note",
            completed_at=completed_at,
            created_at=created,
        )
    )


def add_alert(
    c: Clinic,
    s: Actor,
    severity: AlertSeverity,
    status: AlertStatus,
    created: dt.datetime,
    *,
    assigned: uuid.UUID | None = None,
    ack_after_min: float | None = None,
    sla_due: dt.datetime | None = None,
) -> None:
    acknowledged = created + dt.timedelta(minutes=ack_after_min) if ack_after_min else None
    if sla_due is None and severity in (AlertSeverity.HIGH, AlertSeverity.IMMINENT):
        sla_due = NOW + dt.timedelta(days=30)  # the database requires a due time for these
    c.db.add(
        m.RiskAlert(
            id=uuid7(),
            institution_id=s.institution_id,
            student_id=s.user_id,
            assigned_to=assigned,
            source=AlertSource.HELP_BUTTON,
            detector=AlertDetector.HUMAN,
            category=AlertCategory.ACUTE_DISTRESS,
            severity=severity,
            status=status,
            requires_human=True,
            excerpt=f"{SECRET}-excerpt",
            sla_ack_due_at=sla_due,
            acknowledged_at=acknowledged,
            resolved_at=created + dt.timedelta(hours=5)
            if status in (ALERT.RESOLVED, ALERT.DISMISSED)
            else None,
            created_at=created,
        )
    )


async def fetch(c: Clinic, weeks: int | None = None, tz: str | None = None) -> dict[str, Any]:
    query = "&".join(
        part for part in (f"weeks={weeks}" if weeks else "", f"tz={tz}" if tz else "") if part
    )
    r = await c.therapist.get(PATH + (f"?{query}" if query else ""))
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def stable(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k != "generated_at"}


def monday(weeks_ago: int) -> str:
    return (when(weeks_ago) - dt.timedelta(days=2)).date().isoformat()


def blank_week_counts(body: list[dict[str, Any]], key: str = "count") -> list[int]:
    return [row[key] for row in body]


async def populated(c: Clinic) -> tuple[Actor, Actor]:
    """Two consenting students with a spread of records of every kind."""
    one = await student(c)
    two = await student(c)
    add_mood(c, one, 1, 2)
    add_mood(c, one, 1, 4, hours=2)
    add_stress(c, one, 1, 2)
    add_sleep(c, one, 1, 6.0)
    for i in range(4):
        add_mood(c, two, 1, 5, hours=i)
    add_stress(c, two, 1, 4)
    add_sleep(c, two, 1, 8.0)
    add_mood(c, one, 2, 3)
    add_appointment(c, one, APPT.COMPLETED, when(1))
    add_appointment(c, two, APPT.NO_SHOW, when(2), mode=SessionMode.PHONE)
    add_recommendation(c, one, RecommendationStatus.COMPLETED, when(1))
    add_recommendation(c, two, RecommendationStatus.PENDING, when(2))
    today = NOW.date()
    add_follow_up(c, one, FollowUpStatus.OPEN, when(1), today - dt.timedelta(days=1))
    add_follow_up(
        c,
        two,
        FollowUpStatus.DONE,
        when(1),
        today - dt.timedelta(days=3),
        completed_at=NOW - dt.timedelta(days=4),
        kind=FollowUpKind.BOOK_SESSION,
    )
    add_alert(
        c, one, AlertSeverity.HIGH, ALERT.ACKNOWLEDGED, when(1), assigned=c.therapist.id,
        ack_after_min=20,
    )  # fmt: skip
    add_alert(c, two, AlertSeverity.LOW, ALERT.OPEN, when(2), sla_due=NOW - dt.timedelta(hours=1))
    await c.db.commit()
    return one, two


# ---- shape and windows ---------------------------------------------------------------------


async def test_the_default_window_is_eight_completed_weeks(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    body = await fetch(c)
    expected = [d.isoformat() for d in cohort.week_starts(NOW.date(), 8)]
    assert body["weeks"] == 8
    for section in (
        body["caseload"]["weekly"],
        body["appointments"]["weekly"],
        body["interventions"]["recommendations"]["weekly"],
        body["alerts"]["weekly"],
    ):
        assert [w["week_start"] for w in section] == expected
    first = dt.date.fromisoformat(expected[0])
    assert first.weekday() == 0
    assert body["window_start"] == expected[0]
    assert dt.date.fromisoformat(body["window_end"]) == dt.date.fromisoformat(expected[-1]) + (
        dt.timedelta(days=6)
    )
    assert dt.date.fromisoformat(body["window_end"]) < NOW.date()  # never the week in progress
    assert body["generated_at"] and "not a diagnosis" in body["disclaimer"]


@pytest.mark.parametrize("weeks", [4, 8, 12])
async def test_each_allowed_window_has_that_many_weeks(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, weeks: int
) -> None:
    c = await clinic(client, api_db, world)
    body = await fetch(c, weeks)
    assert body["weeks"] == weeks
    assert len(body["caseload"]["weekly"]) == len(body["alerts"]["weekly"]) == weeks


@pytest.mark.parametrize("weeks", ["0", "1", "5", "13", "-4", "abc", "8.5"])
async def test_any_other_window_is_refused(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, weeks: str
) -> None:
    c = await clinic(client, api_db, world)
    r = await c.therapist.get(f"{PATH}?weeks={weeks}")
    assert r.status_code == 422, r.text


async def test_the_window_decides_which_records_count(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s = await student(c)
    add_appointment(c, s, APPT.COMPLETED, when(3))
    add_appointment(c, s, APPT.COMPLETED, when(6), mode=SessionMode.PHONE)
    add_appointment(c, s, APPT.COMPLETED, when(10), mode=SessionMode.IN_PERSON)
    add_appointment(c, s, APPT.COMPLETED, when(14), mode=SessionMode.IN_PERSON)
    await c.db.commit()
    done = {w: (await fetch(c, w))["appointments"]["by_status"]["completed"] for w in (4, 8, 12)}
    assert done == {4: 1, 8: 2, 12: 3}


async def test_week_boundaries_are_monday_midnight_utc(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s = await student(c)
    first = dt.datetime.fromisoformat(f"{monday(8)}T00:00:00+00:00")
    this_monday = dt.datetime.fromisoformat(f"{monday(0)}T00:00:00+00:00")
    one_second = dt.timedelta(seconds=1)
    # Statuses differ so no two live appointments overlap; each is a different boundary case.
    add_appointment(c, s, APPT.COMPLETED, first - one_second)  # just before the window
    add_appointment(c, s, APPT.NO_SHOW, first)  # the first instant of week 1
    add_appointment(c, s, APPT.CANCELLED, first + dt.timedelta(days=7) - one_second)  # end of wk 1
    add_appointment(c, s, APPT.COMPLETED, first + dt.timedelta(days=7))  # start of week 2
    add_appointment(c, s, APPT.COMPLETED, this_monday - one_second)  # last second of week 8
    add_appointment(c, s, APPT.COMPLETED, this_monday)  # the week in progress: never counted
    await c.db.commit()
    body = await fetch(c)
    weekly = body["appointments"]["weekly"]
    assert weekly[0]["week_start"] == first.date().isoformat()
    assert [w["scheduled"] for w in weekly] == [2, 1, 0, 0, 0, 0, 0, 1]
    assert (weekly[0]["no_show"], weekly[0]["cancelled"]) == (1, 1)
    assert body["appointments"]["by_status"] == {
        "requested": 0,
        "confirmed": 0,
        "completed": 2,
        "cancelled": 1,
        "no_show": 1,
    }


# ---- caseload ------------------------------------------------------------------------------


async def test_caseload_averages_each_students_week_first(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    light, heavy = await student(c), await student(c)
    add_mood(c, light, 1, 2)
    add_mood(c, light, 1, 4, hours=1)  # this student's week: 3.0
    for i in range(4):
        add_mood(c, heavy, 1, 5, hours=i)  # four entries, one student: 5.0
    add_stress(c, light, 1, 2)
    add_stress(c, heavy, 1, 4)
    add_sleep(c, light, 1, 6.0)
    add_sleep(c, light, 1, 7.0, day_offset=1)  # this student's week: 6.5 h
    add_sleep(c, heavy, 1, 8.0)
    add_mood(c, light, 2, 3)  # the week before: one student, mood only
    await c.db.commit()

    caseload = (await fetch(c))["caseload"]
    assert caseload["caseload_size"] == 2 and caseload["sharing_count"] == 2
    last, before = caseload["weekly"][-1], caseload["weekly"][-2]
    assert last["week_start"] == monday(1)
    # pooled it would be 4.3; the mean of the two students' own means is 4.0
    assert last == {
        "week_start": monday(1),
        "students_reporting": 2,
        "mood_avg": 4.0,
        "stress_avg": 3.0,
        "sleep_hours_avg": 7.25,
    }
    assert before == {
        "week_start": monday(2),
        "students_reporting": 1,
        "mood_avg": 3.0,
        "stress_avg": None,
        "sleep_hours_avg": None,
    }
    quiet = caseload["weekly"][:-2]
    assert all(
        w["students_reporting"] == 0
        and w["mood_avg"] is None
        and w["stress_avg"] is None
        and w["sleep_hours_avg"] is None
        for w in quiet
    )


async def test_a_student_who_only_logged_sleep_counts_as_reporting(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s = await student(c)
    add_sleep(c, s, 1, 7.5)
    await c.db.commit()
    last = (await fetch(c))["caseload"]["weekly"][-1]
    assert (last["students_reporting"], last["mood_avg"], last["sleep_hours_avg"]) == (1, None, 7.5)


async def test_students_without_consent_are_on_the_caseload_but_add_no_figures(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    sharing = await student(c)
    add_mood(c, sharing, 1, 4)
    await c.db.commit()
    before = await fetch(c)

    private = await student(c, consent=False)
    add_mood(c, private, 1, 1)
    add_stress(c, private, 1, 5)
    add_sleep(c, private, 1, 2.0)
    # an old, revoked grant is no consent either
    revoked = await student(c, consent=False)
    api_db.add(
        m.Consent(
            institution_id=c.inst,
            user_id=revoked.user_id,
            scope=ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
            policy_version="test",
            granted_at=NOW - dt.timedelta(days=20),
            revoked_at=NOW - dt.timedelta(days=10),
        )
    )
    add_mood(c, revoked, 1, 1)
    # consent to something else does not open up check-ins
    other_scope = await student(c, consent=False)
    api_db.add(
        m.Consent(
            institution_id=c.inst,
            user_id=other_scope.user_id,
            scope=ConsentScope.SHARE_ASSESSMENTS_WITH_CARE_TEAM,
            policy_version="test",
            granted_at=NOW - dt.timedelta(days=20),
        )
    )
    add_mood(c, other_scope, 1, 1)
    await c.db.commit()

    after = await fetch(c)
    assert after["caseload"]["caseload_size"] == 4 and after["caseload"]["sharing_count"] == 1
    assert after["caseload"]["weekly"] == before["caseload"]["weekly"]
    for section in ("appointments", "interventions", "alerts"):
        assert after[section] == before[section]


async def test_consent_changes_are_followed_the_moment_they_happen(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    a, b = await student(c), await student(c)
    add_mood(c, a, 1, 2)
    add_mood(c, b, 1, 4)
    await c.db.commit()
    assert (await fetch(c))["caseload"]["weekly"][-1]["mood_avg"] == 3.0

    grant = await api_db.scalar(
        select(m.Consent).where(
            m.Consent.user_id == b.user_id,
            m.Consent.scope == ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
        )
    )
    assert grant is not None
    grant.revoked_at = NOW
    await api_db.commit()
    body = (await fetch(c))["caseload"]
    assert body["sharing_count"] == 1 and body["caseload_size"] == 2
    assert body["weekly"][-1]["mood_avg"] == 2.0 and body["weekly"][-1]["students_reporting"] == 1


async def test_ended_care_links_and_other_caseloads_change_no_number(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    await populated(c)
    before = await fetch(c)
    assert before["caseload"]["caseload_size"] == 2

    other = await colleague(c)
    # a consenting student whose care link has ended, with records of every kind
    gone = await student(c, ended=True)
    # a consenting student on another therapist's caseload, with records of every kind
    theirs = await student(c, link=other)
    foreign_inst, foreign_dept = await c.builder.institution(uuid.uuid4().hex[:8])
    foreign_therapist = await c.builder.user(foreign_inst, UserRole.THERAPIST)
    foreigner = await c.builder.user(foreign_inst, UserRole.STUDENT, department_id=foreign_dept)
    for s in (gone, theirs, foreigner):
        add_mood(c, s, 1, 1)
        add_mood(c, s, 2, 1)
        add_stress(c, s, 1, 5)
        add_sleep(c, s, 1, 3.0)
    for s in (theirs, gone):
        # another therapist's work: appointments, recommendations, follow-ups, alerts
        add_appointment(c, s, APPT.COMPLETED, when(1, hours=3), therapist=other.user_id)
        add_appointment(c, s, APPT.NO_SHOW, when(2, hours=3), therapist=other.user_id)
        add_recommendation(c, s, RecommendationStatus.COMPLETED, when(1), author=other.user_id)
        add_follow_up(
            c, s, FollowUpStatus.OPEN, when(1), NOW.date() - dt.timedelta(days=5),
            therapist=other.user_id,
        )  # fmt: skip
        add_alert(
            c, s, AlertSeverity.IMMINENT, ALERT.RESOLVED, when(1), assigned=other.user_id,
            ack_after_min=5, sla_due=NOW - dt.timedelta(days=1),
        )  # fmt: skip
    add_appointment(
        c, foreigner, APPT.COMPLETED, when(1, hours=3), therapist=foreign_therapist.user_id
    )
    add_alert(
        c, foreigner, AlertSeverity.HIGH, ALERT.OPEN, when(1),
        sla_due=NOW - dt.timedelta(days=1),
    )  # fmt: skip
    await c.db.commit()

    after = await fetch(c)
    assert stable(after) == stable(before)


async def test_the_caseload_of_a_therapist_without_students_is_all_zeros_and_nulls(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    body = await fetch(c, 12)
    assert body["caseload"]["caseload_size"] == 0 and body["caseload"]["sharing_count"] == 0
    assert len(body["caseload"]["weekly"]) == 12
    assert all(
        w["students_reporting"] == 0 and w["mood_avg"] is None for w in body["caseload"]["weekly"]
    )
    appointments = body["appointments"]
    assert set(appointments["by_status"].values()) == {0}
    assert set(appointments["by_mode"].values()) == {0}
    assert appointments["rates"] == {"completion": None, "no_show": None, "cancellation": None}
    assert all(w["scheduled"] == 0 for w in appointments["weekly"])
    recs = body["interventions"]["recommendations"]
    assert recs["total"] == 0 and recs["completion_rate"] is None
    assert set(recs["by_status"].values()) == {0} and set(blank_week_counts(recs["weekly"])) == {0}
    follow = body["interventions"]["follow_ups"]
    assert follow["total"] == 0 and follow["overdue"] == 0 and follow["done_on_time_rate"] is None
    assert set(follow["by_status"].values()) == {0} and set(follow["by_kind"].values()) == {0}
    alerts = body["alerts"]
    assert alerts["total"] == 0 and alerts["acknowledged_median_minutes"] is None
    assert alerts["overdue_open"] == 0 and alerts["resolved_count"] == 0
    assert set(alerts["by_severity"].values()) == {0} == set(alerts["by_status"].values())


# ---- appointments --------------------------------------------------------------------------


async def test_appointment_counts_weeks_modes_and_rates_are_exact(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s1, s2 = await student(c), await student(c)
    add_appointment(c, s1, APPT.COMPLETED, when(1))
    add_appointment(c, s2, APPT.COMPLETED, when(1, hours=2))
    add_appointment(c, s1, APPT.NO_SHOW, when(1, hours=4), mode=SessionMode.PHONE)
    add_appointment(c, s2, APPT.CANCELLED, when(2), mode=SessionMode.IN_PERSON)
    add_appointment(c, s1, APPT.CONFIRMED, when(2, hours=2))  # still unresolved, not an outcome
    add_appointment(c, s2, APPT.COMPLETED, when(3))
    # not counted: before the window, the week in progress, and the future
    add_appointment(c, s1, APPT.COMPLETED, when(9))
    add_appointment(c, s1, APPT.REQUESTED, when(0, hours=-30))
    add_appointment(c, s1, APPT.CONFIRMED, NOW + dt.timedelta(days=9))
    await c.db.commit()

    a = (await fetch(c))["appointments"]
    assert a["by_status"] == {
        "requested": 0,
        "confirmed": 1,
        "completed": 3,
        "cancelled": 1,
        "no_show": 1,
    }
    assert a["by_mode"] == {"video": 4, "in_person": 1, "phone": 1}
    # three completed, one no-show, one cancelled: 5 reached an outcome; the confirmed one did not
    assert a["rates"] == {"completion": 60, "no_show": 20, "cancellation": 20}
    weekly = {w["week_start"]: w for w in a["weekly"]}
    assert weekly[monday(1)] | {"week_start": None} == {
        "week_start": None,
        "scheduled": 3,
        "completed": 2,
        "no_show": 1,
        "cancelled": 0,
    }
    assert weekly[monday(2)]["scheduled"] == 2 and weekly[monday(2)]["cancelled"] == 1
    assert weekly[monday(3)]["scheduled"] == 1 and weekly[monday(3)]["completed"] == 1
    assert sum(w["scheduled"] for w in a["weekly"]) == 6
    assert (await fetch(c, 12))["appointments"]["by_status"]["completed"] == 4


async def test_rates_are_null_while_nothing_has_reached_an_outcome(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s = await student(c)
    add_appointment(c, s, APPT.CONFIRMED, when(1))
    add_appointment(c, s, APPT.REQUESTED, when(2))
    await c.db.commit()
    a = (await fetch(c))["appointments"]
    assert a["by_status"]["confirmed"] == 1 and a["by_status"]["requested"] == 1
    assert a["rates"] == {"completion": None, "no_show": None, "cancellation": None}


async def test_a_single_outcome_gives_whole_hundred_and_zero_percents(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s = await student(c)
    add_appointment(c, s, APPT.NO_SHOW, when(1))
    await c.db.commit()
    rates = (await fetch(c))["appointments"]["rates"]
    assert rates == {"completion": 0, "no_show": 100, "cancellation": 0}


async def test_appointment_history_with_a_student_who_left_the_caseload_is_still_mine(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    gone = await student(c, ended=True)
    add_appointment(c, gone, APPT.COMPLETED, when(1))
    await c.db.commit()
    body = await fetch(c)
    assert body["caseload"]["caseload_size"] == 0
    assert body["appointments"]["by_status"]["completed"] == 1


# ---- interventions: recommendations -------------------------------------------------------


async def test_only_my_own_suggestions_count_with_their_progress(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s1, s2 = await student(c), await student(c)
    other = await colleague(c)
    P, V, D, C = (
        RecommendationStatus.PENDING,
        RecommendationStatus.VIEWED,
        RecommendationStatus.DISMISSED,
        RecommendationStatus.COMPLETED,
    )
    for status, week, who in (
        (P, 1, s1), (C, 1, s2), (V, 2, s1), (C, 2, s2), (D, 3, s1), (P, 3, s2),
    ):  # fmt: skip
        add_recommendation(c, who, status, when(week))
    # not mine, or not a therapist's suggestion, or outside the window
    add_recommendation(c, s1, C, when(1), author=other.user_id)
    add_recommendation(c, s1, C, when(1), source=RecommendationSource.RULE)
    add_recommendation(c, s1, C, when(10))
    add_recommendation(c, s1, C, NOW)  # the week in progress
    await c.db.commit()

    recs = (await fetch(c))["interventions"]["recommendations"]
    assert recs["total"] == 6
    assert recs["by_status"] == {"pending": 2, "viewed": 1, "dismissed": 1, "completed": 2}
    assert recs["completion_rate"] == 33
    weekly = {w["week_start"]: w["count"] for w in recs["weekly"]}
    assert weekly[monday(1)] == weekly[monday(2)] == weekly[monday(3)] == 2
    assert sum(weekly.values()) == 6
    wider = (await fetch(c, 12))["interventions"]["recommendations"]
    assert wider["total"] == 7 and wider["completion_rate"] == 43


async def test_a_therapist_without_suggestions_has_no_completion_rate(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    recs = (await fetch(c))["interventions"]["recommendations"]
    assert recs["total"] == 0 and recs["completion_rate"] is None


# ---- interventions: follow-ups -------------------------------------------------------------


async def test_follow_up_status_overdue_and_on_time_figures_are_exact(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s = await student(c)
    other = await colleague(c)
    today = NOW.date()
    day = dt.timedelta(days=1)
    noon = dt.time(12)

    def at(d: dt.date) -> dt.datetime:
        return dt.datetime.combine(d, noon, tzinfo=dt.UTC)

    OPEN, DONE, GONE = FollowUpStatus.OPEN, FollowUpStatus.DONE, FollowUpStatus.CANCELLED
    add_follow_up(c, s, OPEN, when(1), today - 2 * day)  # overdue
    add_follow_up(c, s, OPEN, when(1), today - day, kind=FollowUpKind.PAPERWORK)  # overdue
    add_follow_up(c, s, OPEN, when(2), today)  # due today: not overdue yet
    add_follow_up(c, s, OPEN, when(2), today + 3 * day)  # not due yet
    # done: on the day, earlier than due, and a day late
    add_follow_up(
        c, s, DONE, when(1), today - 10 * day, completed_at=at(today - 10 * day),
        kind=FollowUpKind.BOOK_SESSION,
    )  # fmt: skip
    add_follow_up(
        c, s, DONE, when(2), today - 9 * day, completed_at=at(today - 12 * day),
        kind=FollowUpKind.BOOK_SESSION,
    )  # fmt: skip
    add_follow_up(
        c, s, DONE, when(3), today - 20 * day, completed_at=at(today - 19 * day),
        kind=FollowUpKind.REFERRAL,
    )  # fmt: skip
    add_follow_up(c, s, GONE, when(3), today - 30 * day, kind=FollowUpKind.OTHER)
    # not mine / not in the window: another therapist's, and one created before the window
    add_follow_up(c, s, OPEN, when(1), today - 5 * day, therapist=other.user_id)
    add_follow_up(c, s, OPEN, when(10), today - 50 * day)
    await c.db.commit()

    f = (await fetch(c))["interventions"]["follow_ups"]
    assert f["total"] == 8
    assert f["by_status"] == {"open": 4, "done": 3, "cancelled": 1}
    assert f["overdue"] == 2
    assert f["done_on_time_rate"] == 67  # two of three done on or before the due date
    assert f["by_kind"] == {
        "check_in": 3,
        "book_session": 2,
        "referral": 1,
        "paperwork": 1,
        "other": 1,
    }
    wide = (await fetch(c, 12))["interventions"]["follow_ups"]
    assert wide["total"] == 9 and wide["overdue"] == 3


async def test_follow_up_lateness_follows_the_viewers_time_zone(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s = await student(c)
    due = NOW.date() - dt.timedelta(days=6)
    # 20:00 UTC on the due date is already the next morning in India (UTC+5:30)
    finished = dt.datetime.combine(due, dt.time(20), tzinfo=dt.UTC)
    add_follow_up(c, s, FollowUpStatus.DONE, when(1), due, completed_at=finished)
    await c.db.commit()
    assert (await fetch(c))["interventions"]["follow_ups"]["done_on_time_rate"] == 100
    assert (await fetch(c, tz="Asia/Kolkata"))["interventions"]["follow_ups"][
        "done_on_time_rate"
    ] == 0


async def test_no_finished_follow_ups_means_no_on_time_rate(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s = await student(c)
    add_follow_up(c, s, FollowUpStatus.OPEN, when(1), NOW.date() + dt.timedelta(days=2))
    await c.db.commit()
    f = (await fetch(c))["interventions"]["follow_ups"]
    assert f["total"] == 1 and f["overdue"] == 0 and f["done_on_time_rate"] is None


# ---- alerts --------------------------------------------------------------------------------


async def test_alert_counts_median_acknowledge_time_and_overdue_are_exact(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s1, s2 = await student(c), await student(c)
    other = await colleague(c)
    me = c.therapist.id
    past, future = NOW - dt.timedelta(hours=2), NOW + dt.timedelta(hours=2)
    add_alert(c, s1, AlertSeverity.HIGH, ALERT.OPEN, when(1), assigned=me, sla_due=past)  # overdue
    add_alert(
        c, s2, AlertSeverity.MODERATE, ALERT.ACKNOWLEDGED, when(1, hours=1), assigned=me,
        ack_after_min=30, sla_due=past,
    )  # fmt: skip
    add_alert(
        c, s1, AlertSeverity.IMMINENT, ALERT.RESOLVED, when(2), assigned=me, ack_after_min=90,
        sla_due=past,
    )  # fmt: skip
    add_alert(c, s2, AlertSeverity.LOW, ALERT.ESCALATED, when(2, hours=1), sla_due=past)  # overdue
    add_alert(
        c, s1, AlertSeverity.MODERATE, ALERT.DISMISSED, when(3), assigned=me, ack_after_min=45
    )
    add_alert(
        c, s2, AlertSeverity.HIGH, ALERT.IN_PROGRESS, when(3, hours=1), assigned=me,
        ack_after_min=60,
    )  # fmt: skip
    add_alert(c, s1, AlertSeverity.LOW, ALERT.OPEN, when(4), sla_due=future)  # open, not overdue
    # not counted: another therapist's alert, an old one, and one raised this week
    add_alert(c, s1, AlertSeverity.IMMINENT, ALERT.OPEN, when(1), assigned=other.user_id,
              sla_due=past)  # fmt: skip
    add_alert(c, s1, AlertSeverity.IMMINENT, ALERT.OPEN, when(9), sla_due=past)
    add_alert(c, s1, AlertSeverity.IMMINENT, ALERT.OPEN, NOW, sla_due=past)
    await c.db.commit()

    alerts = (await fetch(c))["alerts"]
    assert alerts["total"] == 7
    assert alerts["by_severity"] == {"low": 2, "moderate": 2, "high": 2, "imminent": 1}
    assert alerts["by_status"] == {
        "open": 2,
        "acknowledged": 1,
        "escalated": 1,
        "in_progress": 1,
        "resolved": 1,
        "dismissed": 1,
    }
    weekly = {w["week_start"]: w["count"] for w in alerts["weekly"]}
    assert (weekly[monday(1)], weekly[monday(2)], weekly[monday(3)], weekly[monday(4)]) == (
        2, 2, 2, 1,
    )  # fmt: skip
    assert sum(weekly.values()) == 7
    assert alerts["acknowledged_median_minutes"] == 52.5  # 30, 45, 60, 90
    assert alerts["overdue_open"] == 2  # the open and the escalated one past their due time
    assert alerts["resolved_count"] == 1


async def test_median_acknowledge_time_is_null_until_something_is_acknowledged(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    s = await student(c)
    add_alert(c, s, AlertSeverity.LOW, ALERT.OPEN, when(1))
    await c.db.commit()
    alerts = (await fetch(c))["alerts"]
    assert alerts["total"] == 1 and alerts["acknowledged_median_minutes"] is None
    assert alerts["overdue_open"] == 0  # no due time recorded, nothing is overdue


async def test_unassigned_alerts_are_the_counselling_teams_and_so_are_counted(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Same visibility as the therapist's alert list: assigned to me, or to nobody."""
    c = await clinic(client, api_db, world)
    unrelated = await student(c, link=False)
    add_alert(c, unrelated, AlertSeverity.HIGH, ALERT.OPEN, when(1))
    await c.db.commit()
    listed = (await c.therapist.get("/therapist/alerts")).json()
    assert len(listed) == 1
    assert (await fetch(c))["alerts"]["total"] == len(listed)


# ---- privacy and isolation -----------------------------------------------------------------


async def test_the_payload_names_nobody_and_carries_no_free_text(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    one, two = await populated(c)
    stranger = await student(c, link=False)
    add_alert(c, stranger, AlertSeverity.HIGH, ALERT.OPEN, when(1))  # unassigned
    await c.db.commit()
    people = [one, two, stranger]
    for weeks in (4, 8, 12):
        r = await c.therapist.get(f"{PATH}?weeks={weeks}")
        text = json.dumps(r.json())
        for p in people:
            u = await api_db.get(m.User, p.user_id)
            assert u is not None
            for secret in (str(p.user_id), p.email, u.full_name, u.full_name.split()[-1]):
                assert secret not in text, secret
        assert SECRET not in text and "SYNTHETIC" not in text
        assert str(c.therapist.id) not in text and c.therapist.actor.email not in text

        def keys(node: Any) -> set[str]:
            if isinstance(node, dict):
                return set(node) | {k for v in node.values() for k in keys(v)}
            if isinstance(node, list):
                return {k for v in node for k in keys(v)}
            return set()

        names = {k.lower() for k in keys(r.json())}
        assert not {"student_id", "student", "name", "full_name", "email", "id", "title"} & names
        assert not {"note", "body", "excerpt", "rationale", "reason", "category"} & names


async def test_the_read_is_audited_with_counts_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    one, two = await populated(c)
    await fetch(c, 12)
    events = list(
        await api_db.scalars(
            select(m.AuditLog).where(
                m.AuditLog.actor_id == c.therapist.id,
                m.AuditLog.action == "therapist_analytics.read",
            )
        )
    )
    assert len(events) == 1
    e = events[0]
    assert e.subject_student_id is None and e.resource_id is None
    assert e.details == {
        "weeks": 12,
        "caseload": 2,
        "sharing": 2,
        "appointments": 2,
        "recommendations": 2,
        "follow_ups": 2,
        "alerts": 2,
    }
    blob = json.dumps(e.details) + str(e.reason)
    assert str(one.user_id) not in blob and str(two.user_id) not in blob and SECRET not in blob


async def test_two_reads_give_the_same_figures(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world)
    await populated(c)
    assert stable(await fetch(c)) == stable(await fetch(c))


# ---- who may ask ---------------------------------------------------------------------------


async def test_authentication_is_required(client: httpx.AsyncClient, world: World) -> None:
    r = await call(client, "GET", PATH)
    assert r.status_code == 401
    bad = await call(client, "GET", PATH, token="not-a-token")
    assert bad.status_code == 401


@pytest.mark.parametrize("role", ["student", "teacher", "admin"])
async def test_other_roles_are_refused(client: httpx.AsyncClient, world: World, role: str) -> None:
    token = await token_for(client, getattr(world, role), world.password)
    r = await call(client, "GET", PATH, token=token)
    assert r.status_code == 403
    assert "weeks" not in r.text and "caseload" not in r.text


async def test_the_seeded_therapist_may_ask(client: httpx.AsyncClient, world: World) -> None:
    token = await token_for(client, world.therapist, world.password)
    r = await call(client, "GET", PATH, token=token)
    assert r.status_code == 200, r.text
    assert r.json()["caseload"]["caseload_size"] >= 1


async def test_a_therapist_of_another_institution_sees_only_their_own(
    client: httpx.AsyncClient, world: World
) -> None:
    token = await token_for(client, world.b_therapist, world.password)
    r = await call(client, "GET", PATH, token=token)
    assert r.status_code == 200
    assert r.json()["caseload"]["caseload_size"] >= 1  # their own linked student(s) only


async def test_an_unverified_therapist_gets_the_empty_view_like_the_dashboard(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    c = await clinic(client, api_db, world, verified=False)
    unrelated = await student(c, link=False)
    add_alert(c, unrelated, AlertSeverity.HIGH, ALERT.OPEN, when(1))  # unassigned, in-institution
    await c.db.commit()
    assert (await c.therapist.get("/therapist/dashboard")).status_code == 200
    body = await fetch(c)
    assert body["caseload"]["caseload_size"] == 0
    assert body["alerts"]["total"] == 0 and body["alerts"]["by_severity"]["high"] == 0
    assert len(body["alerts"]["weekly"]) == 8


# ---- the small pure helpers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("part", "whole", "expected"),
    [(0, 0, None), (3, 0, None), (0, 5, 0), (1, 3, 33), (2, 3, 67), (1, 8, 13), (5, 5, 100)],
)
async def test_percent_rounds_half_up_and_has_no_zero_denominator(
    part: int, whole: int, expected: int | None
) -> None:
    assert ta.percent(part, whole) == expected


async def test_median_and_mean_helpers() -> None:
    minute = dt.timedelta(minutes=1)
    assert ta.median_minutes([]) is None
    assert ta.median_minutes([5 * minute]) == 5.0
    assert ta.median_minutes([minute, 3 * minute, 100 * minute]) == 3.0
    assert ta.median_minutes([minute, 2 * minute]) == 1.5
    assert ta.mean([]) is None and ta.mean([1, 2, 4]) == 2.33


@pytest.mark.parametrize("value", [None, 4, 8, 12])
async def test_allowed_windows(value: int | None) -> None:
    assert ta.check_weeks(value) == (value or 8)
