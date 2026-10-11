"""Administrator service analytics: platform usage, counselling utilisation, engagement.

Every test builds its own institution with known numbers, so an exact count can be asserted and
nothing else in the shared database (the seed, other tests) can change it. The rules proved here:

* counts of 1 to 4 are ``null`` ("fewer than 5"), zero stays zero, 5 is shown;
* people are counted once however much they do (distinct students);
* utilisation is hours booked over hours offered, rounded to the nearest 5 percent;
* an engagement group shows only when 5 different students are in it, whatever the number of
  suggestions;
* another institution's data never counts, and nothing identifies a person or quotes a word.
"""

import dataclasses
import datetime as dt
import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import admin_usage
from app.domain.wellness.recommender.catalog import AREAS
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AIMessageRole,
    AIReplyKind,
    AppointmentStatus,
    AuditOutcome,
    FeedbackRating,
    RecommendationSource,
    RecommendationStatus,
    SessionMode,
    UserRole,
)
from app.infrastructure.db.ids import uuid7
from tests.api_world import Actor, Builder, World
from tests.student_helpers import Session, sign_in
from tests.teacher_helpers import wednesday
from tests.test_teacher_portal_privacy import json_keys

pytestmark = pytest.mark.asyncio

URL = "/admin/analytics/services"
SECRET = "SENTINEL-USAGE-31337"  # planted in every free-text field; must never be returned


# ---- arrange ---------------------------------------------------------------------------------


@dataclasses.dataclass
class Org:
    """A brand-new institution with an administrator, one therapist and a pool of students."""

    db: AsyncSession
    inst: uuid.UUID
    dept: uuid.UUID
    admin: Session
    therapist: Actor
    students: list[Actor]

    def monday(self, weeks_ago: int) -> dt.datetime:
        """00:00 UTC on the Monday of a calendar week (1 = the last completed week)."""
        mid = wednesday(weeks_ago)
        return (mid - dt.timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)

    def week_start(self, weeks_ago: int) -> str:
        return str(self.monday(weeks_ago).date())


async def org(
    client: httpx.AsyncClient, db: AsyncSession, world: World, *, students: int = 12
) -> Org:
    b = Builder(db, world.password)
    inst, dept = await b.institution(uuid.uuid4().hex[:8])
    admin = await b.user(inst, UserRole.ADMINISTRATOR)
    therapist = await b.user(inst, UserRole.THERAPIST)
    pool = [await b.user(inst, UserRole.STUDENT, department_id=dept) for _ in range(students)]
    await db.commit()
    return Org(db, inst, dept, await sign_in(client, admin, world.password), therapist, pool)


async def get(o: Org, weeks: int | None = 4) -> dict[str, Any]:
    r = await o.admin.get(URL if weeks is None else f"{URL}?weeks={weeks}")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def mood(o: Org, student: Actor, when: dt.datetime) -> None:
    o.db.add(
        m.MoodEntry(
            institution_id=o.inst,
            student_id=student.user_id,
            mood_score=3,
            note=f"{SECRET} mood note",
            logged_at=when,
        )
    )


def stress(o: Org, student: Actor, when: dt.datetime) -> None:
    o.db.add(
        m.StressAssessment(
            institution_id=o.inst,
            student_id=student.user_id,
            scale="perceived_stress_10",
            score=20,
            max_score=40,
            perceived_stress_level=3,
            stressors=["exams"],
            completed_at=when,
        )
    )


def sleep(o: Org, student: Actor, when: dt.datetime) -> None:
    wake = when.replace(hour=6)
    o.db.add(
        m.SleepEntry(
            institution_id=o.inst,
            student_id=student.user_id,
            sleep_date=wake.date(),
            bedtime=wake - dt.timedelta(hours=7),
            wake_time=wake,
            duration_minutes=420,
            quality=3,
        )
    )


def companion(o: Org, student: Actor, when: dt.datetime, user: int, assistant: int = 0) -> None:
    """One conversation with ``user`` student messages and ``assistant`` replies."""
    convo = m.AIConversation(id=uuid7(), institution_id=o.inst, student_id=student.user_id)
    o.db.add(convo)
    seq = 0
    for _ in range(user):
        seq += 1
        o.db.add(
            m.AIMessage(
                conversation_id=convo.id,
                seq=seq,
                role=AIMessageRole.USER,
                content=f"{SECRET} companion question",
                created_at=when,
            )
        )
    for _ in range(assistant):
        seq += 1
        o.db.add(
            m.AIMessage(
                conversation_id=convo.id,
                seq=seq,
                role=AIMessageRole.ASSISTANT,
                content=f"{SECRET} companion answer",
                reply_kind=AIReplyKind.REPLY,
                created_at=when,
            )
        )


def chat(o: Org, student: Actor, when: dt.datetime, *, from_student: bool) -> None:
    o.db.add(
        m.Message(
            institution_id=o.inst,
            student_id=student.user_id,
            therapist_id=o.therapist.user_id,
            sender_id=student.user_id if from_student else o.therapist.user_id,
            body=f"{SECRET} private message",
            created_at=when,
        )
    )


async def sign_ins(
    o: Org, when: dt.datetime, n: int, *, action: str = "auth.login", ok: bool = True
) -> None:
    for _ in range(n):
        await append_audit_event(
            o.db,
            institution_id=o.inst,
            actor_id=o.students[0].user_id,
            actor_role=UserRole.STUDENT,
            action=action,
            outcome=AuditOutcome.ALLOWED if ok else AuditOutcome.DENIED,
            resource_type="user",
            occurred_at=when,
        )


# ---- who may call it, and which windows -------------------------------------------------------


async def test_only_administrators_may_read(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    assert (await client.get(f"/api/v1{URL}")).status_code == 401
    for actor in (world.student, world.teacher, world.therapist):
        who = await sign_in(client, actor, world.password)
        assert (await who.get(URL)).status_code == 403, actor.role
    me = await org(client, api_db, world, students=1)
    assert (await me.admin.get(URL)).status_code == 200


async def test_only_four_eight_or_twelve_weeks(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world, students=1)
    for weeks, expected in ((None, 8), (4, 4), (8, 8), (12, 12)):
        body = await get(o, weeks)
        assert body["window_weeks"] == expected
        assert len(body["usage"]["weekly"]) == expected
        assert len(body["utilisation"]["weekly"]) == expected
    first = body["usage"]["weekly"][0]["week_start"]
    assert body["window_start"] == first
    start = dt.date.fromisoformat(body["window_start"])
    assert dt.date.fromisoformat(body["window_end"]) == start + dt.timedelta(weeks=12, days=-1)
    assert start.weekday() == 0
    for bad in (1, 3, 5, 7, 13, 52, -4):  # 0 means "not given", as on the other endpoints
        assert (await o.admin.get(f"{URL}?weeks={bad}")).status_code == 422, bad
    assert (await o.admin.get(f"{URL}?weeks=many")).status_code == 422
    assert "individual" in body["disclaimer"]


async def test_the_read_is_audited_with_counts_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world)
    await get(o, 8)
    await api_db.rollback()
    row = await api_db.scalar(
        select(m.AuditLog)
        .where(m.AuditLog.institution_id == o.inst, m.AuditLog.action == "service_analytics.read")
        .order_by(m.AuditLog.seq.desc())
        .limit(1)
    )
    assert row is not None
    assert row.actor_id == o.admin.id and row.subject_student_id is None
    assert set(row.details) == {"weeks", "groups", "suppressed_groups"}
    assert row.details["weeks"] == 8
    assert all(isinstance(v, int) for v in row.details.values())


# ---- usage -----------------------------------------------------------------------------------


async def test_usage_is_counted_per_completed_week(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world)
    s = o.students
    # last week: 6 students check in once each; two weeks ago: one student checks in 7 times;
    # three weeks ago: 4 check-ins by 4 students; four weeks ago: nothing at all
    for st in s[:6]:
        mood(o, st, wednesday(1))
    for day in range(7):
        mood(o, s[0], wednesday(2) + dt.timedelta(hours=day))
    for st in s[:4]:
        mood(o, st, wednesday(3))
    # these are outside a 4-week window: this week (still in progress) and five weeks ago
    for st in s[:8]:
        mood(o, st, wednesday(0))
        mood(o, st, wednesday(5))
    await api_db.commit()

    body = await get(o, 4)
    weeks = {w["week_start"]: w for w in body["usage"]["weekly"]}
    assert list(weeks) == [o.week_start(n) for n in (4, 3, 2, 1)]
    assert weeks[o.week_start(1)]["check_ins"] == 6
    assert weeks[o.week_start(1)]["active_students"] == 6
    # seven check-ins, but all by one student: the check-ins are shown, the one student is not
    assert weeks[o.week_start(2)]["check_ins"] == 7
    assert weeks[o.week_start(2)]["active_students"] is None
    assert (
        weeks[o.week_start(3)]["check_ins"] is None
        and weeks[o.week_start(3)]["active_students"] is None
    )
    assert (
        weeks[o.week_start(4)]["check_ins"] == 0 and weeks[o.week_start(4)]["active_students"] == 0
    )
    totals = body["usage"]["totals"]
    assert totals["check_ins"] == 17
    assert totals["active_students"] == 6  # the same six people, counted once

    wide = await get(o, 8)
    by_week = {w["week_start"]: w["check_ins"] for w in wide["usage"]["weekly"]}
    assert by_week[o.week_start(5)] == 8  # five weeks ago is inside an 8-week window
    assert wide["usage"]["totals"]["check_ins"] == 25
    assert wide["usage"]["totals"]["active_students"] == 8


async def test_the_window_edges_are_calendar_weeks_in_utc(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world)
    first, after = o.monday(4), o.monday(0)
    for st in o.students[:5]:
        mood(o, st, first - dt.timedelta(seconds=1))  # last second before the window
        mood(o, st, first)  # first instant
        mood(o, st, after - dt.timedelta(seconds=1))  # last instant (Sunday 23:59:59)
        mood(o, st, after)  # Monday of the week in progress
    await api_db.commit()
    weeks = (await get(o, 4))["usage"]["weekly"]
    assert [w["check_ins"] for w in weeks] == [5, 0, 0, 5]
    assert (await get(o, 4))["usage"]["totals"]["check_ins"] == 10


async def test_active_students_count_any_kind_of_entry_once(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world)
    s, when = o.students, wednesday(1)
    for st in s[:3]:
        mood(o, st, when)
    for st in s[3:5]:
        stress(o, st, when)
    for st in s[5:7]:
        sleep(o, st, when)
    for st in s[:7]:  # everyone again, in every way: still the same seven people
        mood(o, st, when + dt.timedelta(hours=1))
        stress(o, st, when + dt.timedelta(hours=2))
    await api_db.commit()
    week = (await get(o, 4))["usage"]["weekly"][-1]
    assert week["active_students"] == 7
    assert week["check_ins"] == 10  # only mood entries are check-ins: 3 + 7


@pytest.mark.parametrize(("n", "shown"), [(0, 0), (1, None), (4, None), (5, 5), (9, 9)])
async def test_every_usage_count_hides_one_to_four(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, n: int, shown: int | None
) -> None:
    o = await org(client, api_db, world)
    when = wednesday(1)
    for st in o.students[:n]:
        mood(o, st, when)
        chat(o, st, when, from_student=True)
    for _ in range(n):
        companion(o, o.students[0], when, user=1, assistant=2)  # replies are never counted
    await sign_ins(o, when, n)
    await sign_ins(o, when, 3, action="auth.logout")  # not a sign-in
    await sign_ins(o, when, 3, ok=False)  # a refused sign-in is not a sign-in either
    await api_db.commit()

    body = await get(o, 4)
    week = body["usage"]["weekly"][-1]
    expected = {
        "check_ins": shown,
        "active_students": shown,
        "companion_messages": shown,
        "therapist_messages": shown,
        "sign_ins": shown,
    }
    assert {k: week[k] for k in expected} == expected
    assert body["usage"]["totals"] == expected
    # and the weeks around it are zero, never null
    assert [w["check_ins"] for w in body["usage"]["weekly"][:-1]] == [0, 0, 0]


async def test_messages_count_both_directions_and_only_the_student_side_of_the_companion(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world)
    when = wednesday(1)
    for st in o.students[:2]:
        chat(o, st, when, from_student=True)
        chat(o, st, when, from_student=False)
    companion(o, o.students[0], when, user=4, assistant=4)
    companion(o, o.students[1], when, user=3, assistant=1)
    await api_db.commit()
    week = (await get(o, 4))["usage"]["weekly"][-1]
    assert week["therapist_messages"] is None  # four messages, two each way
    assert week["companion_messages"] == 7  # not the 12 rows, not the 4 replies
    chat(o, o.students[3], when, from_student=True)
    chat(o, o.students[4], when, from_student=False)
    await api_db.commit()
    assert (await get(o, 4))["usage"]["weekly"][-1]["therapist_messages"] == 6


async def test_another_institutions_data_never_counts(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    mine = await org(client, api_db, world)
    theirs = await org(client, api_db, world)
    when = wednesday(1)
    for st in theirs.students:
        mood(theirs, st, when)
        stress(theirs, st, when)
        chat(theirs, st, when, from_student=True)
        companion(theirs, st, when, user=2)
        theirs.db.add(
            m.Recommendation(
                id=uuid7(),
                institution_id=theirs.inst,
                student_id=st.user_id,
                source=RecommendationSource.RULE,
                title="t",
                rationale="r",
                problem_area="stress",
                intervention_key="box_breathing",
                created_at=when,
            )
        )
    await sign_ins(theirs, when, 12)
    slot = await add_slots(theirs, 1, 10, hours=1.0)
    await book(theirs, slot, theirs.students, AppointmentStatus.COMPLETED)
    await api_db.commit()

    body = await get(mine, 12)
    assert all(
        w[k] == 0
        for w in body["usage"]["weekly"]
        for k in ("check_ins", "active_students", "companion_messages", "therapist_messages")
    )
    assert body["utilisation"]["overall"]["capacity_hours"] == 0.0
    assert body["utilisation"]["overall"]["booked_hours"] == 0.0
    assert all(g["suppressed"] for g in body["engagement"]["by_source"])
    assert all(g["suppressed"] for g in body["engagement"]["by_problem_area"])
    assert body["engagement"]["top_interventions"] == []
    # and the other institution does see its own
    assert (await get(theirs, 12))["usage"]["totals"]["check_ins"] == len(theirs.students)


# ---- counselling utilisation -----------------------------------------------------------------


async def add_slots(
    o: Org,
    weeks_ago: int,
    count: int,
    *,
    hours: float,
    mode: SessionMode = SessionMode.VIDEO,
    offset: int = 0,
) -> list[m.TherapistAvailability]:
    """``count`` back-to-back slots of ``hours`` each, from Monday 00:00 of the week plus
    ``offset`` slots (so a second batch in the same week does not overlap the first)."""
    length = dt.timedelta(hours=hours)
    start = o.monday(weeks_ago) + length * offset
    slots = []
    for i in range(count):
        slot = m.TherapistAvailability(
            id=uuid7(),
            institution_id=o.inst,
            therapist_id=o.therapist.user_id,
            starts_at=start + length * i,
            ends_at=start + length * (i + 1),
            mode=mode,
        )
        o.db.add(slot)
        slots.append(slot)
    await o.db.flush()
    return slots


async def book(
    o: Org,
    slots: list[m.TherapistAvailability],
    students: list[Actor],
    status: AppointmentStatus,
) -> None:
    """One appointment per slot, each with the next student in turn."""
    for i, slot in enumerate(slots):
        o.db.add(
            m.Appointment(
                id=uuid7(),
                institution_id=o.inst,
                student_id=students[i % len(students)].user_id,
                therapist_id=o.therapist.user_id,
                availability_id=slot.id,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
                mode=slot.mode,
                status=status,
                reason=f"{SECRET} reason",
                cancelled_at=slot.starts_at - dt.timedelta(days=1)
                if status is AppointmentStatus.CANCELLED
                else None,
            )
        )
    await o.db.flush()


async def test_percent_is_whole_and_rounded_to_the_nearest_five() -> None:
    p = admin_usage.percent_to_5
    assert p(0, 0) is None and p(5, 0) is None
    assert p(0, 8) == 0 and p(8, 8) == 100
    assert p(1, 8) == 15  # 12.5 rounds up
    assert p(1, 3) == 35 and p(2, 3) == 65
    assert p(1, 10) == 10 and p(1, 40) == 5  # 2.5 -> 5
    assert p(1, 100) == 0 and p(2, 100) == 0 and p(3, 100) == 5


async def test_utilisation_arithmetic(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world)
    s = o.students
    # last completed week: ten 1-hour video slots and seven 20-minute phone slots
    video = await add_slots(o, 1, 10, hours=1.0)
    phone = await add_slots(o, 1, 7, hours=1 / 3, mode=SessionMode.PHONE, offset=30)
    # video: six slots booked in different live or finished ways, one only ever cancelled
    await book(o, video[0:1], s, AppointmentStatus.REQUESTED)
    await book(o, video[1:2], s, AppointmentStatus.CONFIRMED)
    await book(o, video[2:4], s, AppointmentStatus.COMPLETED)
    await book(o, video[4:6], s, AppointmentStatus.NO_SHOW)
    await book(o, video[6:7], s, AppointmentStatus.CANCELLED)
    # a slot that was cancelled and then taken again is booked once, not twice
    await book(o, video[3:4], s, AppointmentStatus.CANCELLED)
    # phone: five of seven slots booked
    await book(o, phone[:5], s, AppointmentStatus.COMPLETED)
    # two weeks ago: five 1-hour slots, only two booked (too few to show)
    older = await add_slots(o, 2, 5, hours=1.0)
    await book(o, older[:2], s, AppointmentStatus.COMPLETED)
    # outside a 4-week window
    old = await add_slots(o, 5, 3, hours=1.0)
    await book(o, old, s, AppointmentStatus.COMPLETED)
    await add_slots(o, 0, 2, hours=1.0)
    await api_db.commit()

    u = (await get(o, 4))["utilisation"]
    weeks = {w["week_start"]: w for w in u["weekly"]}
    last = weeks[o.week_start(1)]
    # capacity: 10h video + 140 minutes phone = 12.3h; booked 6h + 100 minutes = 7.7h
    assert last["capacity_hours"] == 12.3 and last["booked_hours"] == 7.7
    assert last["utilisation_percent"] == 60  # 460 / 740 = 62.2%
    quiet = weeks[o.week_start(2)]
    assert quiet["capacity_hours"] == 5.0
    assert quiet["booked_hours"] is None and quiet["utilisation_percent"] is None  # 2 booked
    for ago in (3, 4):  # no slots: zero hours, and no percentage of nothing
        empty = weeks[o.week_start(ago)]
        assert empty["capacity_hours"] == 0.0 and empty["booked_hours"] == 0.0
        assert empty["utilisation_percent"] is None

    overall = u["overall"]
    assert overall["capacity_hours"] == 17.3  # 1040 minutes
    assert overall["booked_hours"] == 9.7  # 580 minutes, 13 booked slots
    assert overall["utilisation_percent"] == 55  # 55.8%
    modes = {x["mode"]: x for x in u["by_mode"]}
    assert list(modes) == ["video", "in_person", "phone"]
    assert modes["video"]["capacity_hours"] == 15.0 and modes["video"]["booked_hours"] == 8.0
    assert modes["video"]["utilisation_percent"] == 55  # 53.3%
    assert modes["phone"]["capacity_hours"] == 2.3 and modes["phone"]["booked_hours"] == 1.7
    assert modes["phone"]["utilisation_percent"] == 70  # 71.4%
    nothing = modes["in_person"]
    assert nothing["capacity_hours"] == 0.0 and nothing["utilisation_percent"] is None

    # the 8-week window reaches the slots five weeks ago
    wide = (await get(o, 8))["utilisation"]
    assert wide["overall"]["capacity_hours"] == 20.3


async def test_a_cell_with_no_booking_is_zero_and_a_full_one_is_a_hundred(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world)
    await add_slots(o, 1, 6, hours=1.0)
    await api_db.commit()
    overall = (await get(o, 4))["utilisation"]["overall"]
    assert overall["capacity_hours"] == 6.0
    assert overall["booked_hours"] == 0.0 and overall["utilisation_percent"] == 0
    await book(o, await slots_of(o), o.students, AppointmentStatus.CONFIRMED)
    await api_db.commit()
    overall = (await get(o, 4))["utilisation"]["overall"]
    assert overall["booked_hours"] == 6.0 and overall["utilisation_percent"] == 100


async def slots_of(o: Org) -> list[m.TherapistAvailability]:
    rows = await o.db.scalars(
        select(m.TherapistAvailability)
        .where(m.TherapistAvailability.institution_id == o.inst)
        .order_by(m.TherapistAvailability.starts_at)
    )
    return list(rows)


async def test_no_show_and_cancellation_shares_follow_the_group_rules(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    # too few appointments to say anything: "hidden"
    tiny = await org(client, api_db, world)
    few = await add_slots(tiny, 1, 3, hours=1.0)
    await book(tiny, few, tiny.students, AppointmentStatus.NO_SHOW)
    await api_db.commit()
    overall = (await get(tiny, 4))["utilisation"]["overall"]
    assert overall["no_show_share"] == {"state": "hidden", "percent": None}
    assert overall["cancellation_share"] == {"state": "hidden", "percent": None}

    # 2 completed, 8 no-shows (nearly all held sessions were missed), 5 cancelled of 15
    o = await org(client, api_db, world)
    slots = await add_slots(o, 1, 15, hours=1.0)
    await book(o, slots[:2], o.students, AppointmentStatus.COMPLETED)
    await book(o, slots[2:10], o.students, AppointmentStatus.NO_SHOW)
    await book(o, slots[10:], o.students, AppointmentStatus.CANCELLED)
    await api_db.commit()
    overall = (await get(o, 4))["utilisation"]["overall"]
    assert overall["no_show_share"] == {"state": "most", "percent": None}
    assert overall["cancellation_share"] == {"state": "shown", "percent": 35}  # 5 of 15
    video = next(x for x in (await get(o, 4))["utilisation"]["by_mode"] if x["mode"] == "video")
    assert video["no_show_share"]["state"] == "most"
    phone = next(x for x in (await get(o, 4))["utilisation"]["by_mode"] if x["mode"] == "phone")
    assert phone["no_show_share"]["state"] == "hidden"

    # 3 completed + 6 no-shows of 12: a quarter... 6 of 9 held = 65%, 3 cancelled -> "few"
    p = await org(client, api_db, world)
    slots = await add_slots(p, 1, 12, hours=1.0)
    await book(p, slots[:3], p.students, AppointmentStatus.COMPLETED)
    await book(p, slots[3:9], p.students, AppointmentStatus.NO_SHOW)
    await book(p, slots[9:], p.students, AppointmentStatus.CANCELLED)
    await api_db.commit()
    overall = (await get(p, 4))["utilisation"]["overall"]
    assert overall["no_show_share"]["state"] == "hidden"  # only 9 sessions were due
    assert overall["cancellation_share"] == {"state": "few", "percent": None}


# ---- intervention engagement -----------------------------------------------------------------


def rec(
    o: Org,
    student: Actor,
    *,
    source: RecommendationSource = RecommendationSource.RULE,
    status: RecommendationStatus = RecommendationStatus.PENDING,
    area: str | None = None,
    key: str | None = None,
    when: dt.datetime | None = None,
    rating: FeedbackRating | None = None,
) -> None:
    rid = uuid7()
    o.db.add(
        m.Recommendation(
            id=rid,
            institution_id=o.inst,
            student_id=student.user_id,
            source=source,
            status=status,
            title=f"{SECRET} title",
            rationale=f"{SECRET} rationale",
            problem_area=area,
            intervention_key=key,
            model_version="test-model" if source is RecommendationSource.MODEL else None,
            created_at=when or wednesday(1),
        )
    )
    if rating is not None:
        o.db.add(
            m.RecommendationFeedback(
                institution_id=o.inst,
                student_id=student.user_id,
                recommendation_id=rid,
                rating=rating,
            )
        )


def group(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next(g for g in rows if g["key"] == key)


COUNTS = ("suggestions", "viewed", "completed", "dismissed", "helpful", "not_helpful")


async def test_a_group_needs_five_different_students_not_many_suggestions(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world)
    s = o.students
    therapist, model = RecommendationSource.THERAPIST, RecommendationSource.MODEL
    done, viewed = RecommendationStatus.COMPLETED, RecommendationStatus.VIEWED
    # therapist / mood: 4 students and 40 suggestions -> suppressed, whatever the count
    for st in s[:4]:
        for _ in range(10):
            rec(o, st, source=therapist, area="mood", key="gratitude_note", status=done)
    # rule / stress: 5 students, 12 suggestions: 5 completed (all found helpful), 5 viewed,
    # 1 dismissed, 1 pending that one student found not helpful
    for st in s[4:9]:
        rec(o, st, area="stress", key="box_breathing", status=done, rating=FeedbackRating.HELPFUL)
        rec(o, st, area="stress", key="box_breathing", status=viewed)
    rec(o, s[5], area="stress", key="box_breathing", status=RecommendationStatus.DISMISSED)
    rec(o, s[6], area="stress", key="box_breathing", rating=FeedbackRating.NOT_HELPFUL)
    # model, no problem area: 5 students, one pending suggestion each
    for st in s[4:9]:
        rec(o, st, source=model, area=None, key="short_walk")
    # outside the window: never counted
    for st in s[:8]:
        rec(o, st, area="sleep_disruption", when=wednesday(0))
        rec(o, st, area="sleep_disruption", when=wednesday(6))
    await api_db.commit()

    e = (await get(o, 4))["engagement"]
    sources = e["by_source"]
    assert [g["key"] for g in sources] == ["rule", "model", "therapist"]
    gone = group(sources, "therapist")
    assert gone["suppressed"] is True and all(gone[c] is None for c in COUNTS)
    expected_rule = {
        "suggestions": 12,
        "viewed": 5,
        "completed": 5,
        "dismissed": None,  # one: fewer than 5
        "helpful": 5,
        "not_helpful": None,  # one: fewer than 5
    }
    shown = group(sources, "rule")
    assert shown["suppressed"] is False
    assert {c: shown[c] for c in COUNTS} == expected_rule
    pending = group(sources, "model")
    assert pending["suppressed"] is False
    assert {c: pending[c] for c in COUNTS} == {
        "suggestions": 5,
        "viewed": 0,
        "completed": 0,
        "dismissed": 0,
        "helpful": 0,
        "not_helpful": 0,
    }

    areas = e["by_problem_area"]
    assert [g["key"] for g in areas] == [*AREAS, "other"]
    assert {c: group(areas, "stress")[c] for c in COUNTS} == expected_rule
    assert group(areas, "mood")["suppressed"] is True
    assert group(areas, "mood")["suggestions"] is None  # not 40
    other = group(areas, "other")  # no problem area -> "other"
    assert other["suppressed"] is False and other["suggestions"] == 5
    for quiet in ("sleep_disruption", "career_anxiety"):  # nothing inside the window
        assert group(areas, quiet)["suppressed"] is True
        assert all(group(areas, quiet)[c] is None for c in COUNTS)

    # keys are shown only with five different students behind them
    assert e["top_interventions"] == [
        {"intervention_key": "box_breathing", "students": 5},
        {"intervention_key": "short_walk", "students": 5},
    ]
    # nine different students in all: too few for a share
    assert e["completion_share"] == {"state": "hidden", "percent": None}
    assert e["helpful_share"] == {"state": "hidden", "percent": None}


async def test_four_students_is_suppressed_and_five_is_shown(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world)
    for st in o.students[:4]:
        rec(o, st, area="mood", status=RecommendationStatus.COMPLETED)
    for st in o.students[4:9]:
        rec(o, st, area="stress", status=RecommendationStatus.COMPLETED)
    for _ in range(30):  # one student, many suggestions
        rec(o, o.students[9], area="engagement")
    await api_db.commit()
    areas = (await get(o, 4))["engagement"]["by_problem_area"]
    assert group(areas, "mood")["suppressed"] is True
    assert group(areas, "stress")["suppressed"] is False
    assert group(areas, "stress")["completed"] == 5
    assert group(areas, "engagement")["suppressed"] is True  # 30 suggestions, 1 student


@pytest.mark.parametrize(
    ("students", "completed", "rated", "helpful", "completion", "found_helpful"),
    [
        (9, 9, 9, 9, ("hidden", None), ("hidden", None)),
        (20, 3, 12, 2, ("few", None), ("few", None)),
        (20, 10, 14, 8, ("shown", 50), ("shown", 55)),
        (20, 17, 12, 11, ("most", None), ("most", None)),
    ],
)
async def test_completion_and_helpful_shares_count_students_not_suggestions(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    students: int,
    completed: int,
    rated: int,
    helpful: int,
    completion: tuple[str, int | None],
    found_helpful: tuple[str, int | None],
) -> None:
    o = await org(client, api_db, world, students=students)
    for i, st in enumerate(o.students):
        status = RecommendationStatus.COMPLETED if i < completed else RecommendationStatus.VIEWED
        rating = None
        if i < rated:
            rating = FeedbackRating.HELPFUL if i < helpful else FeedbackRating.NOT_HELPFUL
        rec(o, st, area="stress", status=status, rating=rating)
    # the first student has four more finished, helpful suggestions: still one student each way
    for _ in range(4):
        rec(
            o,
            o.students[0],
            area="stress",
            status=RecommendationStatus.COMPLETED,
            rating=FeedbackRating.HELPFUL,
        )
    await api_db.commit()
    e = (await get(o, 4))["engagement"]
    assert (e["completion_share"]["state"], e["completion_share"]["percent"]) == completion
    assert (e["helpful_share"]["state"], e["helpful_share"]["percent"]) == found_helpful


async def test_top_interventions_need_five_students_and_are_rounded_down(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world, students=17)
    plan = {"k1": 17, "k2": 14, "k3": 11, "k4": 9, "k5": 7, "k6": 5, "k7": 4}
    for key, n in plan.items():
        for st in o.students[:n]:
            for _ in range(3 if key == "k7" else 1):  # k7: four students, many suggestions
                rec(o, st, key=key)
    rec(o, o.students[0])  # no key at all
    await api_db.commit()
    top = (await get(o, 4))["engagement"]["top_interventions"]
    assert top == [
        {"intervention_key": "k1", "students": 15},
        {"intervention_key": "k2", "students": 10},
        {"intervention_key": "k3", "students": 10},
        {"intervention_key": "k4", "students": 5},
        {"intervention_key": "k5", "students": 5},
    ]  # k6 has five students but the list stops at five keys; k7 has too few


# ---- privacy ---------------------------------------------------------------------------------

FORBIDDEN_KEYS = {
    "id",
    "student_id",
    "user_id",
    "therapist_id",
    "resource_id",
    "email",
    "name",
    "full_name",
    "title",
    "rationale",
    "body",
    "content",
    "note",
    "reason",
    "message",
}


async def test_nothing_identifies_a_person_or_quotes_a_word(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    o = await org(client, api_db, world, students=14)
    s, when = o.students, wednesday(1)
    for i, st in enumerate(s):
        mood(o, st, when)
        stress(o, st, when)
        sleep(o, st, when)
        chat(o, st, when, from_student=True)
        chat(o, st, when, from_student=False)
        companion(o, st, when, user=2, assistant=2)
        rec(
            o,
            st,
            area="stress",
            key="box_breathing",
            status=RecommendationStatus.COMPLETED if i < 7 else RecommendationStatus.VIEWED,
            rating=FeedbackRating.HELPFUL if i < 7 else FeedbackRating.NOT_HELPFUL,
        )
    await sign_ins(o, when, 6)
    slots = await add_slots(o, 1, 14, hours=1.0)
    await book(o, slots, s, AppointmentStatus.COMPLETED)
    await api_db.commit()
    people = list(
        await api_db.execute(
            select(m.User.id, m.User.email, m.User.full_name).where(m.User.institution_id == o.inst)
        )
    )
    assert len(people) == 14 + 2

    for weeks in (4, 8, 12):
        r = await o.admin.get(f"{URL}?weeks={weeks}")
        assert r.status_code == 200
        body = r.json()
        raw = json.dumps(body)
        # a busy, real response: the numbers are there, the people are not
        assert body["usage"]["totals"]["check_ins"] == 14
        assert body["utilisation"]["overall"]["booked_hours"] == 14.0
        assert body["engagement"]["completion_share"]["state"] == "shown"
        for user_id, email, full_name in people:
            assert str(user_id) not in raw
            assert email not in raw and email.split("@")[0] not in raw
            assert full_name not in raw
        for slot in slots:
            assert str(slot.id) not in raw
        for word in (SECRET, "private message", "rationale", "reason"):
            assert word not in raw
        assert not (set(json_keys(body)) & FORBIDDEN_KEYS), set(json_keys(body)) & FORBIDDEN_KEYS
