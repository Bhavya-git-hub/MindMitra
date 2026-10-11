"""Authorization for every student-portal route.

Each route is called by every role (and anonymously). Only the roles that should reach it get
past the guard; everyone else is refused before any data is touched. Cross-user and
cross-institution attempts on real records are covered next to each feature; the cases here are
the role matrix plus the "teachers, admins and therapists never see student data" guarantees.
"""

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from tests.api_helpers import call, token_for
from tests.api_world import World
from tests.student_helpers import new_student, sleep_body

pytestmark = pytest.mark.asyncio

ROLES = ("student", "therapist", "teacher", "admin")
FAKE = uuid.UUID(int=1)

# (method, path, json body, roles allowed past the guard)
STUDENT_ONLY = {"student"}
STUDENT_AND_THERAPIST = {"student", "therapist"}
ROUTES: list[tuple[str, str, Any, set[str]]] = [
    ("POST", "/me/check-ins", {"mood_score": 3}, STUDENT_ONLY),
    ("POST", "/me/wellness/mood-entries", {"mood_score": 3}, STUDENT_ONLY),
    ("GET", "/me/wellness/stress-entries", None, STUDENT_ONLY),
    ("POST", "/me/wellness/stress-entries", {"stress_level": 2}, STUDENT_ONLY),
    ("GET", "/me/wellness/sleep-entries", None, STUDENT_ONLY),
    ("PUT", "/me/wellness/sleep-entries", sleep_body(), STUDENT_ONLY),
    ("GET", "/me/wellness/summary", None, STUDENT_ONLY),
    ("GET", "/me/wellness/trends", None, STUDENT_ONLY),
    ("GET", "/me/wellness/analytics", None, STUDENT_ONLY),
    ("GET", "/me/dashboard", None, STUDENT_ONLY),
    ("GET", "/me/wellness/assessment", None, STUDENT_ONLY),
    ("GET", "/me/wellness/assessments", None, STUDENT_ONLY),
    (
        "POST",
        "/me/wellness/assessments",
        {"responses": {f"q{i}": 3 for i in range(1, 6)}},
        STUDENT_ONLY,
    ),
    ("GET", "/me/goals", None, STUDENT_ONLY),
    ("POST", "/me/goals", {"title": "g", "category": "sleep"}, STUDENT_ONLY),
    ("PATCH", f"/me/goals/{FAKE}", {"status": "paused"}, STUDENT_ONLY),
    ("GET", "/me/recommendations", None, STUDENT_ONLY),
    ("POST", "/me/recommendations/refresh", None, STUDENT_ONLY),
    ("PATCH", f"/me/recommendations/{FAKE}", {"status": "viewed"}, STUDENT_ONLY),
    ("GET", "/me/recommendations/history", None, STUDENT_ONLY),
    ("PUT", f"/me/recommendations/{FAKE}/feedback", {"rating": "helpful"}, STUDENT_ONLY),
    ("DELETE", f"/me/recommendations/{FAKE}/feedback", None, STUDENT_ONLY),
    ("GET", "/me/recommendations/preferences", None, STUDENT_ONLY),
    ("PATCH", "/me/recommendations/preferences", {"use_indicators": False}, STUDENT_ONLY),
    ("GET", "/therapists", None, STUDENT_ONLY),
    ("GET", f"/therapists/{FAKE}", None, STUDENT_ONLY),
    ("GET", f"/therapists/{FAKE}/slots", None, STUDENT_ONLY),
    ("POST", "/me/appointments", {"availability_id": str(FAKE)}, STUDENT_ONLY),
    ("PATCH", f"/me/appointments/{FAKE}", {"status": "cancelled"}, STUDENT_ONLY),
    # messaging is the student/therapist pair (a therapist's side is tested in the therapist suite)
    ("GET", "/me/conversations", None, STUDENT_AND_THERAPIST),
    ("GET", f"/me/conversations/{FAKE}/messages", None, STUDENT_AND_THERAPIST),
    ("POST", f"/me/conversations/{FAKE}/messages", {"body": "hi"}, STUDENT_AND_THERAPIST),
    ("POST", f"/me/conversations/{FAKE}/read", None, STUDENT_AND_THERAPIST),
    ("GET", "/me/consents", None, STUDENT_ONLY),
    ("PUT", "/me/consents/email_notifications", {"granted": True}, STUDENT_ONLY),
    ("GET", "/me/privacy/access-history", None, STUDENT_ONLY),
    ("GET", "/me/privacy/export", None, STUDENT_ONLY),
    ("POST", "/me/support-requests", {}, STUDENT_ONLY),
    ("GET", "/me/safety/resources", None, STUDENT_ONLY),
    # vetted content is for students and the therapists who recommend it
    ("GET", "/resources", None, {"student", "therapist"}),
    ("GET", f"/resources/{FAKE}", None, {"student", "therapist"}),
]


def _id(route: tuple[str, str, Any, set[str]]) -> str:
    return f"{route[0]} {route[1].replace(str(FAKE), '{id}')}"


@pytest.mark.parametrize("route", ROUTES, ids=_id)
@pytest.mark.parametrize("role", ROLES)
async def test_role_matrix(
    client: httpx.AsyncClient, world: World, role: str, route: tuple[str, str, Any, set[str]]
) -> None:
    method, path, body, allowed = route
    actor = getattr(world, role)
    token = await token_for(client, actor, world.password)
    r = await call(client, method, path, token=token, json=body)
    if role in allowed:
        # past the guard: success or a clean "not found", never 401/403
        assert r.status_code not in (401, 403), f"{role} {method} {path}: {r.status_code} {r.text}"
        assert r.status_code < 500, r.text
    else:
        assert r.status_code == 403, f"{role} {method} {path}: {r.status_code} {r.text}"
        assert r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("route", ROUTES, ids=_id)
async def test_anonymous_is_refused(
    client: httpx.AsyncClient, route: tuple[str, str, Any, set[str]]
) -> None:
    method, path, body, _ = route
    r = await call(client, method, path, json=body)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


async def test_tampered_token_is_refused(client: httpx.AsyncClient, world: World) -> None:
    token = await token_for(client, world.student, world.password)
    r = await call(client, "GET", "/me/dashboard", token=token[:-3] + "abc")
    assert r.status_code == 401


# ---- nobody else sees a student's records through the student routes ------------------------


async def test_only_the_owner_ever_receives_a_students_records(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    await a.post("/me/check-ins", {"mood_score": 1, "note": "A-only-secret", "stress_level": 5})
    await a.post("/me/goals", {"title": "A-only-goal", "category": "sleep"})
    await a.post("/me/wellness/assessments", {"responses": {f"q{i}": 0 for i in range(1, 6)}})
    await a.post("/me/support-requests", {"message": "A-only-help"})
    await a.put("/me/wellness/sleep-entries", sleep_body())

    readers = [
        "/me/dashboard",
        "/me/wellness/summary",
        "/me/wellness/trends?days=30",
        "/me/wellness/analytics?weeks=8",
        "/me/wellness/mood-entries",
        "/me/wellness/stress-entries",
        "/me/wellness/sleep-entries",
        "/me/wellness/assessments",
        "/me/goals",
        "/me/recommendations?include_closed=true",
        "/me/recommendations/history",
        "/me/recommendations/preferences",
        "/me/appointments",
        "/me/conversations",
        "/me/privacy/access-history",
        "/me/privacy/export",
    ]
    for path in readers:
        text = (await b.get(path)).text
        assert "A-only" not in text, path
        body = (await b.get(path)).json()
        if path.startswith("/me/wellness/trends"):
            assert all(p["mood"] is None for p in body["points"])
        elif path == "/me/dashboard":
            assert body["mood"]["today"] is None and body["wellbeing"] is None
        elif isinstance(body, list):
            assert body == [], path


async def test_non_students_cannot_read_student_data_by_any_known_route(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Teachers and administrators have no route to wellness or messages at all; therapists
    only reach the consent-gated, care-team-gated views that already have their own tests."""
    s = await new_student(client, api_db, world)
    await s.post("/me/check-ins", {"mood_score": 2, "note": "stu-private"})
    for role in ("teacher", "admin", "therapist"):
        token = await token_for(client, getattr(world, role), world.password)
        for path in (
            "/me/dashboard",
            "/me/wellness/mood-entries",
            "/me/goals",
            "/me/privacy/export",
            f"/me/conversations/{s.id}/messages",
        ):
            r = await call(client, "GET", path, token=token)
            if role == "therapist" and path.startswith("/me/conversations"):
                # the messaging API is shared; a therapist with no link to s sees nothing
                assert r.status_code in (403, 404), (role, path)
            else:
                assert r.status_code == 403, (role, path)
            assert "stu-private" not in r.text
        r = await call(client, "GET", f"/students/{s.id}/mood-entries", token=token)
        assert r.status_code in (403, 404)  # therapists: not on the care team; others: no role
        assert "stu-private" not in r.text


async def test_ids_in_paths_never_widen_access(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Passing someone else's id (or the owner's id) in a path or body gets the caller nothing."""
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    goal = (await a.post("/me/goals", {"title": "mine", "category": "sleep"})).json()
    # student_id smuggled into bodies is ignored (the schemas have no such field)
    r = await b.post("/me/goals", {"title": "b's", "category": "sleep", "student_id": str(a.id)})
    assert r.status_code == 201
    row = await api_db.get(m.WellnessGoal, r.json()["id"])
    assert row is not None and row.student_id == b.id
    r = await b.post(
        "/me/check-ins",
        {"mood_score": 3, "student_id": str(a.id), "institution_id": str(world.inst_b)},
    )
    assert r.status_code == 201
    mood = await api_db.get(m.MoodEntry, r.json()["mood"]["id"])
    assert mood is not None and mood.student_id == b.id and mood.institution_id == world.inst_a
    assert goal["id"] not in {g["id"] for g in (await b.get("/me/goals")).json()}


async def test_sensitive_responses_are_not_cacheable(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    for path in ("/me/dashboard", "/me/privacy/export", "/me/wellness/mood-entries"):
        r = await s.get(path)
        assert r.headers["cache-control"] == "no-store", path


async def test_error_bodies_do_not_echo_private_input(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.post("/me/check-ins", {"mood_score": 99, "note": "do-not-echo-this"})
    assert r.status_code == 422 and "do-not-echo-this" not in r.text
    r = await s.post(f"/me/conversations/{uuid.uuid4()}/messages", {"body": "do-not-echo-this"})
    assert r.status_code == 404 and "do-not-echo-this" not in r.text
    assert json.loads(r.text)["status"] == 404


async def test_student_cannot_use_therapist_or_admin_routes(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    for method, path, body in (
        ("GET", "/students", None),
        ("GET", f"/students/{s.id}/therapy-notes", None),
        ("GET", "/therapist/appointments", None),
        ("PATCH", f"/appointments/{world.appointment}", {"status": "confirmed"}),
        ("GET", "/admin/users", None),
        ("GET", "/admin/audit", None),
        ("GET", "/insights/mood-summary", None),
    ):
        r = await call(client, method, path, token=s.token, json=body)
        assert r.status_code == 403, (method, path)


async def test_the_seeded_student_still_reads_only_their_own_notes_of_record(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    """Regression guard for the existing therapy-note rules after adding student routes."""
    token = await token_for(client, world.student, world.password)
    r = await call(client, "GET", f"/students/{world.student.user_id}/therapy-notes", token=token)
    assert r.status_code == 403
    count = await api_db.scalar(
        select(m.TherapyNote.id).where(m.TherapyNote.author_id == world.student.user_id).limit(1)
    )
    assert count is None
