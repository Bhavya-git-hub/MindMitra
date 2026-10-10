"""Every teacher-portal route, tried by every role. The permission guard must refuse the wrong
roles before any record is read (record-level rules are tested next to each feature)."""

import uuid
from typing import Any

import httpx
import pytest

from tests.api_helpers import call, token_for
from tests.api_world import World

pytestmark = pytest.mark.asyncio

ROLES = ("student", "therapist", "teacher", "admin")
FAKE = uuid.UUID(int=1)
TEACHER = {"teacher"}
REFERRAL = {
    "student_id": str(FAKE),
    "course_id": str(FAKE),
    "category": "wellbeing_concern",
    "urgency": "routine",
}
ASK = {"course_id": str(FAKE), "teacher_id": str(FAKE), "topic": "extension"}

ROUTES: list[tuple[str, str, Any, set[str]]] = [
    ("GET", "/teacher/dashboard", None, TEACHER),
    ("GET", "/teacher/classes", None, TEACHER),
    ("GET", f"/teacher/classes/{FAKE}", None, TEACHER),
    ("GET", f"/teacher/classes/{FAKE}/students", None, TEACHER),
    ("GET", f"/teacher/classes/{FAKE}/analytics", None, TEACHER),
    ("GET", f"/teacher/classes/{FAKE}/report", None, TEACHER),
    ("GET", f"/teacher/classes/{FAKE}/report.csv", None, TEACHER),
    ("GET", f"/teacher/departments/{FAKE}/analytics", None, TEACHER),
    ("GET", f"/teacher/departments/{FAKE}/report", None, TEACHER),
    ("GET", f"/teacher/departments/{FAKE}/report.csv", None, TEACHER),
    ("POST", "/teacher/referrals", REFERRAL, TEACHER),
    ("GET", "/teacher/referrals", None, TEACHER),
    ("GET", f"/teacher/referrals/{FAKE}", None, TEACHER),
    ("GET", "/teacher/support-requests", None, TEACHER),
    ("POST", f"/teacher/support-requests/{FAKE}/acknowledge", None, TEACHER),
    ("POST", f"/teacher/support-requests/{FAKE}/close", None, TEACHER),
    ("GET", "/teacher/resources", None, {"teacher", "admin"}),
    ("GET", f"/teacher/resources/{FAKE}", None, {"teacher", "admin"}),
    ("GET", "/me/teacher-support/options", None, {"student"}),
    ("GET", "/me/teacher-support", None, {"student"}),
    ("POST", "/me/teacher-support", ASK, {"student"}),
    ("POST", f"/me/teacher-support/{FAKE}/withdraw", None, {"student"}),
    ("GET", "/therapist/referrals", None, {"therapist"}),
    ("GET", f"/therapist/referrals/{FAKE}", None, {"therapist"}),
    ("POST", f"/therapist/referrals/{FAKE}/claim", None, {"therapist"}),
    ("POST", f"/therapist/referrals/{FAKE}/close", {"outcome": "no_action_needed"}, {"therapist"}),
]


def _id(route: tuple[str, str, Any, set[str]]) -> str:
    return f"{route[0]} {route[1].replace(str(FAKE), '{id}')}"


@pytest.mark.parametrize("route", ROUTES, ids=_id)
@pytest.mark.parametrize("role", ROLES)
async def test_role_matrix(
    client: httpx.AsyncClient, world: World, role: str, route: tuple[str, str, Any, set[str]]
) -> None:
    method, path, body, allowed = route
    token = await token_for(client, getattr(world, role), world.password)
    r = await call(client, method, path, token=token, json=body)
    if role in allowed:
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


async def test_faculty_resources_are_for_staff_and_student_resources_are_not(
    client: httpx.AsyncClient, world: World
) -> None:
    teacher = await token_for(client, world.teacher, world.password)
    student = await token_for(client, world.student, world.password)
    therapist = await token_for(client, world.therapist, world.password)
    staff = (await call(client, "GET", "/teacher/resources", token=teacher)).json()
    assert staff and all("faculty" in r["tags"] for r in staff)
    for token in (student, therapist):
        listed = (await call(client, "GET", "/resources?limit=100", token=token)).json()
        assert listed and not any("faculty" in r["tags"] for r in listed)
        for r in staff:  # and guessing a staff id gets nothing either
            hit = await call(client, "GET", f"/resources/{r['id']}", token=token)
            assert hit.status_code == 404
    # teachers get only the staff library
    open_id = (await call(client, "GET", "/resources?limit=1", token=student)).json()[0]["id"]
    assert (
        await call(client, "GET", f"/teacher/resources/{open_id}", token=teacher)
    ).status_code == 404
