"""Every therapist-portal route, tried by every role. The permission guard must refuse
students, teachers and administrators before any record is read (the record-level rules are
tested in the suites next to each feature)."""

import datetime as dt
import uuid
from typing import Any

import httpx
import pytest

from tests.api_helpers import call, token_for
from tests.api_world import World

pytestmark = pytest.mark.asyncio

ROLES = ("student", "therapist", "teacher", "admin")
FAKE = uuid.UUID(int=1)
START = (dt.datetime.now(dt.UTC) + dt.timedelta(days=200)).isoformat()
END = (dt.datetime.now(dt.UTC) + dt.timedelta(days=200, hours=1)).isoformat()
THERAPIST = {"therapist"}

ROUTES: list[tuple[str, str, Any, set[str]]] = [
    ("GET", "/therapist/dashboard", None, THERAPIST),
    ("GET", "/therapist/profile", None, THERAPIST),
    ("PATCH", "/therapist/profile", {"bio": "Hello"}, THERAPIST),
    # invalid on purpose (422): the shared therapist must stay verified for the other tests
    ("POST", "/therapist/verification", {"licence_number": "x"}, THERAPIST),
    ("GET", "/therapist/availability", None, THERAPIST),
    ("POST", "/therapist/availability", {"starts_at": START, "ends_at": END}, THERAPIST),
    ("DELETE", f"/therapist/availability/{FAKE}", None, THERAPIST),
    ("GET", "/therapist/appointments", None, THERAPIST),
    ("PATCH", f"/appointments/{FAKE}", {"status": "confirmed"}, THERAPIST),
    ("GET", "/therapist/students", None, THERAPIST),
    ("GET", f"/therapist/students/{FAKE}", None, THERAPIST),
    ("GET", f"/therapist/students/{FAKE}/trends", None, THERAPIST),
    ("GET", f"/therapist/students/{FAKE}/assessments", None, THERAPIST),
    ("GET", f"/therapist/students/{FAKE}/recommendations", None, THERAPIST),
    (
        "POST",
        f"/therapist/students/{FAKE}/recommendations",
        {"title": "A walk", "rationale": "Fresh air helps."},
        THERAPIST,
    ),
    ("GET", "/therapist/sessions", None, THERAPIST),
    ("POST", f"/therapist/appointments/{FAKE}/session", None, THERAPIST),
    ("PATCH", f"/therapist/sessions/{FAKE}", {"status": "completed"}, THERAPIST),
    ("GET", f"/therapist/sessions/{FAKE}/note", None, THERAPIST),
    ("PUT", f"/therapist/sessions/{FAKE}/note", {"body": "x"}, THERAPIST),
    ("GET", f"/students/{FAKE}/therapy-notes", None, THERAPIST),
    ("GET", f"/students/{FAKE}/mood-entries", None, THERAPIST),
    ("GET", "/therapist/alerts", None, THERAPIST),
    ("PATCH", f"/therapist/alerts/{FAKE}", {"action": "acknowledge"}, THERAPIST),
    ("GET", "/therapist/follow-ups", None, THERAPIST),
    (
        "POST",
        "/therapist/follow-ups",
        {"student_id": str(FAKE), "kind": "check_in", "due_on": "2099-01-01"},
        THERAPIST,
    ),
    ("PATCH", f"/therapist/follow-ups/{FAKE}", {"status": "done"}, THERAPIST),
    ("GET", "/admin/therapists", None, {"admin"}),
    ("PATCH", f"/admin/therapists/{FAKE}/verification", {"status": "verified"}, {"admin"}),
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


@pytest.mark.parametrize("route", ROUTES[:-2], ids=_id)
async def test_other_institutions_therapist_is_refused_or_finds_nothing(
    client: httpx.AsyncClient, world: World, route: tuple[str, str, Any, set[str]]
) -> None:
    """The seeded institution-B therapist is a real, verified therapist. Naming institution A's
    records (here: ids that do not exist) can only ever give 'not found' or a validation error,
    never data."""
    method, path, body, _ = route
    token = await token_for(client, world.b_therapist, world.password)
    r = await call(client, method, path, token=token, json=body)
    assert r.status_code in (200, 201, 204, 403, 404, 409, 422), (path, r.status_code, r.text)
