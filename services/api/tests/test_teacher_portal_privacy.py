"""Teachers cannot reach confidential student information.

Three independent proofs:

1. **Map.** Every route a teacher's permissions reach is listed here by hand. A route added
   later that a teacher can reach fails this test until someone decides it is safe.
2. **Refusal.** Every other route answers a teacher with 403, whatever ids are named.
3. **Content.** Real confidential records (therapy note, private journal, AI conversation, private
   message, mood note, safety alert) are planted for students in a teacher's own class. Every
   route the teacher can reach is then read, and none of the planted text, nor any student who
   is not on a roster, referral or request the teacher is entitled to, appears anywhere.
"""

import datetime as dt
import json
import re
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AUTHZ_MARKER
from app.api.main import API_PREFIX, PUBLIC_ROUTES, ROUTERS
from app.domain.auth.permissions import ROLE_PERMISSIONS, Permission, Role
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AIConversationStatus,
    AIMessageRole,
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    ConsentScope,
    TherapySessionStatus,
    UserRole,
)
from app.infrastructure.db.ids import uuid7
from tests.api_helpers import call
from tests.api_world import NOW, Actor, Builder, World
from tests.student_helpers import sign_in
from tests.teacher_helpers import add_week, school

pytestmark = pytest.mark.asyncio

FAKE = uuid.UUID(int=7)

# ---- 1. the map -----------------------------------------------------------------------------

TEACHER_ROUTES = {
    ("POST", "/auth/logout"),
    ("GET", "/me"),
    # their own notifications (never anyone else's)
    ("GET", "/me/notifications"),
    ("GET", "/me/notifications/unread-count"),
    ("POST", "/me/notifications/{notification_id}/read"),
    ("POST", "/me/notifications/read-all"),
    ("GET", "/insights/mood-summary"),
    ("GET", "/teacher/dashboard"),
    ("GET", "/teacher/classes"),
    ("GET", "/teacher/classes/{course_id}"),
    ("GET", "/teacher/classes/{course_id}/students"),
    ("GET", "/teacher/classes/{course_id}/analytics"),
    ("GET", "/teacher/classes/{course_id}/report"),
    ("GET", "/teacher/classes/{course_id}/report.csv"),
    ("GET", "/teacher/departments/{department_id}/analytics"),
    ("GET", "/teacher/departments/{department_id}/report"),
    ("GET", "/teacher/departments/{department_id}/report.csv"),
    ("POST", "/teacher/referrals"),
    ("GET", "/teacher/referrals"),
    ("GET", "/teacher/referrals/{referral_id}"),
    ("GET", "/teacher/support-requests"),
    ("POST", "/teacher/support-requests/{request_id}/acknowledge"),
    ("POST", "/teacher/support-requests/{request_id}/close"),
    ("GET", "/teacher/resources"),
    ("GET", "/teacher/resources/{resource_id}"),
}


def _routes() -> Iterator[tuple[str, str, APIRoute]]:
    for router in ROUTERS:
        for route in router.routes:
            assert isinstance(route, APIRoute)
            for method in sorted(route.methods or ()):
                if method != "HEAD":
                    yield method, route.path, route


def _requirements(route: APIRoute) -> list[str]:
    found: list[str] = []

    def walk(dependant: Any) -> None:
        call = getattr(dependant, "call", None)
        if call is not None and hasattr(call, AUTHZ_MARKER):
            found.append(getattr(call, AUTHZ_MARKER))
        for sub in dependant.dependencies:
            walk(sub)

    walk(route.dependant)
    return found


def _teacher_may_pass(route: APIRoute) -> bool:
    for requirement in _requirements(route):
        if requirement == "authenticated":
            continue
        wanted = [Permission(p) for p in requirement.split(":", 1)[1].split(",") if p]
        if not all(p in ROLE_PERMISSIONS[Role.TEACHER] for p in wanted):
            return False
    return True


def _is_public(method: str, path: str) -> bool:
    return (method, API_PREFIX + path) in PUBLIC_ROUTES


async def test_the_routes_a_teacher_can_reach_are_exactly_the_reviewed_ones() -> None:
    reachable = {
        (method, path)
        for method, path, route in _routes()
        if not _is_public(method, path) and _teacher_may_pass(route)
    }
    assert reachable == TEACHER_ROUTES


async def test_no_teacher_route_is_one_that_reads_a_students_private_records() -> None:
    private = (
        "therapy-notes", "mood-entries", "journal", "ai-conversations", "conversations",
        "trends", "assessments", "privacy", "wellness", "sessions", "alerts",
    )  # fmt: skip
    for _, path in TEACHER_ROUTES:
        assert not any(word in path for word in private), path


# ---- 2. refusal -----------------------------------------------------------------------------

FORBIDDEN = [
    (method, path)
    for method, path, route in _routes()
    if not _is_public(method, path) and not _teacher_may_pass(route)
]


def _fill(path: str) -> str:
    return API_PREFIX + re.sub(r"\{[^}]+\}", str(FAKE), path)


@pytest.mark.parametrize(("method", "path"), FORBIDDEN, ids=[f"{m} {p}" for m, p in FORBIDDEN])
async def test_every_other_route_refuses_a_teacher(
    client: httpx.AsyncClient, world: World, method: str, path: str
) -> None:
    from tests.api_helpers import token_for

    token = await token_for(client, world.teacher, world.password)
    r = await client.request(
        method, "https://testserver" + _fill(path), headers={"Authorization": f"Bearer {token}"},
        json={} if method in {"POST", "PUT", "PATCH"} else None,
    )  # fmt: skip
    assert r.status_code == 403, f"{method} {path}: {r.status_code} {r.text}"


def json_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from json_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from json_keys(inner)


# ---- 3. content -----------------------------------------------------------------------------

SENTINELS = {
    "mood": "SENTINEL-MOOD-NOTE-31337",
    "journal": "SENTINEL-JOURNAL-ENTRY-31337",
    "ai": "SENTINEL-AI-CHAT-31337",
    "dm": "SENTINEL-PRIVATE-MESSAGE-31337",
    "therapy": "SENTINEL-THERAPY-NOTE-31337",
    "alert": "SENTINEL-ALERT-EXCERPT-31337",
}


async def plant(
    db: AsyncSession, world: World, student: Actor, therapist: Actor, n: int = 0
) -> dict[str, uuid.UUID]:
    """Confidential records for one student, including ones they chose to share with their
    therapist. Returns ids a curious teacher might try."""
    b = Builder(db, world.password)
    inst = world.inst_a
    await add_week(db, inst, student, 1, note=SENTINELS["mood"], stress=None, sleep_hours=None)
    db.add(
        m.JournalEntry(
            institution_id=inst,
            student_id=student.user_id,
            title="Private",
            body=SENTINELS["journal"],
        )
    )
    convo = m.AIConversation(
        id=uuid7(),
        institution_id=inst,
        student_id=student.user_id,
        status=AIConversationStatus.ACTIVE,
        started_at=NOW,
    )
    db.add(convo)
    await db.flush()
    db.add(
        m.AIMessage(
            conversation_id=convo.id, seq=1, role=AIMessageRole.USER, content=SENTINELS["ai"]
        )
    )
    await b.care_link(inst, student, therapist)
    for scope in (
        ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
        ConsentScope.SHARE_ASSESSMENTS_WITH_CARE_TEAM,
    ):
        db.add(
            m.Consent(
                institution_id=inst,
                user_id=student.user_id,
                scope=scope,
                policy_version="test",
                granted_at=NOW - dt.timedelta(days=5),
            )
        )
    db.add(
        m.Message(
            institution_id=inst,
            student_id=student.user_id,
            therapist_id=therapist.user_id,
            sender_id=therapist.user_id,
            body=SENTINELS["dm"],
        )
    )
    appointment = await b.appointment(inst, student, therapist, days_ahead=-3 - n)
    session = m.TherapySession(
        id=uuid7(),
        institution_id=inst,
        appointment_id=appointment,
        student_id=student.user_id,
        therapist_id=therapist.user_id,
        status=TherapySessionStatus.COMPLETED,
        started_at=NOW - dt.timedelta(days=3),
        ended_at=NOW - dt.timedelta(days=3) + dt.timedelta(minutes=50),
    )
    db.add(session)
    await db.flush()
    note = m.TherapyNote(
        id=uuid7(),
        institution_id=inst,
        session_id=session.id,
        author_id=therapist.user_id,
        body=SENTINELS["therapy"],
    )
    db.add(note)
    alert = m.RiskAlert(
        id=uuid7(),
        institution_id=inst,
        student_id=student.user_id,
        source=AlertSource.HELP_BUTTON,
        detector=AlertDetector.HUMAN,
        category=AlertCategory.ACUTE_DISTRESS,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.OPEN,
        requires_human=True,
        excerpt=SENTINELS["alert"],
        sla_ack_due_at=NOW + dt.timedelta(minutes=15),
    )
    db.add(alert)
    await db.commit()
    return {"session": session.id, "note": note.id, "alert": alert.id, "convo": convo.id}


async def test_planted_confidential_records_never_reach_a_teacher(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    therapist = await Builder(api_db, world.password).user(world.inst_a, UserRole.THERAPIST)
    await api_db.commit()
    ids = {}
    for n, student in enumerate(s.students[:3]):
        ids = await plant(api_db, world, student, therapist, n)

    # a student who asks this teacher for help, and a referral the teacher raises
    asker = await sign_in(client, s.students[0], world.password)
    sent = await asker.post(
        "/me/teacher-support",
        {"course_id": str(s.course_id), "teacher_id": str(s.teacher.id), "topic": "wellbeing_chat"},
    )
    assert sent.status_code == 201, sent.text
    referred = await s.teacher.post(
        "/teacher/referrals",
        {
            "student_id": str(s.students[1].user_id),
            "course_id": str(s.course_id),
            "category": "wellbeing_concern",
            "urgency": "routine",
        },
    )
    assert referred.status_code == 201, referred.text

    resource = (await s.teacher.get("/teacher/resources")).json()[0]["id"]
    templates = {
        "course_id": str(s.course_id),
        "department_id": str(s.dept_id),
        "referral_id": referred.json()["id"],
        "request_id": sent.json()["id"],
        "resource_id": resource,
    }
    # teacher-visible routes that may legitimately name people, and exactly whom
    entitled = {
        "/teacher/classes/{course_id}/students": {x.user_id for x in s.students},
        "/teacher/referrals": {s.students[1].user_id},
        "/teacher/referrals/{referral_id}": {s.students[1].user_id},
        "/teacher/support-requests": {s.students[0].user_id},
        "/teacher/support-requests/{request_id}/acknowledge": {s.students[0].user_id},
        "/teacher/support-requests/{request_id}/close": {s.students[0].user_id},
        "/teacher/dashboard": set(),
    }
    everyone = {x.user_id for x in s.students} | {
        world.student.user_id,
        world.other_student.user_id,
    }
    emails = {x.user_id: x.email for x in s.students}

    crawled = 0
    for method, path in sorted(TEACHER_ROUTES):
        reads = method == "GET"
        if not reads and path != "/teacher/support-requests/{request_id}/acknowledge":
            continue  # logout, creating a referral and closing a request are exercised elsewhere
        url = path
        for key, value in templates.items():
            url = url.replace("{" + key + "}", value)
        r = await s.teacher.get(url) if method == "GET" else await s.teacher.post(url)
        assert r.status_code == 200, f"{method} {path}: {r.status_code} {r.text}"
        crawled += 1
        text = r.text
        for label, secret in SENTINELS.items():
            assert secret not in text, f"{label} text leaked through {path}"
        allowed_people = entitled.get(path, set())
        for uid in everyone - allowed_people:
            assert str(uid) not in text, f"{path} names a student the teacher is not entitled to"
            if uid in emails:
                assert emails[uid] not in text
        for uid in allowed_people & set(emails):
            assert emails[uid] not in text  # even entitled routes never carry contact details
        if "json" in r.headers["content-type"]:
            bad = [
                k
                for k in json_keys(r.json())
                if re.search(r"diagnos|therapy|journal|alert|conversation", k)
            ]
            assert bad == [], (path, bad)
    assert crawled >= 15
    assert ids


async def test_a_teacher_cannot_open_the_confidential_records_directly(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    therapist = await Builder(api_db, world.password).user(world.inst_a, UserRole.THERAPIST)
    await api_db.commit()
    ids = await plant(api_db, world, s.students[0], therapist)
    sid = s.students[0].user_id
    attempts = [
        ("GET", f"/students/{sid}/therapy-notes"),
        ("GET", f"/students/{sid}/mood-entries"),
        ("GET", f"/therapist/sessions/{ids['session']}/note"),
        ("PUT", f"/therapist/sessions/{ids['session']}/note"),
        ("GET", f"/therapist/students/{sid}"),
        ("GET", f"/therapist/students/{sid}/trends"),
        ("GET", f"/therapist/students/{sid}/assessments"),
        ("GET", "/therapist/alerts"),
        ("PATCH", f"/therapist/alerts/{ids['alert']}"),
        ("GET", f"/me/conversations/{sid}/messages"),
        ("GET", "/me/conversations"),
        ("GET", "/me/ai-conversations"),
        ("GET", "/me/wellness/mood-entries"),
        ("GET", "/me/privacy/export"),
        ("GET", "/me/privacy/access-history"),
        ("GET", "/students"),
        ("GET", "/admin/audit"),
    ]
    for method, path in attempts:
        r = await call(
            client, method, path, token=s.teacher.token,
            json={} if method in {"PUT", "PATCH"} else None,
        )  # fmt: skip
        assert r.status_code == 403, f"{method} {path}: {r.status_code}"
        text = r.text
        assert not any(secret in text for secret in SENTINELS.values())


async def test_a_student_who_asks_a_teacher_for_help_shares_only_that_message(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Explicit authorization is narrow: it covers the words the student sent, nothing more,
    even for a student who also shares everything with their therapist."""
    s = await school(client, api_db, world, students=12)
    therapist = await Builder(api_db, world.password).user(world.inst_a, UserRole.THERAPIST)
    await api_db.commit()
    await plant(api_db, world, s.students[0], therapist)
    asker = await sign_in(client, s.students[0], world.password)
    await asker.post(
        "/me/teacher-support",
        {
            "course_id": str(s.course_id),
            "teacher_id": str(s.teacher.id),
            "topic": "workload",
            "message": "I am behind on the project.",
        },
    )
    inbox = (await s.teacher.get("/teacher/support-requests")).json()
    assert len(inbox) == 1
    assert set(inbox[0]) == {
        "id", "course_id", "course_code", "course_title", "teacher_name", "student_name",
        "topic", "topic_label", "message", "status", "status_label", "created_at",
    }  # fmt: skip
    assert inbox[0]["message"] == "I am behind on the project."
    assert not any(secret in json.dumps(inbox) for secret in SENTINELS.values())


async def test_a_group_figure_cannot_be_narrowed_to_a_person(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Nine students agreed, one did not: asking for any window, class or department view
    still yields nothing about the nine, and the one is never counted."""
    s = await school(client, api_db, world, students=10, consenting=9)
    for weeks in (4, 8, 12):
        a = (await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics?weeks={weeks}")).json()
        assert a["analytics"]["state"] == "too_small" and a["analytics"]["weeks"] == []
        d = (
            await s.teacher.get(f"/teacher/departments/{s.dept_id}/analytics?weeks={weeks}")
        ).json()
        assert d["analytics"]["state"] == "too_small" and d["analytics"]["weeks"] == []
    csv = (await s.teacher.get(f"/teacher/classes/{s.course_id}/report.csv")).text
    assert len(csv.strip().splitlines()) == 1  # header only
    legacy = (await s.teacher.get(f"/insights/mood-summary?department_id={s.dept_id}")).json()
    assert legacy["suppressed"] is True and legacy["average_mood"] is None
