"""The same privacy promises, checked across every portal's analytics at once.

Each portal has its own tests for its own numbers. This file proves the promises they share:

* teacher and administrator analytics are group figures, with no student id, name, email, note or
  per-student key anywhere in the payload;
* a group of fewer than ten students who agreed to be counted shows no figure at all;
* the administrator's small counts (one to four) are never shown;
* a therapist's analytics never include a student who has not agreed to share, and a student's own
  analytics never include anyone else.
"""

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api_world import World
from tests.student_helpers import Session, sign_in
from tests.teacher_helpers import School, school
from tests.test_teacher_portal_privacy import json_keys

pytestmark = pytest.mark.asyncio

NOTE = "private synthetic note"  # planted in every check-in the school helper creates
FORBIDDEN_KEYS = {
    "student_id",
    "user_id",
    "email",
    "name",
    "full_name",
    "first_name",
    "last_name",
    "note",
    "notes",
    "excerpt",
    "body",
    "rationale",
}


def assert_nobody_in(text: str, s: School) -> None:
    for p in s.students:
        assert str(p.user_id) not in text
        assert p.email not in text
    assert NOTE not in text


def assert_no_personal_keys(body: Any) -> None:
    found = {k for k in json_keys(body) if k in FORBIDDEN_KEYS}
    assert not found, found


async def get_json(session: Session, path: str) -> Any:
    r = await session.get(path)
    assert r.status_code == 200, (path, r.text)
    return r.json()


async def test_group_analytics_for_teachers_and_administrators_name_nobody(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    admin = await sign_in(client, world.admin, world.password)

    payloads = [
        await get_json(s.teacher, f"/teacher/classes/{s.course_id}/analytics"),
        await get_json(s.teacher, f"/teacher/departments/{s.dept_id}/analytics"),
        await get_json(admin, "/admin/analytics"),
        await get_json(admin, "/admin/analytics/services"),
    ]
    csv = (await s.teacher.get(f"/teacher/classes/{s.course_id}/report.csv")).text
    for body in payloads:
        assert_nobody_in(json.dumps(body), s)
        assert_no_personal_keys(body)
    assert_nobody_in(csv, s)


@pytest.mark.parametrize("agreed", [0, 4, 9])
async def test_a_group_under_ten_who_agreed_shows_no_figure(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, agreed: int
) -> None:
    """Twelve students have data, but only ``agreed`` of them may be counted."""
    s = await school(client, api_db, world, students=12, consenting=agreed)
    for path in (
        f"/teacher/classes/{s.course_id}/analytics",
        f"/teacher/departments/{s.dept_id}/analytics",
    ):
        body = (await get_json(s.teacher, path))["analytics"]
        assert body["state"] == "too_small", path
        assert not any(w["mood"] is not None for w in body["weeks"]), path
        assert not body.get("students_contributing"), path


async def test_the_size_of_a_group_is_a_band_never_an_exact_number(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=13)
    body = (await get_json(s.teacher, f"/teacher/classes/{s.course_id}/analytics"))["analytics"]
    assert body["students_contributing"] == "10 to 19"
    assert "13" not in json.dumps(body["students_contributing"])


async def test_an_administrator_never_sees_a_count_of_one_to_four(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """The seeded institution has a handful of students, so every small usage count must be
    hidden (null) rather than shown, and zero stays zero."""
    admin = await sign_in(client, world.admin, world.password)
    body = await get_json(admin, "/admin/analytics/services?weeks=12")
    usage = body["usage"]
    for week in usage["weekly"]:
        for key in ("check_ins", "active_students", "companion_messages", "therapist_messages"):
            assert week[key] is None or week[key] == 0 or week[key] >= 5, (key, week)
    for key, value in usage["totals"].items():
        assert value is None or value == 0 or value >= 5, (key, value)
    for group in body["engagement"]["by_source"] + body["engagement"]["by_problem_area"]:
        if group["suppressed"]:
            assert group["suggestions"] is None and group["completed"] is None


async def test_a_therapist_gets_no_figures_from_students_who_did_not_agree_to_share(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    therapist = await sign_in(client, world.therapist, world.password)
    body = await get_json(therapist, "/therapist/analytics?weeks=12")
    text = json.dumps(body)
    assert_no_personal_keys(body)
    for person in (world.student, world.unconsented_student, world.other_student):
        assert str(person.user_id) not in text and person.email not in text
    caseload = body["caseload"]
    assert caseload["sharing_count"] <= caseload["caseload_size"]
    assert caseload["sharing_count"] < caseload["caseload_size"]  # one care-team student is private


async def test_a_students_analytics_hold_only_their_own_week(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    other = await sign_in(client, world.other_student, world.password)
    own = await sign_in(client, world.student, world.password)
    for who in (own, other):
        body = await get_json(who, "/me/wellness/analytics?weeks=4")
        text = json.dumps(body)
        assert str(uuid.UUID(int=0)) not in text
        for person in (world.student, world.other_student, world.unconsented_student):
            assert str(person.user_id) not in text and person.email not in text
        assert len(body["weeks"]) == 4
