"""Administrators run the institution without being handed anyone's private records.

Four independent proofs, like the teacher portal's:

1. **Map.** Every route an administrator's permissions reach is listed by hand. A route added
   later that an administrator can reach fails this test until someone decides it is safe.
2. **Refusal.** Students, therapists and teachers are refused on every admin route (403), and an
   administrator of another institution cannot see or change anything (404), whatever id is named.
3. **Content.** Real confidential records (therapy note, private journal, AI conversation, private
   message, mood note, safety alert) are planted. Every route the administrator can reach is then
   read, and none of the planted text, and no care relationship, appears in any response.
4. **Permissions.** The admin-only permissions belong to the administrator role alone, and the role
   holds no permission that reads confidential content.
"""

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
from app.domain.auth.permissions import (
    ADMIN_ONLY_PERMISSIONS,
    CONTENT_PERMISSIONS,
    ROLE_PERMISSIONS,
    Permission,
    Role,
)
from app.infrastructure.db.enums import UserRole
from tests.api_helpers import token_for
from tests.api_world import Builder, World
from tests.student_helpers import sign_in
from tests.teacher_helpers import school
from tests.test_teacher_portal_privacy import SENTINELS, json_keys, plant

pytestmark = pytest.mark.asyncio

FAKE = uuid.UUID(int=9)

# ---- 1. the map -----------------------------------------------------------------------------

ADMIN_ROUTES = {
    # shared with other roles
    ("POST", "/auth/logout"),
    ("GET", "/me"),
    # their own notifications (never anyone else's)
    ("GET", "/me/notifications"),
    ("GET", "/me/notifications/unread-count"),
    ("POST", "/me/notifications/{notification_id}/read"),
    ("POST", "/me/notifications/read-all"),
    ("GET", "/insights/mood-summary"),
    ("GET", "/teacher/resources"),
    ("GET", "/teacher/resources/{resource_id}"),
    # accounts and institution
    ("GET", "/admin/users"),
    ("GET", "/admin/users/{user_id}"),
    ("POST", "/admin/users"),
    ("PATCH", "/admin/users/{user_id}"),
    ("POST", "/admin/users/{user_id}/resend-invite"),
    ("POST", "/admin/users/{user_id}/sign-out"),
    ("GET", "/admin/config"),
    ("PATCH", "/admin/config"),
    # audit log
    ("GET", "/admin/audit"),
    ("GET", "/admin/audit/actions"),
    ("POST", "/admin/audit/verify"),
    ("GET", "/admin/audit/export"),
    # therapist verification and accounts
    ("GET", "/admin/therapists"),
    ("PATCH", "/admin/therapists/{therapist_id}/verification"),
    ("GET", "/admin/therapist-accounts"),
    ("PATCH", "/admin/therapist-accounts/{therapist_id}"),
    # people and structure
    ("GET", "/admin/departments"),
    ("POST", "/admin/departments"),
    ("PATCH", "/admin/departments/{department_id}"),
    ("DELETE", "/admin/departments/{department_id}"),
    ("GET", "/admin/courses"),
    ("POST", "/admin/courses"),
    ("GET", "/admin/courses/{course_id}"),
    ("PATCH", "/admin/courses/{course_id}"),
    ("DELETE", "/admin/courses/{course_id}"),
    ("PUT", "/admin/courses/{course_id}/teachers/{teacher_id}"),
    ("DELETE", "/admin/courses/{course_id}/teachers/{teacher_id}"),
    ("PUT", "/admin/courses/{course_id}/students/{student_id}"),
    ("DELETE", "/admin/courses/{course_id}/students/{student_id}"),
    ("GET", "/admin/students"),
    ("GET", "/admin/students/{student_id}"),
    ("PATCH", "/admin/students/{student_id}"),
    ("GET", "/admin/teachers"),
    ("PATCH", "/admin/teachers/{teacher_id}"),
    # resources
    ("GET", "/admin/resources"),
    ("POST", "/admin/resources"),
    ("GET", "/admin/resources/{resource_id}"),
    ("PUT", "/admin/resources/{resource_id}"),
    ("PATCH", "/admin/resources/{resource_id}/publication"),
    ("DELETE", "/admin/resources/{resource_id}"),
    # aggregates only
    ("GET", "/admin/dashboard"),
    ("GET", "/admin/analytics"),
    ("GET", "/admin/appointments/oversight"),
    # settings
    ("GET", "/admin/settings/notifications"),
    ("PATCH", "/admin/settings/notifications"),
    ("GET", "/admin/settings/safety"),
    ("PATCH", "/admin/settings/safety"),
    ("GET", "/admin/settings/crisis-contacts"),
    ("POST", "/admin/settings/crisis-contacts"),
    ("PATCH", "/admin/settings/crisis-contacts/{contact_id}"),
    ("DELETE", "/admin/settings/crisis-contacts/{contact_id}"),
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


def _role_may_pass(role: Role, route: APIRoute) -> bool:
    for requirement in _requirements(route):
        if requirement == "authenticated":
            continue
        wanted = [Permission(p) for p in requirement.split(":", 1)[1].split(",") if p]
        if not all(p in ROLE_PERMISSIONS[role] for p in wanted):
            return False
    return True


def _is_public(method: str, path: str) -> bool:
    return (method, API_PREFIX + path) in PUBLIC_ROUTES


def _fill(path: str) -> str:
    return API_PREFIX + re.sub(r"\{[^}]+\}", str(FAKE), path)


async def test_the_routes_an_administrator_can_reach_are_exactly_the_reviewed_ones() -> None:
    reachable = {
        (method, path)
        for method, path, route in _routes()
        if not _is_public(method, path) and _role_may_pass(Role.ADMIN, route)
    }
    assert reachable == ADMIN_ROUTES


async def test_no_admin_route_reads_private_records() -> None:
    private = (
        "therapy-notes", "mood-entries", "journal", "ai-conversations", "conversations",
        "messages", "trends", "assessments", "privacy", "wellness", "sessions", "referrals",
        "support-requests", "recommendations", "goals", "alerts",
    )  # fmt: skip
    for _, path in ADMIN_ROUTES:
        assert not any(word in path for word in private), path


# ---- 2. refusal -----------------------------------------------------------------------------

ADMIN_AREA = [
    (method, path)
    for method, path, _ in _routes()
    if path.startswith("/admin") and (method, path) in ADMIN_ROUTES
]


@pytest.mark.parametrize("role", ["student", "therapist", "teacher"])
@pytest.mark.parametrize(("method", "path"), ADMIN_AREA, ids=[f"{m} {p}" for m, p in ADMIN_AREA])
async def test_every_admin_route_refuses_other_roles(
    client: httpx.AsyncClient, world: World, role: str, method: str, path: str
) -> None:
    actor = {"student": world.student, "therapist": world.therapist, "teacher": world.teacher}[role]
    token = await token_for(client, actor, world.password)
    r = await client.request(
        method,
        "https://testserver" + _fill(path),
        headers={"Authorization": f"Bearer {token}"},
        json={} if method in {"POST", "PUT", "PATCH"} else None,
    )
    assert r.status_code == 403, f"{role} {method} {path}: {r.status_code} {r.text}"


async def test_admin_routes_need_a_token(client: httpx.AsyncClient) -> None:
    for method, path in ADMIN_AREA:
        r = await client.request(method, "https://testserver" + _fill(path))
        assert r.status_code == 401, (method, path)


async def test_another_institutions_administrator_sees_and_changes_nothing_here(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await sign_in(client, world.admin, world.password)
    b = await sign_in(client, world.b_admin, world.password)

    dept = (await a.post("/admin/departments", {"name": "Isolation", "code": "ISO"})).json()
    course = (
        await a.post(
            "/admin/courses",
            {
                "department_id": dept["id"],
                "code": "ISO1",
                "title": "Isolation 101",
                "term": "2026-autumn",
                "credits": 3,
            },
        )
    ).json()
    resource = (
        await a.post(
            "/admin/resources",
            {
                "title": "Own resource",
                "summary": "s",
                "resource_type": "article",
                "body": "text",
                "publish": True,
            },
        )
    ).json()
    contact = (
        await a.post(
            "/admin/settings/crisis-contacts",
            {"label": "Campus line", "kind": "campus", "phone": "000"},
        )
    ).json()

    mine = {
        "department": dept["id"],
        "course": course["id"],
        "resource": resource["id"],
        "contact": contact["id"],
        "student": str(world.student.user_id),
        "teacher": str(world.teacher.user_id),
        "therapist": str(world.therapist.user_id),
        "user": str(world.student.user_id),
    }
    attempts = [
        ("GET", f"/admin/users/{mine['user']}", None),
        ("PATCH", f"/admin/users/{mine['user']}", {"status": "suspended"}),
        ("POST", f"/admin/users/{mine['user']}/sign-out", None),
        ("POST", f"/admin/users/{mine['user']}/resend-invite", None),
        ("GET", f"/admin/students/{mine['student']}", None),
        ("PATCH", f"/admin/students/{mine['student']}", {"year_of_study": 4}),
        ("PATCH", f"/admin/teachers/{mine['teacher']}", {"title": "x"}),
        ("PATCH", f"/admin/therapist-accounts/{mine['therapist']}", {"max_caseload": 3}),
        (
            "PATCH",
            f"/admin/therapists/{mine['therapist']}/verification",
            {"status": "rejected", "note": "x"},
        ),
        ("PATCH", f"/admin/departments/{mine['department']}", {"name": "Hijacked"}),
        ("DELETE", f"/admin/departments/{mine['department']}", None),
        ("GET", f"/admin/courses/{mine['course']}", None),
        ("PATCH", f"/admin/courses/{mine['course']}", {"title": "Hijacked"}),
        ("DELETE", f"/admin/courses/{mine['course']}", None),
        ("PUT", f"/admin/courses/{mine['course']}/students/{mine['student']}", None),
        ("PUT", f"/admin/courses/{mine['course']}/teachers/{mine['teacher']}", None),
        ("GET", f"/admin/resources/{mine['resource']}", None),
        ("PUT", f"/admin/resources/{mine['resource']}", {
            "title": "Hijacked", "summary": "s", "resource_type": "article", "body": "x"}),
        ("PATCH", f"/admin/resources/{mine['resource']}/publication", {"published": False}),
        ("DELETE", f"/admin/resources/{mine['resource']}", None),
        ("PATCH", f"/admin/settings/crisis-contacts/{mine['contact']}", {"label": "Hijacked"}),
        ("DELETE", f"/admin/settings/crisis-contacts/{mine['contact']}", None),
    ]  # fmt: skip
    for method, path, body in attempts:
        r = await b.client.request(
            method,
            "https://testserver" + API_PREFIX + path,
            headers={"Authorization": f"Bearer {b.token}"},
            json=body,
        )
        assert r.status_code == 404, f"{method} {path}: {r.status_code} {r.text}"

    # nothing of A's shows up in B's lists either
    for path in (
        "/admin/users?limit=200",
        "/admin/students?limit=200",
        "/admin/teachers?limit=200",
        "/admin/therapist-accounts?limit=200",
        "/admin/courses",
        "/admin/departments",
        "/admin/settings/crisis-contacts",
    ):
        text = (await b.get(path)).text
        for value in mine.values():
            assert value not in text, f"{path} leaked {value}"

    # B's log holds B's own attempts (denied, recorded in B's institution) and none of A's
    events = (await b.get("/admin/audit?limit=200")).json()
    assert events
    assert str(world.admin.user_id) not in {e["actor_id"] for e in events}
    assert {e["outcome"] for e in events if e["action"].startswith("department.")} <= {"denied"}

    # and nothing changed
    assert (await a.get(f"/admin/courses/{mine['course']}")).json()["course"]["title"] == (
        "Isolation 101"
    )
    assert (await a.get(f"/admin/users/{mine['user']}")).json()["status"] == "active"


# ---- 3. content -----------------------------------------------------------------------------


async def test_planted_confidential_records_never_reach_an_administrator(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    therapist = await Builder(api_db, world.password).user(world.inst_a, UserRole.THERAPIST)
    await api_db.commit()
    for n, student in enumerate(s.students[:3]):
        await plant(api_db, world, student, therapist, n)
    admin = await sign_in(client, world.admin, world.password)

    teacher_id = (await admin.get("/admin/teachers?limit=200")).json()["items"][0]["id"]
    resources = (await admin.get("/admin/resources")).json()
    templates = {
        "user_id": str(s.students[0].user_id),
        "student_id": str(s.students[0].user_id),
        "course_id": str(s.course_id),
        "department_id": str(s.dept_id),
        "teacher_id": teacher_id,
        "therapist_id": str(therapist.user_id),
        "resource_id": resources[0]["id"],
    }
    # routes that legitimately name people (account and roster data), and the care link that
    # must still never appear in them
    names_students = {
        "/admin/users", "/admin/users/{user_id}", "/admin/students", "/admin/students/{student_id}",
        "/admin/courses/{course_id}", "/admin/audit", "/admin/audit/export",
    }  # fmt: skip
    student_ids = {str(x.user_id) for x in s.students}
    emails = [x.email for x in s.students]
    care_ids = {str(therapist.user_id)}
    reads = sorted(
        (m, p)
        for m, p in ADMIN_ROUTES
        if m == "GET" and p.startswith("/admin") and p != "/admin/audit/export"
    ) + [("GET", "/admin/audit/export")]

    crawled = 0
    for _, path in reads:
        url = path
        for key, value in templates.items():
            url = url.replace("{" + key + "}", value)
        r = await admin.get(url)
        assert r.status_code == 200, f"GET {path}: {r.status_code} {r.text}"
        crawled += 1
        text = r.text
        for label, secret in SENTINELS.items():
            assert secret not in text, f"{label} text leaked through {path}"
        if path not in names_students:
            for sid in student_ids:
                assert sid not in text, f"{path} names a student"
            for email in emails:
                assert email not in text, f"{path} carries a student's e-mail"
        if path in {"/admin/students/{student_id}", "/admin/users/{user_id}", "/admin/students"}:
            for cid in care_ids:
                assert cid not in text, f"{path} reveals who a student sees"
        if "json" in r.headers["content-type"]:
            bad = [
                k
                for k in json_keys(r.json())
                if re.search(r"diagnos|therapy|journal|conversation|mood_score|care_team", k)
            ]
            assert bad == [], (path, bad)
    assert crawled >= 18


async def test_an_administrator_cannot_open_confidential_records_directly(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    therapist = await Builder(api_db, world.password).user(world.inst_a, UserRole.THERAPIST)
    await api_db.commit()
    ids = await plant(api_db, world, s.students[0], therapist)
    sid = s.students[0].user_id
    admin = await sign_in(client, world.admin, world.password)
    attempts = [
        ("GET", f"/students/{sid}/therapy-notes"),
        ("GET", f"/therapist/sessions/{ids['session']}/note"),
        ("PUT", f"/therapist/sessions/{ids['session']}/note"),
        ("GET", f"/therapist/students/{sid}"),
        ("GET", f"/therapist/students/{sid}/trends"),
        ("GET", "/therapist/alerts"),
        ("PATCH", f"/therapist/alerts/{ids['alert']}"),
        ("GET", "/therapist/appointments"),
        ("GET", "/me/conversations"),
        ("GET", "/me/ai-conversations"),
        ("GET", "/me/wellness/mood-entries"),
        ("GET", "/me/privacy/export"),
        ("GET", "/me/journal"),
        ("GET", "/me/messages"),
        ("GET", "/teacher/referrals"),
        ("GET", "/teacher/support-requests"),
        ("GET", f"/teacher/classes/{s.course_id}/students"),
        ("GET", f"/teacher/classes/{s.course_id}/analytics"),
    ]
    for method, path in attempts:
        r = await admin.client.request(
            method,
            "https://testserver" + API_PREFIX + path,
            headers={"Authorization": f"Bearer {admin.token}"},
            json={} if method in {"PUT", "PATCH"} else None,
        )
        assert r.status_code in {403, 404}, f"{method} {path}: {r.status_code}"
        assert not any(secret in r.text for secret in SENTINELS.values())


# ---- 4. permissions -------------------------------------------------------------------------


async def test_admin_only_permissions_belong_to_administrators_alone() -> None:
    for perm in ADMIN_ONLY_PERMISSIONS:
        assert [r for r in Role if perm in ROLE_PERMISSIONS[r]] == [Role.ADMIN], perm


async def test_the_administrator_role_holds_no_content_permission() -> None:
    assert not ROLE_PERMISSIONS[Role.ADMIN] & CONTENT_PERMISSIONS


async def test_admin_permissions_never_include_anything_that_reads_a_students_private_data() -> (
    None
):
    private_words = ("note", "journal", "conversation", "message", "mood", "assessment", "alert")
    for perm in ROLE_PERMISSIONS[Role.ADMIN]:
        assert not any(w in perm.value for w in private_words), perm.value
