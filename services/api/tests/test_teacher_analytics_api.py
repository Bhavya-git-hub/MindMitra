"""Group figures for a teacher: only for their own class and department, only from students who
agreed to be counted, and never for a group small enough to point at a person."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AuditOutcome
from tests.api_helpers import call, token_for
from tests.api_world import World
from tests.student_helpers import sign_in
from tests.teacher_helpers import School, add_week, another_teacher, school

pytestmark = pytest.mark.asyncio


def figures_text(body: object) -> str:
    return json.dumps(body)


async def analytics(s: School, weeks: int | None = None) -> httpx.Response:
    q = f"?weeks={weeks}" if weeks else ""
    return await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics{q}")


async def test_a_class_of_enough_consenting_students_gets_figures(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    r = await analytics(s)
    assert r.status_code == 200, r.text
    a = r.json()["analytics"]
    assert a["state"] == "ok" and a["students_contributing"] == "10 to 19"
    assert a["min_group_size"] == 10 and a["window_weeks"] == 8 and len(a["weeks"]) == 8
    last_week = a["weeks"][-2]  # last week; the current week has no data yet
    assert last_week["mood"] is not None and 1 <= last_week["mood"] <= 5
    assert a["weeks"][0]["mood"] is None  # no data that far back, so nothing is invented
    assert "diagnos" in a["disclaimer"]


async def test_the_response_contains_no_individual_student(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    text = figures_text((await analytics(s)).json()) + figures_text(
        (await s.teacher.get(f"/teacher/classes/{s.course_id}/report")).json()
    )
    csv = (await s.teacher.get(f"/teacher/classes/{s.course_id}/report.csv")).text
    for p in s.students:
        for secret in (str(p.user_id), p.email):
            assert secret not in text and secret not in csv
    assert "private synthetic note" not in text + csv
    assert '"student_id"' not in text and '"name"' not in text


@pytest.mark.parametrize(
    ("consenting", "expected"), [(0, "too_small"), (9, "too_small"), (10, "ok")]
)
async def test_the_threshold_counts_students_who_agreed_not_students_enrolled(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, consenting: int, expected: str
) -> None:
    s = await school(client, api_db, world, students=14, consenting=consenting)
    a = (await analytics(s)).json()["analytics"]
    assert a["state"] == expected
    if expected == "too_small":
        assert a["weeks"] == [] and a["stressors"] == [] and a["actions"] == []
        assert a["students_contributing"] is None and a["wellbeing"] == []
        assert "Too few" in " ".join(a["headline"])


async def test_students_who_did_not_agree_change_nothing(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Adding a non-consenting student with extreme entries must not move any figure."""
    s = await school(client, api_db, world, students=12)
    before = (await analytics(s)).json()["analytics"]
    from app.infrastructure.db.enums import UserRole
    from tests.api_world import Builder

    b = Builder(api_db, world.password)
    dept = await api_db.scalar(select(m.Course.department_id).where(m.Course.id == s.course_id))
    assert dept is not None
    outsider = await b.user(world.inst_a, UserRole.STUDENT, department_id=dept)
    api_db.add(
        m.CourseEnrollment(
            institution_id=world.inst_a, course_id=s.course_id, student_id=outsider.user_id
        )
    )
    for weeks_ago in (1, 2):
        await add_week(api_db, world.inst_a, outsider, weeks_ago, mood=1, energy=1, stress=5)
    await api_db.commit()
    after = (await analytics(s)).json()["analytics"]
    before.pop("generated_at"), after.pop("generated_at")
    assert before == after


async def test_withdrawing_consent_removes_the_student_from_the_next_request(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=10)
    assert (await analytics(s)).json()["analytics"]["state"] == "ok"
    leaver = await sign_in(client, s.students[0], world.password)
    r = await leaver.put("/me/consents/anonymous_aggregate_research", {"granted": False})
    assert r.status_code == 200, r.text
    again = (await analytics(s)).json()["analytics"]
    assert again["state"] == "too_small" and again["weeks"] == []
    r = await leaver.put("/me/consents/anonymous_aggregate_research", {"granted": True})
    assert r.status_code == 200
    assert (await analytics(s)).json()["analytics"]["state"] == "ok"


async def test_shares_are_rounded_and_never_a_small_count(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    a = (await analytics(s)).json()["analytics"]
    for week in a["weeks"]:
        for key in ("check_in", "academic_stress", "strain"):
            share = week[key]
            assert share["state"] in {"shown", "few", "most", "hidden"}
            if share["state"] == "shown":
                assert share["percent"] % 5 == 0
            else:
                assert share["percent"] is None
    for item in a["stressors"]:
        assert item["share"]["state"] in {"shown", "most"}


async def test_window_must_be_one_of_the_fixed_sizes(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Free-form windows would let overlapping requests be subtracted to isolate one week."""
    s = await school(client, api_db, world, students=10)
    for weeks in (1, 3, 5, 9, 52):
        assert (await analytics(s, weeks)).status_code == 422
    for weeks in (4, 8, 12):
        r = await analytics(s, weeks)
        assert r.status_code == 200 and len(r.json()["analytics"]["weeks"]) == weeks


async def test_another_teachers_class_looks_like_it_does_not_exist(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    mine = await school(client, api_db, world, students=12)
    theirs = await school(client, api_db, world, students=12)
    for path in ("analytics", "report", "report.csv", "students", ""):
        r = await mine.teacher.get(f"/teacher/classes/{theirs.course_id}/{path}".rstrip("/"))
        assert r.status_code == 404, (path, r.status_code)
    missing = await mine.teacher.get(f"/teacher/classes/{uuid.uuid4()}/analytics")
    assert missing.status_code == 404 and missing.json()["detail"] == r.json()["detail"]


async def test_a_teacher_in_the_same_department_but_not_teaching_the_class_is_refused(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    colleague = await another_teacher(client, api_db, world, s.dept_id)
    assert (await colleague.get(f"/teacher/classes/{s.course_id}/analytics")).status_code == 404
    assert (await colleague.get(f"/teacher/classes/{s.course_id}/students")).status_code == 404
    # but the department is theirs too, so department figures are allowed
    assert (await colleague.get(f"/teacher/departments/{s.dept_id}/analytics")).status_code == 200


async def test_department_figures_are_for_the_teachers_own_department_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    mine = await school(client, api_db, world, students=12)
    theirs = await school(client, api_db, world, students=12)
    ok = await mine.teacher.get(f"/teacher/departments/{mine.dept_id}/analytics")
    assert ok.status_code == 200 and ok.json()["analytics"]["state"] == "ok"
    for tail in ("analytics", "report", "report.csv"):
        assert (
            await mine.teacher.get(f"/teacher/departments/{theirs.dept_id}/{tail}")
        ).status_code == 403
    assert (
        await mine.teacher.get(f"/teacher/departments/{uuid.uuid4()}/analytics")
    ).status_code == 404


async def test_other_institutions_are_invisible(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    token = await token_for(client, world.b_teacher, world.password)
    for path in (
        f"/teacher/classes/{s.course_id}/analytics",
        f"/teacher/classes/{s.course_id}/students",
        f"/teacher/departments/{s.dept_id}/analytics",
    ):
        assert (await call(client, "GET", path, token=token)).status_code == 404, path
    # and the other institution's teacher sees no classes of ours
    assert (await call(client, "GET", "/teacher/classes", token=token)).json() == []


async def test_a_teachers_classes_are_listed_with_enrolment_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=11, consenting=3)
    classes = (await s.teacher.get("/teacher/classes")).json()
    assert [c["id"] for c in classes] == [str(s.course_id)]
    assert classes[0]["enrolled"] == 11
    assert set(classes[0]) == {"id", "code", "title", "term", "department_name", "enrolled"}


async def test_roster_is_names_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=10, consenting=0)
    r = await s.teacher.get(f"/teacher/classes/{s.course_id}/students")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 10 and all(set(x) == {"student_id", "name"} for x in rows)
    assert not any("@" in x["name"] for x in rows)


async def test_dashboard_shows_the_department_and_counts_not_people(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    r = await s.teacher.get("/teacher/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["teacher"]["department_id"] == str(s.dept_id)
    assert d["department"]["window_weeks"] == 4 and d["department"]["state"] == "ok"
    assert d["referrals"] == {"received": 0, "in_progress": 0, "closed": 0}
    text = figures_text(d)
    assert not any(str(p.user_id) in text or p.email in text for p in s.students)


async def test_report_and_csv_downloads(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    report = (await s.teacher.get(f"/teacher/classes/{s.course_id}/report?weeks=4")).json()
    assert report["title"].startswith("Anonymous wellbeing report")
    assert report["window_weeks"] == 4 and report["summary"] and report["notes"]
    csv = await s.teacher.get(f"/teacher/classes/{s.course_id}/report.csv?weeks=4")
    assert csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv.headers["content-disposition"]
    assert len(csv.text.strip().splitlines()) == 5  # header + 4 weeks


async def test_reads_and_refusals_are_audited_without_figures(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    mine = await school(client, api_db, world, students=12)
    theirs = await school(client, api_db, world, students=12)
    assert (await analytics(mine)).status_code == 200
    assert (
        await mine.teacher.get(f"/teacher/departments/{theirs.dept_id}/analytics")
    ).status_code == 403
    rows = (
        await api_db.scalars(select(m.AuditLog).where(m.AuditLog.actor_id == mine.teacher.id))
    ).all()
    by_action = {(r.action, r.outcome) for r in rows}
    assert ("class_analytics.read", AuditOutcome.ALLOWED) in by_action
    assert ("department_analytics.read", AuditOutcome.DENIED) in by_action
    read = next(r for r in rows if r.action == "class_analytics.read")
    assert read.subject_student_id is None
    assert set(read.details) == {"weeks", "result"}


@pytest.mark.parametrize(("checks", "shown"), [(9, False), (10, True)])
async def test_wellbeing_bands_need_ten_students_with_a_recent_check(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, checks: int, shown: bool
) -> None:
    from tests.teacher_helpers import add_wellbeing_check

    s = await school(client, api_db, world, students=12)
    for i, p in enumerate(s.students[:checks]):
        await add_wellbeing_check(api_db, world.inst_a, p, 20 if i % 2 == 0 else 8)
    await api_db.commit()
    bands = (await analytics(s)).json()["analytics"]["wellbeing"]
    assert bool(bands) is shown
    for band in bands:
        assert band["share"]["state"] in {"shown", "few", "most"}
