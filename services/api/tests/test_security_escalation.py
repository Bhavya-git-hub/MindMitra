"""Privilege-escalation matrix (security audit, October 2026).

Each test is one attempted escalation path against the real app over HTTP: an actor tries to
reach data or powers that belong to someone else. A test passes when the attempt is refused (or
returns nothing private). Together they are the evidence for the authorization section of the
audit report, so each name says what was tried.

Areas: unauthenticated access to every route, student/teacher/therapist/administrator reaching
beyond their own records, care-link and consent changes, unverified therapists, cross-institution
access for every role, mass assignment and self-elevation, accounts that were suspended,
deactivated, deleted or changed role, and "not found" answers that must not reveal existence.

Every scene is built from fresh people, so the shared cast in ``api_world`` is never disturbed.
"""

import dataclasses
import datetime as dt
import re
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.main import PUBLIC_ROUTES, ROUTERS
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AIConversationStatus,
    AIMessageRole,
    CareRole,
    UserRole,
    UserStatus,
    VerificationStatus,
)
from app.infrastructure.db.ids import uuid7
from tests.api_helpers import call, token_for
from tests.api_world import NOW, Builder, World
from tests.student_helpers import Session, new_student, sign_in
from tests.teacher_helpers import school
from tests.therapist_helpers import (
    Pair,
    care_pair,
    due_appointment,
    end_care_link,
    fresh_admin,
    fresh_therapist,
    started_session,
)

pytestmark = pytest.mark.asyncio

RANDOM = uuid.UUID("0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b")  # a well-formed id nobody owns

# Planted text: none of it may ever reach anyone but the people entitled to it.
DM = "ESC-SENTINEL-PRIVATE-MESSAGE"
AI = "ESC-SENTINEL-COMPANION-CHAT"
NOTE = "ESC-SENTINEL-THERAPY-NOTE"
FOLLOW = "ESC-SENTINEL-FOLLOW-UP-NOTE"
HELP = "ESC-SENTINEL-HELP-REQUEST"
ASK = "ESC-SENTINEL-ASK-A-TEACHER"
REFERRAL = "ESC-SENTINEL-REFERRAL-NOTE"
CLINICAL = (DM, AI, NOTE, FOLLOW, HELP)  # never for teachers or administrators
EVERYTHING = (*CLINICAL, ASK, REFERRAL)


@dataclasses.dataclass
class Scene:
    """A student on a verified therapist's care team, sharing mood and questionnaires, who has
    a record of every private kind; a teacher who teaches them; and the ids of all of it."""

    pair: Pair
    teacher: Session
    course: uuid.UUID
    goal: str
    recommendation: str
    appointment: str
    conversation: uuid.UUID
    session: uuid.UUID
    follow_up: str
    notification: str
    alert: str
    ask: str
    referral: str
    free_slot: uuid.UUID

    @property
    def student(self) -> Session:
        return self.pair.student

    @property
    def therapist(self) -> Session:
        return self.pair.therapist


async def _ok(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()


async def build_scene(client: httpx.AsyncClient, db: AsyncSession, world: World) -> Scene:
    pair = await care_pair(client, db, world, mood=True, assessments=True)
    s, t = pair.student, pair.therapist
    goal = await _ok(await s.post("/me/goals", {"title": "Sleep by 11", "category": "sleep"}), 201)
    rec = await _ok(
        await t.post(
            f"/therapist/students/{s.id}/recommendations",
            {"title": "A short walk", "rationale": "Fresh air can help."},
        ),
        201,
    )
    appointment = (await _ok(await s.get("/me/appointments")))[0]["id"]
    await _ok(await s.post(f"/me/conversations/{t.id}/messages", {"body": DM}), 201)
    session = await started_session(db, pair)
    await _ok(await t.put(f"/therapist/sessions/{session}/note", {"body": NOTE}))
    due = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    follow_up = await _ok(
        await t.post(
            "/therapist/follow-ups",
            {"student_id": str(s.id), "kind": "check_in", "due_on": due, "note": FOLLOW},
        ),
        201,
    )
    alert = await _ok(await s.post("/me/support-requests", {"message": HELP}), 201)
    notification = (await _ok(await s.get("/me/notifications")))["items"][0]["id"]
    free_slot = await db.scalar(
        select(m.TherapistAvailability.id)
        .where(
            m.TherapistAvailability.therapist_id == t.id,
            ~select(m.Appointment.id)
            .where(m.Appointment.availability_id == m.TherapistAvailability.id)
            .exists(),
        )
        .limit(1)
    )
    assert free_slot is not None

    convo = m.AIConversation(
        id=uuid7(),
        institution_id=world.inst_a,
        student_id=s.id,
        status=AIConversationStatus.ACTIVE,
        started_at=NOW,
    )
    db.add(convo)
    await db.flush()
    db.add(m.AIMessage(conversation_id=convo.id, seq=1, role=AIMessageRole.USER, content=AI))
    teacher_actor = await Builder(db, world.password).user(
        world.inst_a, UserRole.TEACHER, department_id=world.dept_a
    )
    tag = uuid.uuid4().hex[:6].upper()
    course = m.Course(
        id=uuid7(),
        institution_id=world.inst_a,
        department_id=world.dept_a,
        code=f"E{tag}",
        title="Escalation 101",
        term="2026-autumn",
    )
    db.add(course)
    await db.flush()
    db.add(
        m.CourseTeacher(
            institution_id=world.inst_a, course_id=course.id, teacher_id=teacher_actor.user_id
        )
    )
    db.add(m.CourseEnrollment(institution_id=world.inst_a, course_id=course.id, student_id=s.id))
    await db.commit()
    teacher = await sign_in(client, teacher_actor, world.password)
    ask = await _ok(
        await s.post(
            "/me/teacher-support",
            {
                "course_id": str(course.id),
                "teacher_id": str(teacher.id),
                "topic": "workload",
                "message": ASK,
            },
        ),
        201,
    )
    referral = await _ok(
        await teacher.post(
            "/teacher/referrals",
            {
                "student_id": str(s.id),
                "course_id": str(course.id),
                "category": "wellbeing_concern",
                "note": REFERRAL,
            },
        ),
        201,
    )
    return Scene(
        pair=pair,
        teacher=teacher,
        course=course.id,
        goal=goal["id"],
        recommendation=rec["id"],
        appointment=appointment,
        conversation=convo.id,
        session=session,
        follow_up=follow_up["id"],
        notification=notification,
        alert=alert["id"],
        ask=ask["id"],
        referral=referral["id"],
        free_slot=free_slot,
    )


Attempt = tuple[str, str, Any]


async def _attempt(who: Session, method: str, path: str, body: Any = None) -> httpx.Response:
    return await call(who.client, method, path, token=who.token, json=body)


async def assert_refused(
    who: Session, attempts: list[Attempt], allowed: set[int], secrets: tuple[str, ...] = EVERYTHING
) -> None:
    """Every attempt answers one of ``allowed`` and carries none of the planted text."""
    for method, path, body in attempts:
        r = await _attempt(who, method, path, body)
        assert r.status_code in allowed, f"{method} {path}: {r.status_code} {r.text}"
        leaked = [x for x in secrets if x in r.text]
        assert leaked == [], f"{method} {path} leaked {leaked}"


def _student_records(sc: Scene) -> list[Attempt]:
    """Every id-bearing route a student uses for their own records, aimed at ``sc``'s."""
    t = sc.therapist.id
    return [
        ("PATCH", f"/me/goals/{sc.goal}", {"status": "abandoned"}),
        ("PATCH", f"/me/recommendations/{sc.recommendation}", {"status": "dismissed"}),
        ("PUT", f"/me/recommendations/{sc.recommendation}/feedback", {"rating": "helpful"}),
        ("DELETE", f"/me/recommendations/{sc.recommendation}/feedback", None),
        ("PATCH", f"/me/appointments/{sc.appointment}", {"status": "cancelled"}),
        (
            "POST",
            f"/me/appointments/{sc.appointment}/reschedule",
            {"availability_id": str(sc.free_slot)},
        ),
        ("GET", f"/companion/conversations/{sc.conversation}", None),
        ("POST", f"/companion/conversations/{sc.conversation}/messages", {"content": "hi"}),
        ("DELETE", f"/companion/conversations/{sc.conversation}", None),
        ("GET", f"/me/conversations/{t}/messages", None),
        ("POST", f"/me/conversations/{t}/messages", {"body": "hello"}),
        ("POST", f"/me/conversations/{t}/read", None),
        ("POST", f"/me/notifications/{sc.notification}/read", None),
        ("POST", f"/me/teacher-support/{sc.ask}/withdraw", None),
    ]


def _therapist_reads(sc: Scene) -> list[Attempt]:
    """Every therapist route that names ``sc``'s student or their clinical records."""
    s = sc.student.id
    due = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    return [
        ("GET", f"/therapist/students/{s}", None),
        ("GET", f"/therapist/students/{s}/trends", None),
        ("GET", f"/therapist/students/{s}/assessments", None),
        ("GET", f"/therapist/students/{s}/indicators", None),
        ("GET", f"/therapist/students/{s}/recommendations", None),
        (
            "POST",
            f"/therapist/students/{s}/recommendations",
            {"title": "Try this", "rationale": "It may help."},
        ),
        ("GET", f"/students/{s}/mood-entries", None),
        ("GET", f"/students/{s}/therapy-notes", None),
        ("GET", f"/therapist/sessions/{sc.session}/note", None),
        ("PUT", f"/therapist/sessions/{sc.session}/note", {"body": "overwrite"}),
        ("PATCH", f"/therapist/sessions/{sc.session}", {"status": "abandoned"}),
        ("PATCH", f"/therapist/follow-ups/{sc.follow_up}", {"status": "done"}),
        (
            "POST",
            "/therapist/follow-ups",
            {"student_id": str(s), "kind": "check_in", "due_on": due},
        ),
        ("PATCH", f"/therapist/alerts/{sc.alert}", {"action": "acknowledge"}),
        ("GET", f"/me/conversations/{s}/messages", None),
        ("POST", f"/me/conversations/{s}/messages", {"body": "hello"}),
        ("PATCH", f"/appointments/{sc.appointment}", {"status": "cancelled"}),
        (
            "POST",
            f"/therapist/appointments/{sc.appointment}/reschedule",
            {"availability_id": str(sc.free_slot)},
        ),
        ("POST", f"/therapist/appointments/{sc.appointment}/session", None),
        ("GET", f"/therapist/referrals/{sc.referral}", None),
        ("POST", f"/therapist/referrals/{sc.referral}/claim", None),
        ("DELETE", f"/therapist/availability/{sc.free_slot}", None),
    ]


def _teacher_records(sc: Scene) -> list[Attempt]:
    return [
        ("GET", f"/teacher/classes/{sc.course}", None),
        ("GET", f"/teacher/classes/{sc.course}/students", None),
        ("GET", f"/teacher/classes/{sc.course}/analytics", None),
        ("GET", f"/teacher/referrals/{sc.referral}", None),
        ("POST", f"/teacher/support-requests/{sc.ask}/acknowledge", None),
        ("POST", f"/teacher/support-requests/{sc.ask}/close", None),
    ]


# ---- unauthenticated -------------------------------------------------------------------------


def _filled(path: str) -> str:
    def value(match: re.Match[str]) -> str:
        return "share_mood_with_care_team" if match.group(1) == "scope" else str(RANDOM)

    return re.sub(r"\{(\w+)\}", value, path)


async def test_unauthenticated_every_non_public_route_returns_401(
    client: httpx.AsyncClient, api_app: FastAPI
) -> None:
    """Enumerates what the app actually serves (its OpenAPI paths, which the route-coverage
    test ties to ``ROUTERS``), not a hand-written list: a new route is covered on arrival."""
    tried = 0
    for template, operations in api_app.openapi()["paths"].items():
        for method in sorted(op.upper() for op in operations):
            if (method, template) in PUBLIC_ROUTES:
                continue
            path = _filled(template)
            for headers in ({}, {"Authorization": "Bearer not-a-real-token"}):
                r = await client.request(method, path, headers=headers)
                assert r.status_code == 401, f"{method} {template} {headers}: {r.status_code}"
                assert r.headers["www-authenticate"] == "Bearer"
            tried += 1
    assert tried > 150


# ---- student -> another student --------------------------------------------------------------


async def test_student_cannot_touch_another_students_records_by_id(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Goals, suggestions, feedback, appointments, companion chats, messages, notifications and
    teacher requests of another student: all 'not found', nothing changes."""
    sc = await build_scene(client, api_db, world)
    intruder = await new_student(client, api_db, world)
    await assert_refused(intruder, _student_records(sc), {404})
    goals = await _ok(await sc.student.get("/me/goals"))
    assert [g["status"] for g in goals if g["id"] == sc.goal] == ["active"]
    appts = await _ok(await sc.student.get("/me/appointments"))
    assert {a["status"] for a in appts if a["id"] == sc.appointment} == {"confirmed"}
    detail = await _ok(await sc.student.get(f"/companion/conversations/{sc.conversation}"))
    assert detail["messages"][0]["content"] == AI


async def test_student_lists_and_export_never_include_another_students_records(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    intruder = await new_student(client, api_db, world)
    ids = {sc.goal, sc.recommendation, sc.appointment, str(sc.conversation), sc.alert, sc.ask}
    for path in (
        "/me/goals",
        "/me/recommendations",
        "/me/recommendations/history",
        "/me/appointments",
        "/me/ai-conversations",
        "/companion/conversations",
        "/me/conversations",
        "/me/notifications",
        "/me/teacher-support",
        "/me/wellness/mood-entries",
        "/me/privacy/access-history",
        "/me/privacy/export",
        "/me/safety/status",
        "/me/dashboard",
    ):
        r = await intruder.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
        assert not [x for x in (*EVERYTHING, *ids, str(sc.student.id)) if x in r.text], path


async def test_student_cannot_read_another_students_wellness_through_staff_routes(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    intruder = await new_student(client, api_db, world)
    # 403 by permission; 404 for the shared messaging route, which finds no care link
    await assert_refused(intruder, _therapist_reads(sc), {403, 404})


async def test_student_cannot_message_another_student_or_another_students_therapist(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    intruder = await new_student(client, api_db, world)
    await assert_refused(
        intruder,
        [
            ("POST", f"/me/conversations/{sc.student.id}/messages", {"body": "hi"}),
            ("GET", f"/me/conversations/{sc.student.id}/messages", None),
            ("GET", f"/me/conversations/{sc.therapist.id}/messages", None),
        ],
        {404},
    )


# ---- student -> therapist and teacher data ---------------------------------------------------


async def test_student_cannot_reach_therapist_notes_caseload_follow_ups_or_alerts(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Even the student the records are about is refused: notes belong to the therapist."""
    sc = await build_scene(client, api_db, world)
    attempts = _therapist_reads(sc) + [
        ("GET", "/therapist/students", None),
        ("GET", "/students", None),
        ("GET", "/therapist/follow-ups", None),
        ("GET", "/therapist/alerts", None),
        ("GET", "/therapist/sessions", None),
        ("GET", "/therapist/appointments", None),
        ("GET", "/therapist/availability", None),
        ("GET", "/therapist/referrals", None),
        ("GET", f"/therapist/referrals/{sc.referral}", None),
    ]
    # (404 only for messaging "themself": a student holds the messaging permission)
    await assert_refused(sc.student, attempts, {403, 404}, secrets=(NOTE, FOLLOW))
    export = await _ok(await sc.student.get("/me/privacy/export"))
    assert NOTE not in str(export) and FOLLOW not in str(export)


async def test_student_sees_only_a_therapists_public_profile_and_open_times(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    other = await new_student(client, api_db, world)
    card = await _ok(await other.get(f"/therapists/{sc.therapist.id}"))
    assert set(card) == {
        "id",
        "full_name",
        "specialties",
        "languages",
        "accepting_new_students",
        "next_available_at",
        "on_my_care_team",
        "bio",
    }
    slots = await _ok(await other.get(f"/therapists/{sc.therapist.id}/slots"))
    booked = await _ok(await sc.student.get("/me/appointments"))
    taken = {a["starts_at"] for a in booked}
    assert all(set(x) == {"id", "starts_at", "ends_at", "mode"} for x in slots)
    assert not taken & {x["starts_at"] for x in slots}


async def test_student_cannot_reach_teacher_referrals_rosters_or_class_analytics(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    attempts = _teacher_records(sc) + [
        ("GET", "/teacher/dashboard", None),
        ("GET", "/teacher/classes", None),
        ("GET", "/teacher/referrals", None),
        ("GET", "/teacher/support-requests", None),
        ("GET", f"/teacher/departments/{world.dept_a}/analytics", None),
        (
            "POST",
            "/teacher/referrals",
            {
                "student_id": str(sc.student.id),
                "course_id": str(sc.course),
                "category": "wellbeing_concern",
            },
        ),
    ]
    await assert_refused(sc.student, attempts, {403}, secrets=(REFERRAL,))


# ---- teacher ---------------------------------------------------------------------------------


async def test_teacher_cannot_read_private_data_of_a_student_they_teach(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    attempts = (
        _therapist_reads(sc)
        + _student_records(sc)
        + [
            ("GET", "/me/wellness/mood-entries", None),
            ("GET", "/me/privacy/export", None),
            ("GET", "/me/ai-conversations", None),
            ("GET", "/me/conversations", None),
            ("GET", "/students", None),
        ]
    )
    # 404 only for the one route a teacher holds (their own notifications)
    await assert_refused(sc.teacher, attempts, {403, 404}, secrets=CLINICAL)


async def test_teacher_views_carry_no_clinical_content_or_individual_wellbeing(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """What a teacher may read about a student they teach: a roster name, their own referral
    and the request the student chose to send. Nothing clinical."""
    sc = await build_scene(client, api_db, world)
    roster = await _ok(await sc.teacher.get(f"/teacher/classes/{sc.course}/students"))
    assert roster and all(set(r) == {"student_id", "name"} for r in roster)
    referral = await _ok(await sc.teacher.get(f"/teacher/referrals/{sc.referral}"))
    assert not {"claimed_by", "outcome", "therapist_id", "claimed_at"} & set(referral)
    for path in (
        "/teacher/dashboard",
        "/teacher/classes",
        f"/teacher/classes/{sc.course}",
        f"/teacher/classes/{sc.course}/students",
        f"/teacher/classes/{sc.course}/analytics",
        f"/teacher/classes/{sc.course}/report",
        "/teacher/referrals",
        f"/teacher/referrals/{sc.referral}",
        "/teacher/support-requests",
        "/me/notifications",
    ):
        r = await sc.teacher.get(path)
        assert r.status_code == 200, f"{path}: {r.text}"
        assert not [x for x in CLINICAL if x in r.text], path


async def test_teacher_small_class_figures_are_suppressed(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Nine consenting students: no number at all, so no individual can be singled out."""
    s = await school(client, api_db, world, students=9)
    a = (await _ok(await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics")))["analytics"]
    assert a["state"] == "too_small"
    assert a["weeks"] == [] and a["students_contributing"] is None and a["wellbeing"] == []


async def test_teacher_cannot_reach_another_teachers_class_referral_or_request(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    other_actor = await Builder(api_db, world.password).user(
        world.inst_a, UserRole.TEACHER, department_id=world.dept_a
    )
    await api_db.commit()
    other = await sign_in(client, other_actor, world.password)
    await assert_refused(other, _teacher_records(sc), {404})
    r = await other.post(
        "/teacher/referrals",
        {
            "student_id": str(sc.student.id),
            "course_id": str(sc.course),
            "category": "wellbeing_concern",
        },
    )
    assert r.status_code in (404, 422)


# ---- therapist -------------------------------------------------------------------------------


async def test_therapist_cannot_reach_a_student_not_on_their_caseload(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """A verified colleague in the same institution: the student and every record about them,
    including the author's notes, session, follow-up, alert and appointment, look missing."""
    sc = await build_scene(client, api_db, world)
    colleague = await fresh_therapist(client, api_db, world)
    await assert_refused(colleague, _therapist_reads(sc), {404})
    for path in ("/therapist/students", "/students", "/therapist/alerts", "/me/conversations"):
        r = await colleague.get(path)
        assert r.status_code == 200 and str(sc.student.id) not in r.text, path
    listed = await _ok(await colleague.get(f"/therapist/follow-ups?student_id={sc.student.id}"))
    assert listed == []


async def test_therapist_loses_wellbeing_access_when_the_student_revokes_consent(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    s, t = sc.student, sc.therapist
    assert (await t.get(f"/therapist/students/{s.id}/trends")).status_code == 200
    for scope in ("share_mood_with_care_team", "share_assessments_with_care_team"):
        await _ok(await s.put(f"/me/consents/{scope}", {"granted": False}))
    for path in (
        f"/therapist/students/{s.id}/trends",
        f"/therapist/students/{s.id}/assessments",
        f"/students/{s.id}/mood-entries",
    ):
        assert (await t.get(path)).status_code == 403, path
    profile = await _ok(await t.get(f"/therapist/students/{s.id}"))
    assert profile["sharing"] == {"mood": False, "assessments": False}
    assert profile["latest_mood"] is None and profile["latest_assessment"] is None


async def test_therapist_loses_student_data_when_the_care_link_ends(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    await end_care_link(api_db, sc.pair)
    s = sc.student.id
    await assert_refused(
        sc.therapist,
        [
            ("GET", f"/therapist/students/{s}", None),
            ("GET", f"/therapist/students/{s}/trends", None),
            ("GET", f"/therapist/students/{s}/assessments", None),
            ("GET", f"/students/{s}/mood-entries", None),
            ("GET", f"/students/{s}/therapy-notes", None),
            ("GET", f"/therapist/sessions/{sc.session}/note", None),
            ("PUT", f"/therapist/sessions/{sc.session}/note", {"body": "late"}),
            ("GET", f"/me/conversations/{s}/messages", None),
            ("POST", f"/me/conversations/{s}/messages", {"body": "still there?"}),
            ("GET", f"/therapist/students/{s}/recommendations", None),
        ],
        {404},
        secrets=(DM, NOTE, FOLLOW),
    )


async def test_therapist_conversation_list_hides_an_ended_care_link(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Finding (fixed): after the link ended the therapist's conversation list still showed the
    student's name, the first 90 characters of the last message and the unread count, and the
    dashboard kept counting the student's unread messages."""
    sc = await build_scene(client, api_db, world)
    t = sc.therapist
    before = await _ok(await t.get("/me/conversations"))
    assert [c["other_id"] for c in before] == [str(sc.student.id)]
    await end_care_link(api_db, sc.pair)
    r = await t.get("/me/conversations")
    assert r.status_code == 200 and r.json() == [], r.text
    assert DM not in r.text
    assert (await _ok(await t.get("/therapist/dashboard")))["unread_messages"] == 0
    # the student keeps their own history (ADR 0005)
    mine = await _ok(await sc.student.get("/me/conversations"))
    assert [c["active"] for c in mine] == [False] and mine[0]["last_message_preview"] == DM


async def test_therapist_cannot_change_or_read_a_follow_up_after_the_care_link_ends(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Finding (fixed): PATCH answered 200 with the student's name and the note after the link
    ended, although the list already hid the follow-up."""
    sc = await build_scene(client, api_db, world)
    await end_care_link(api_db, sc.pair)
    for body in ({"status": "done"}, {"note": "changed"}, {}):
        r = await sc.therapist.patch(f"/therapist/follow-ups/{sc.follow_up}", body)
        assert r.status_code == 404, r.text
        assert FOLLOW not in r.text


async def test_therapist_cannot_start_or_close_a_session_after_the_care_link_ends(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Finding (fixed): a new clinical session (and a notification to the student) could be
    created, and an open one closed, for a student no longer on the therapist's care team."""
    sc = await build_scene(client, api_db, world)
    # confirmed, ended an hour ago: still inside the window in which a session may be started
    due = await due_appointment(api_db, sc.pair, starts_in=-dt.timedelta(hours=2))
    await end_care_link(api_db, sc.pair)
    r = await sc.therapist.post(f"/therapist/appointments/{due}/session")
    assert r.status_code == 404, r.text
    r = await sc.therapist.patch(f"/therapist/sessions/{sc.session}", {"status": "completed"})
    assert r.status_code == 404, r.text


async def test_therapist_cannot_reach_another_institutions_student(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    b_therapist = await fresh_therapist(client, api_db, world, other_tenant=True)
    await assert_refused(b_therapist, _therapist_reads(sc), {404})
    b = world.b_student.user_id
    await assert_refused(
        sc.therapist,
        [
            ("GET", f"/therapist/students/{b}", None),
            ("GET", f"/therapist/students/{b}/trends", None),
            ("GET", f"/students/{b}/mood-entries", None),
            ("GET", f"/students/{b}/therapy-notes", None),
            ("GET", f"/me/conversations/{b}/messages", None),
            ("POST", f"/me/conversations/{b}/messages", {"body": "hi"}),
            ("PATCH", f"/appointments/{world.b_appointment}", {"status": "confirmed"}),
            ("POST", f"/therapist/appointments/{world.b_appointment}/session", None),
        ],
        {404},
    )


async def test_therapist_cannot_use_another_therapists_notes_sessions_or_appointments(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Both therapists are linked to the same student: the colleague still cannot read or
    amend the author's note, session, follow-up, appointment or availability."""
    sc = await build_scene(client, api_db, world)
    colleague = await fresh_therapist(client, api_db, world)
    api_db.add(
        m.CareTeamMember(
            institution_id=world.inst_a,
            student_id=sc.student.id,
            therapist_id=colleague.id,
            role=CareRole.SECONDARY,
            starts_at=NOW - dt.timedelta(days=1),
        )
    )
    await api_db.commit()
    await assert_refused(
        colleague,
        [
            ("GET", f"/therapist/sessions/{sc.session}/note", None),
            ("PUT", f"/therapist/sessions/{sc.session}/note", {"body": "amended"}),
            ("PATCH", f"/therapist/sessions/{sc.session}", {"status": "abandoned"}),
            ("PATCH", f"/therapist/follow-ups/{sc.follow_up}", {"status": "done"}),
            ("PATCH", f"/therapist/alerts/{sc.alert}", {"action": "acknowledge"}),
            ("PATCH", f"/appointments/{sc.appointment}", {"status": "cancelled"}),
            (
                "POST",
                f"/therapist/appointments/{sc.appointment}/reschedule",
                {"availability_id": str(sc.free_slot)},
            ),
            ("POST", f"/therapist/appointments/{sc.appointment}/session", None),
            ("DELETE", f"/therapist/availability/{sc.free_slot}", None),
        ],
        {404},
        secrets=(NOTE, FOLLOW),
    )
    notes = await _ok(await colleague.get(f"/students/{sc.student.id}/therapy-notes"))
    assert notes == []
    made = await _ok(await colleague.get(f"/therapist/students/{sc.student.id}/recommendations"))
    assert made == []


# ---- unverified therapist --------------------------------------------------------------------


@pytest.mark.parametrize("state", ["pending", "rejected", "expired"])
async def test_unverified_therapist_with_a_care_link_is_refused_every_student_route(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, state: str
) -> None:
    sc = await build_scene(client, api_db, world)
    row = await api_db.get(m.Therapist, sc.therapist.id)
    assert row is not None
    if state == "expired":
        row.licence_expires_on = dt.date.today() - dt.timedelta(days=1)
    else:
        row.verification_status = VerificationStatus(state)
        row.verified_at = None
    await api_db.commit()
    attempts = [a for a in _therapist_reads(sc) if a[0] != "DELETE"] + [
        ("GET", "/therapist/students", None),
        ("GET", "/students", None),
        ("GET", "/therapist/appointments", None),
        ("GET", "/therapist/sessions", None),
        ("GET", "/therapist/alerts", None),
        ("GET", "/therapist/follow-ups", None),
        ("GET", "/therapist/referrals", None),
        ("GET", "/me/conversations", None),
    ]
    await assert_refused(sc.therapist, attempts, {403})
    dash = await _ok(await sc.therapist.get("/therapist/dashboard"))
    assert dash["can_see_students"] is False and dash["caseload"] == 0


# ---- administrator ---------------------------------------------------------------------------


async def test_admin_cannot_read_therapy_notes_messages_companion_chats_or_wellbeing(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    admin = await fresh_admin(client, api_db, world)
    attempts = (
        _therapist_reads(sc)
        + _student_records(sc)
        + [
            ("GET", "/me/conversations", None),
            ("GET", "/me/ai-conversations", None),
            ("GET", "/me/wellness/mood-entries", None),
            ("GET", "/me/privacy/export", None),
            ("GET", "/students", None),
            ("GET", "/therapist/alerts", None),
        ]
    )
    await assert_refused(admin, attempts, {403, 404}, secrets=CLINICAL)
    for path in (
        f"/admin/users/{sc.student.id}",
        f"/admin/students/{sc.student.id}",
        "/admin/therapist-accounts",
        "/admin/dashboard",
        "/admin/appointments/oversight",
    ):
        r = await admin.get(path)
        assert r.status_code == 200 and not [x for x in CLINICAL if x in r.text], path


async def test_admin_audit_log_does_not_reveal_care_relationships_or_safety_events(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    await _ok(await sc.therapist.get(f"/therapist/students/{sc.student.id}"))
    admin = await fresh_admin(client, api_db, world)
    by_therapist = await _ok(await admin.get(f"/admin/audit?actor_id={sc.therapist.id}&limit=200"))
    by_student = await _ok(await admin.get(f"/admin/audit?actor_id={sc.student.id}&limit=200"))
    clinical = {e["action"] for e in by_therapist + by_student if e["subject_student_id"]}
    assert str(sc.student.id) not in {e["subject_student_id"] for e in by_therapist}, (
        f"care relationship visible through {sorted(clinical)}"
    )
    assert not [e for e in by_student if e["resource_type"] in {"risk_alert", "safety_event"}]
    export = await admin.get(f"/admin/audit/export?actor_id={sc.therapist.id}")
    assert export.status_code == 200 and str(sc.student.id) not in export.text


async def test_admin_cannot_verify_themselves_or_change_their_own_status(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    admin = await fresh_admin(client, api_db, world)
    for body in ({"status": "suspended"}, {"status": "active", "role": "therapist"}):
        assert (await admin.patch(f"/admin/users/{admin.id}", body)).status_code == 403
    r = await admin.patch(f"/admin/therapists/{admin.id}/verification", {"status": "verified"})
    assert r.status_code == 404  # an administrator has no therapist record to verify
    assert (await admin.get(f"/admin/users/{admin.id}")).status_code == 403


# ---- cross-institution, every role -----------------------------------------------------------


@pytest.mark.parametrize("role", ["student", "therapist", "teacher", "admin"])
async def test_cross_institution_actor_cannot_reach_institution_a_records(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, role: str
) -> None:
    sc = await build_scene(client, api_db, world)
    b_actor = getattr(world, f"b_{role}")
    intruder = Session(client, b_actor, await token_for(client, b_actor, world.password))
    s = sc.student.id
    attempts = (
        _student_records(sc)
        + _therapist_reads(sc)
        + _teacher_records(sc)
        + [
            ("GET", f"/therapists/{sc.therapist.id}", None),
            ("GET", f"/therapists/{sc.therapist.id}/slots", None),
            ("POST", "/me/appointments", {"availability_id": str(sc.free_slot)}),
            (
                "POST",
                "/me/teacher-support",
                {"course_id": str(sc.course), "teacher_id": str(sc.teacher.id), "topic": "other"},
            ),
            (
                "POST",
                "/teacher/referrals",
                {
                    "student_id": str(s),
                    "course_id": str(sc.course),
                    "category": "wellbeing_concern",
                },
            ),
            ("GET", f"/teacher/departments/{world.dept_a}/analytics", None),
            ("GET", f"/insights/mood-summary?department_id={world.dept_a}", None),
            ("GET", f"/admin/users/{s}", None),
            ("PATCH", f"/admin/users/{s}", {"status": "suspended"}),
            ("POST", f"/admin/users/{s}/sign-out", None),
            ("GET", f"/admin/students/{s}", None),
            ("PATCH", f"/admin/students/{s}", {"year_of_study": 3}),
            ("PATCH", f"/admin/teachers/{sc.teacher.id}", {"title": "x"}),
            ("PATCH", f"/admin/therapist-accounts/{sc.therapist.id}", {"max_caseload": 2}),
            (
                "PATCH",
                f"/admin/therapists/{sc.therapist.id}/verification",
                {"status": "rejected"},
            ),
            ("GET", f"/admin/courses/{sc.course}", None),
            ("PUT", f"/admin/courses/{sc.course}/students/{s}", None),
            ("PUT", f"/admin/courses/{sc.course}/teachers/{sc.teacher.id}", None),
        ]
    )
    await assert_refused(intruder, attempts, {403, 404})
    # nothing changed in institution A
    me = await _ok(await sc.student.get("/me"))
    assert me["status"] == "active"
    assert (await _ok(await sc.therapist.get("/therapist/profile")))["verification_status"] == (
        "verified"
    )


# ---- mass assignment and self-elevation ------------------------------------------------------

PRIVILEGED_FIELDS = {
    "institution_id",
    "user_id",
    "actor_id",
    "author_id",
    "sender_id",
    "authored_by",
    "assigned_to",
    "claimed_by",
    "verification_status",
    "verified_at",
    "verified_by",
    "permissions",
    "admin_level",
    "deleted_at",
    "password_hash",
    "therapist_id",
    "role",
}
# The one reviewed exception: an administrator creates an invited account of a chosen role in
# their own institution (the institution always comes from the administrator's token).
ALLOWED_PRIVILEGED = {("POST", "/admin/users", "role")}


async def test_no_request_body_accepts_a_privileged_field() -> None:
    """Request models ignore unknown keys, so this is the whole mass-assignment surface."""
    found: set[tuple[str, str, str]] = set()
    for router in ROUTERS:
        for route in router.routes:
            assert isinstance(route, APIRoute)
            for param in route.dependant.body_params:
                model = param.field_info.annotation
                assert isinstance(model, type) and issubclass(model, BaseModel)
                assert model.model_config.get("extra") in (None, "ignore"), model
                for name in set(model.model_fields) & PRIVILEGED_FIELDS:
                    for method in route.methods or ():
                        found.add((method, route.path, name))
    assert found == ALLOWED_PRIVILEGED


async def test_therapist_cannot_verify_themselves_through_profile_or_verification(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world, verified=False)
    r = await t.patch(
        "/therapist/profile",
        {
            "bio": "x",
            "verification_status": "verified",
            "verified_by": str(t.id),
            "institution_id": str(world.inst_b),
            "role": "administrator",
        },
    )
    assert r.status_code == 200 and r.json()["verification_status"] == "pending"
    future = (dt.date.today() + dt.timedelta(days=400)).isoformat()
    r = await t.post(
        "/therapist/verification",
        {
            "licence_number": f"LIC-{uuid.uuid4().hex[:8]}",
            "licence_expires_on": future,
            "status": "verified",
        },
    )
    assert r.status_code == 200 and r.json()["verification_status"] == "pending"
    assert (await t.get("/therapist/students")).status_code == 403
    assert (await t.get("/me")).json()["role"] == "therapist"


async def test_verified_therapist_resubmitting_a_licence_drops_back_to_pending(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world)
    r = await t.post("/therapist/verification", {"licence_number": f"L-{uuid.uuid4().hex[:8]}"})
    assert r.json()["verification_status"] == "pending"
    assert (await t.get("/therapist/students")).status_code == 403


async def test_admin_status_change_ignores_role_and_institution_fields(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    admin = await fresh_admin(client, api_db, world)
    victim = await new_student(client, api_db, world)
    r = await admin.patch(
        f"/admin/users/{victim.id}",
        {"status": "active", "role": "administrator", "institution_id": str(world.inst_b)},
    )
    assert r.status_code == 200 and r.json()["role"] == "student"
    user = await api_db.get(m.User, victim.id)
    assert user is not None
    await api_db.refresh(user)
    assert user.role is UserRole.STUDENT
    assert user.institution_id == world.inst_a


async def test_admin_created_account_stays_in_the_admins_institution_and_starts_invited(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    admin = await fresh_admin(client, api_db, world)
    dept_code = await api_db.scalar(
        select(m.Department.code).where(m.Department.id == world.dept_a)
    )
    r = await admin.post(
        "/admin/users",
        {
            "email": f"made.{uuid.uuid4().hex[:8]}@synthetic.example",
            "full_name": "Made Up",
            "role": "teacher",
            "department_code": dept_code,
            "employee_number": uuid.uuid4().hex[:8],
            "institution_id": str(world.inst_b),
            "status": "active",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "invited"
    user = await api_db.get(m.User, uuid.UUID(r.json()["id"]))
    assert user is not None and user.institution_id == world.inst_a


async def test_student_booking_and_cancel_bodies_cannot_set_status_or_parties(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    other = await new_student(client, api_db, world)
    r = await other.post(
        "/me/appointments",
        {
            "availability_id": str(sc.free_slot),
            "status": "confirmed",
            "student_id": str(sc.student.id),
            "therapist_id": str(world.therapist.user_id),
        },
    )
    assert r.status_code == 201, r.text
    booked = r.json()
    assert booked["status"] == "requested"
    row = await api_db.get(m.Appointment, uuid.UUID(booked["id"]))
    assert row is not None and row.student_id == other.id and row.therapist_id == sc.therapist.id
    r = await other.patch(f"/me/appointments/{booked['id']}", {"status": "confirmed"})
    assert r.status_code == 422
    # and no care link was created by any of it
    assert (await other.get(f"/me/conversations/{sc.therapist.id}/messages")).status_code == 404


async def test_teacher_referral_and_therapist_follow_up_bodies_cannot_name_another_owner(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    classmate = await Builder(api_db, world.password).user(
        world.inst_a, UserRole.STUDENT, department_id=world.dept_a
    )
    api_db.add(
        m.CourseEnrollment(
            institution_id=world.inst_a, course_id=sc.course, student_id=classmate.user_id
        )
    )
    await api_db.commit()
    made_referral = await _ok(
        await sc.teacher.post(
            "/teacher/referrals",
            {
                "student_id": str(classmate.user_id),
                "course_id": str(sc.course),
                "category": "wellbeing_concern",
                "teacher_id": str(world.teacher.user_id),
                "institution_id": str(world.inst_b),
                "status": "closed",
                "claimed_by": str(sc.therapist.id),
            },
        ),
        201,
    )
    referral = await api_db.get(m.Referral, uuid.UUID(made_referral["id"]))
    assert referral is not None and referral.teacher_id == sc.teacher.id
    assert referral.institution_id == world.inst_a and referral.claimed_by is None
    assert made_referral["status"] == "received"

    due = (dt.date.today() + dt.timedelta(days=4)).isoformat()
    made = await _ok(
        await sc.therapist.post(
            "/therapist/follow-ups",
            {
                "student_id": str(sc.student.id),
                "kind": "other",
                "due_on": due,
                "therapist_id": str(world.therapist.user_id),
                "institution_id": str(world.inst_b),
            },
        ),
        201,
    )
    row = await api_db.get(m.FollowUp, uuid.UUID(made["id"]))
    assert row is not None and row.therapist_id == sc.therapist.id
    assert row.institution_id == world.inst_a


async def test_student_goal_patch_cannot_move_the_goal_to_another_student(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    sc = await build_scene(client, api_db, world)
    other = await new_student(client, api_db, world)
    await _ok(
        await sc.student.patch(
            f"/me/goals/{sc.goal}", {"title": "Mine", "student_id": str(other.id)}
        )
    )
    row = await api_db.get(m.WellnessGoal, uuid.UUID(sc.goal))
    assert row is not None and row.student_id == sc.student.id
    assert (await _ok(await other.get("/me/goals"))) == []


async def test_admin_cannot_attach_a_record_to_another_institutions_department(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    admin = await fresh_admin(client, api_db, world)
    victim = await new_student(client, api_db, world)
    dept_b = await api_db.scalar(
        select(m.Department.id).where(m.Department.institution_id == world.inst_b)
    )
    assert dept_b is not None
    r = await admin.patch(f"/admin/students/{victim.id}", {"department_id": str(dept_b)})
    assert r.status_code == 404
    r = await admin.post(
        "/admin/courses",
        {
            "department_id": str(dept_b),
            "code": "XB1",
            "title": "x",
            "term": "2026-autumn",
            "credits": 3,
        },
    )
    assert r.status_code == 404


async def test_admin_cannot_claim_another_institutions_email_domain(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Finding (fixed): registration picks the institution by e-mail domain and refuses a
    domain two institutions claim. An administrator could claim another institution's domain,
    or a bare suffix such as ``edu``, and so block (or capture) everyone else's sign-ups."""
    a_admin = await fresh_admin(client, api_db, world)
    b_admin = await fresh_admin(client, api_db, world, other_tenant=True)
    domain = f"college-{uuid.uuid4().hex[:8]}.example"
    before_a = (await _ok(await a_admin.get("/admin/config")))["email_domains"]
    before_b = (await _ok(await b_admin.get("/admin/config")))["email_domains"]
    try:
        await _ok(await b_admin.patch("/admin/config", {"email_domains": [*before_b, domain]}))
        for claim in (domain, f"dept.{domain}", domain.split(".", 1)[1], "edu", "EXAMPLE"):
            r = await a_admin.patch("/admin/config", {"email_domains": [*before_a, claim]})
            assert r.status_code in (409, 422), f"{claim}: {r.status_code} {r.text}"
        after = (await _ok(await a_admin.get("/admin/config")))["email_domains"]
        assert after == before_a
    finally:
        await b_admin.patch("/admin/config", {"email_domains": before_b})


# ---- accounts that changed -------------------------------------------------------------------


@pytest.mark.parametrize("status", ["suspended", "deactivated"])
async def test_suspended_or_deactivated_account_cannot_keep_using_its_token(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, status: str
) -> None:
    sc = await build_scene(client, api_db, world)
    admin = await fresh_admin(client, api_db, world)
    for who, path in (
        (sc.therapist, f"/therapist/students/{sc.student.id}"),
        (sc.student, "/me/wellness/mood-entries"),
        (sc.teacher, f"/teacher/classes/{sc.course}/students"),
    ):
        assert (await who.get(path)).status_code == 200
        await _ok(await admin.patch(f"/admin/users/{who.id}", {"status": status}))
        r = await who.get(path)
        assert r.status_code == 401, f"{who.actor.role} {path}: {r.status_code}"


async def test_role_change_or_deletion_invalidates_existing_tokens(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    promoted = await new_student(client, api_db, world)
    deleted = await new_student(client, api_db, world)
    assert (await promoted.get("/me")).status_code == 200
    user = await api_db.get(m.User, promoted.id)
    gone = await api_db.get(m.User, deleted.id)
    profile = await api_db.get(m.Student, promoted.id)
    assert user is not None and gone is not None and profile is not None
    # a role change (made in the database: no route changes a role) swaps the role profile
    await api_db.delete(profile)
    await api_db.flush()
    user.role = UserRole.ADMINISTRATOR
    api_db.add(m.Administrator(user_id=user.id, institution_id=user.institution_id))
    gone.deleted_at = dt.datetime.now(dt.UTC)
    await api_db.commit()
    assert (await promoted.get("/me")).status_code == 401
    assert (await promoted.get("/admin/users")).status_code == 401
    assert (await deleted.get("/me")).status_code == 401


async def test_reactivated_account_must_sign_in_again(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    admin = await fresh_admin(client, api_db, world)
    s = await new_student(client, api_db, world)
    await _ok(await admin.patch(f"/admin/users/{s.id}", {"status": "suspended"}))
    await _ok(await admin.patch(f"/admin/users/{s.id}", {"status": "active"}))
    assert (await s.get("/me")).status_code == 401  # the old session was revoked for good
    row = await api_db.get(m.User, s.id)
    assert row is not None
    await api_db.refresh(row)
    assert row.status is UserStatus.ACTIVE


# ---- 'not found' must not reveal existence ---------------------------------------------------


def _shape(r: httpx.Response) -> tuple[int, Any, Any]:
    body = r.json()
    return r.status_code, body.get("title"), body.get("detail")


async def test_hidden_records_answer_exactly_like_missing_ones(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """For every id-addressed route, a real record the caller may not see and an id that does
    not exist give the same status, title and detail."""
    sc = await build_scene(client, api_db, world)
    student = await new_student(client, api_db, world)
    colleague = await fresh_therapist(client, api_db, world)
    other_actor = await Builder(api_db, world.password).user(
        world.inst_a, UserRole.TEACHER, department_id=world.dept_a
    )
    await api_db.commit()
    teacher = await sign_in(client, other_actor, world.password)
    b_admin = await fresh_admin(client, api_db, world, other_tenant=True)
    cases: list[tuple[Session, list[Attempt]]] = [
        (student, _student_records(sc)),
        (colleague, _therapist_reads(sc)),
        (teacher, _teacher_records(sc)),
        (
            b_admin,
            [
                ("GET", f"/admin/users/{sc.student.id}", None),
                ("GET", f"/admin/students/{sc.student.id}", None),
                ("GET", f"/admin/courses/{sc.course}", None),
            ],
        ),
    ]
    real_ids = {
        str(x)
        for x in (
            sc.goal,
            sc.recommendation,
            sc.appointment,
            sc.conversation,
            sc.session,
            sc.follow_up,
            sc.notification,
            sc.alert,
            sc.ask,
            sc.referral,
            sc.free_slot,
            sc.course,
            sc.student.id,
            sc.therapist.id,
        )
    }
    compared = 0
    for who, attempts in cases:
        for method, path, body in attempts:
            ghost = path
            for real in real_ids:
                ghost = ghost.replace(real, str(RANDOM))
            if ghost == path:
                continue
            hidden = await _attempt(who, method, path, body)
            missing = await _attempt(who, method, ghost, body)
            assert _shape(hidden) == _shape(missing), f"{method} {path}"
            compared += 1
    assert compared > 40
