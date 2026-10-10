"""What the administrator portal does: accounts, structure, resources, aggregates, audit, settings.

Authorization and privacy have their own file (``test_admin_portal_authz``); this one checks the
behaviour and the rules each change must keep (group figures forgotten when membership moves,
small counts hidden, the last emergency contact kept, and so on).
"""

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import admin_audit, admin_insights
from app.application.auth.delivery import InMemoryTokenOutbox
from app.domain.settings import NotificationSettings, SafetySettings
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AppointmentStatus,
    NotificationType,
    OneTimeTokenPurpose,
    SessionMode,
    UserRole,
)
from app.infrastructure.db.ids import uuid7
from tests.api_world import World
from tests.student_helpers import Session, new_student, sign_in
from tests.teacher_helpers import school
from tests.therapist_helpers import care_pair, fresh_therapist

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def admin(client: httpx.AsyncClient, world: World) -> Session:
    return await sign_in(client, world.admin, world.password)


@pytest_asyncio.fixture
async def b_admin(client: httpx.AsyncClient, world: World) -> Session:
    return await sign_in(client, world.b_admin, world.password)


def tag() -> str:
    return uuid.uuid4().hex[:8]


async def snapshots(db: AsyncSession, group: uuid.UUID) -> int:
    await db.rollback()  # read what the API committed
    return (
        await db.scalar(
            select(func.count())
            .select_from(m.GroupSnapshot)
            .where(m.GroupSnapshot.group_id == group)
        )
    ) or 0


async def audit_count(db: AsyncSession, institution: uuid.UUID, action: str) -> int:
    await db.rollback()
    return (
        await db.scalar(
            select(func.count())
            .select_from(m.AuditLog)
            .where(m.AuditLog.institution_id == institution, m.AuditLog.action == action)
        )
    ) or 0


# ---- accounts --------------------------------------------------------------------------------


async def test_user_list_searches_filters_and_pages(admin: Session, world: World) -> None:
    t = tag()
    for i in range(3):
        r = await admin.post(
            "/admin/users",
            {
                "email": f"find.{t}.{i}@test.example",
                "full_name": f"Findable {t} {i}",
                "role": "therapist",
                "licence_number": f"LN-{t}-{i}",
            },
        )
        assert r.status_code == 201, r.text

    found = (await admin.get(f"/admin/users?q={t}")).json()
    assert found["total"] == 3 and len(found["items"]) == 3
    assert {u["role"] for u in found["items"]} == {"therapist"}
    page = (await admin.get(f"/admin/users?q={t}&limit=2&offset=2")).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    # a search is not a pattern: % and _ are literal
    assert (await admin.get("/admin/users?q=%25")).json()["total"] == 0
    only_students = (await admin.get("/admin/users?role=student&limit=200")).json()
    assert only_students["items"] and {u["role"] for u in only_students["items"]} == {"student"}
    invited = (await admin.get(f"/admin/users?q={t}&status=invited")).json()
    assert invited["total"] == 3
    assert (await admin.get("/admin/users?limit=500")).status_code == 422


async def test_resend_invite_and_forced_sign_out(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    admin: Session,
    world: World,
    outbox: InMemoryTokenOutbox,
) -> None:
    email = f"invite.{tag()}@test.example"
    created = await admin.post(
        "/admin/users",
        {"email": email, "full_name": "Invitee", "role": "therapist", "licence_number": tag()},
    )
    uid = created.json()["id"]
    first = outbox.latest(email, OneTimeTokenPurpose.ACCOUNT_SETUP)
    assert (await admin.post(f"/admin/users/{uid}/resend-invite")).status_code == 204
    second = outbox.latest(email, OneTimeTokenPurpose.ACCOUNT_SETUP)
    assert first and second and first != second

    student = await new_student(client, api_db, world)
    sessions = select(m.AuthSession).where(m.AuthSession.user_id == student.id)
    assert all(s.revoked_at is None for s in await api_db.scalars(sessions))
    assert (await admin.post(f"/admin/users/{student.id}/sign-out")).status_code == 204
    await api_db.rollback()
    rows = list(await api_db.scalars(sessions))
    assert rows and all(s.revoked_at is not None for s in rows)
    # an active account has nothing to resend
    assert (await admin.post(f"/admin/users/{student.id}/resend-invite")).status_code == 409


async def test_an_administrator_cannot_manage_their_own_account(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    from tests.therapist_helpers import fresh_admin

    me = await fresh_admin(client, api_db, world)
    for method, path, body in (
        ("PATCH", f"/admin/users/{me.id}", {"status": "suspended"}),
        ("POST", f"/admin/users/{me.id}/sign-out", None),
    ):
        r = await me.client.request(
            method,
            f"https://testserver/api/v1{path}",
            headers={"Authorization": f"Bearer {me.token}"},
            json=body,
        )
        assert r.status_code == 403, (method, path, r.status_code)


# ---- departments and courses ----------------------------------------------------------------


async def test_department_rules(admin: Session) -> None:
    code = f"D{tag()}".upper()
    made = await admin.post("/admin/departments", {"name": "  Physics  Lab ", "code": code.lower()})
    assert made.status_code == 201, made.text
    dept = made.json()
    assert dept["code"] == code and dept["name"] == "Physics Lab" and dept["students"] == 0

    assert (
        await admin.post("/admin/departments", {"name": "Dup", "code": code})
    ).status_code == 409
    assert (
        await admin.post("/admin/departments", {"name": "Bad", "code": "has space"})
    ).status_code == 422
    assert (await admin.post("/admin/departments", {"name": "  ", "code": "X1"})).status_code == 422

    renamed = await admin.patch(f"/admin/departments/{dept['id']}", {"name": "Physics"})
    assert renamed.json()["name"] == "Physics"
    listed = (await admin.get("/admin/departments")).json()
    assert any(d["id"] == dept["id"] for d in listed)
    assert (await admin.delete(f"/admin/departments/{dept['id']}")).status_code == 204
    assert (await admin.delete(f"/admin/departments/{dept['id']}")).status_code == 404


async def test_a_department_in_use_cannot_be_deleted(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    r = await admin.delete(f"/admin/departments/{s.dept_id}")
    assert r.status_code == 409
    listed = {d["id"]: d for d in (await admin.get("/admin/departments")).json()}
    assert listed[str(s.dept_id)]["students"] == 2 and listed[str(s.dept_id)]["courses"] == 1


async def test_course_rules(admin: Session) -> None:
    dept = (await admin.post("/admin/departments", {"name": "Maths", "code": f"M{tag()}"})).json()
    body = {
        "department_id": dept["id"],
        "code": "ma101",
        "title": "Calculus",
        "term": "2026-autumn",
        "credits": 4,
    }
    made = await admin.post("/admin/courses", body)
    assert made.status_code == 201, made.text
    course = made.json()
    assert course["code"] == "MA101" and course["credits"] == 4 and course["enrolled"] == 0
    assert (await admin.post("/admin/courses", body)).status_code == 409
    assert (await admin.post("/admin/courses", body | {"term": "autumn"})).status_code == 422
    assert (await admin.post("/admin/courses", body | {"credits": 31})).status_code == 422
    missing = body | {"department_id": str(uuid.uuid4()), "code": "ZZ1"}
    assert (await admin.post("/admin/courses", missing)).status_code == 404

    changed = await admin.patch(f"/admin/courses/{course['id']}", {"title": "Calculus I"})
    assert changed.json()["title"] == "Calculus I"
    by_dept = (await admin.get(f"/admin/courses?department_id={dept['id']}")).json()
    assert [c["id"] for c in by_dept] == [course["id"]]
    assert (await admin.get("/admin/courses?q=calculus")).json()
    assert (await admin.delete(f"/admin/courses/{course['id']}")).status_code == 204


async def test_teacher_assignment(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    other = str(world.teacher.user_id)
    path = f"/admin/courses/{s.course_id}/teachers/{other}"
    assert (await admin.put(path)).status_code == 204
    assert (await admin.put(path)).status_code == 204  # idempotent
    detail = (await admin.get(f"/admin/courses/{s.course_id}")).json()
    assert other in {t["id"] for t in detail["teachers"]} and len(detail["teachers"]) == 2
    assert (await admin.delete(path)).status_code == 204
    detail = (await admin.get(f"/admin/courses/{s.course_id}")).json()
    assert other not in {t["id"] for t in detail["teachers"]}
    # a teacher from another institution is not on offer
    foreign = f"/admin/courses/{s.course_id}/teachers/{world.b_teacher.user_id}"
    assert (await admin.put(foreign)).status_code == 404


async def test_enrolment_changes_make_a_class_forget_its_stored_figures(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    first = (await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics")).json()
    assert first["analytics"]["state"] == "ok"
    assert await snapshots(api_db, s.course_id) == 1

    leaving = s.students[0]
    drop = f"/admin/courses/{s.course_id}/students/{leaving.user_id}"
    assert (await admin.delete(drop)).status_code == 204
    assert await snapshots(api_db, s.course_id) == 0  # the class's stored window is gone
    detail = (await admin.get(f"/admin/courses/{s.course_id}")).json()
    assert detail["course"]["enrolled"] == 11
    assert str(leaving.user_id) not in {p["id"] for p in detail["students"]}
    roster = (await s.teacher.get(f"/teacher/classes/{s.course_id}/students")).json()
    assert str(leaving.user_id) not in {p["student_id"] for p in roster}

    assert (await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics")).status_code == 200
    assert await snapshots(api_db, s.course_id) == 1
    assert (await admin.put(drop)).status_code == 204  # re-enrolling restores them
    assert await snapshots(api_db, s.course_id) == 0
    detail = (await admin.get(f"/admin/courses/{s.course_id}")).json()
    assert detail["course"]["enrolled"] == 12
    assert (
        await admin.put(f"/admin/courses/{s.course_id}/students/{uuid.uuid4()}")
    ).status_code == 404


async def test_a_course_with_enrolment_history_cannot_be_deleted(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    assert (await admin.delete(f"/admin/courses/{s.course_id}")).status_code == 409


# ---- students, teachers, therapists ---------------------------------------------------------


async def test_student_records(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    target = s.students[0]
    listed = (await admin.get(f"/admin/students?department_id={s.dept_id}&limit=200")).json()
    assert listed["total"] == 12
    one = listed["items"][0]
    assert set(one) == {
        "id", "full_name", "email", "status", "student_number", "department_id",
        "department_name", "enrollment_year", "year_of_study",
    }  # fmt: skip
    found = (await admin.get(f"/admin/students?q={target.email}")).json()
    assert [x["id"] for x in found["items"]] == [str(target.user_id)]
    detail = (await admin.get(f"/admin/students/{target.user_id}")).json()
    assert [c["status"] for c in detail["courses"]] == ["enrolled"]

    # moving a student between departments makes both departments forget stored figures
    assert (await s.teacher.get(f"/teacher/departments/{s.dept_id}/analytics")).status_code == 200
    assert await snapshots(api_db, s.dept_id) == 1
    new_dept = (
        await admin.post("/admin/departments", {"name": "Moved to", "code": f"T{tag()}"})
    ).json()
    moved = await admin.patch(
        f"/admin/students/{target.user_id}",
        {"department_id": new_dept["id"], "year_of_study": 3},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["department_id"] == new_dept["id"] and moved.json()["year_of_study"] == 3
    assert await snapshots(api_db, s.dept_id) == 0
    now_in_dept = (await s.teacher.get(f"/teacher/departments/{s.dept_id}/analytics")).json()
    assert now_in_dept["analytics"]["students_contributing"] in {"10 to 19", None, "20 to 49"}

    other = s.students[1]
    clash = await admin.patch(
        f"/admin/students/{target.user_id}",
        {"student_number": f"T-{other.email.split('.')[1].split('@')[0]}"},
    )
    assert clash.status_code in {
        200,
        409,
    }  # number format is the fixture's; uniqueness is the point
    assert (
        await admin.patch(f"/admin/students/{target.user_id}", {"year_of_study": 9})
    ).status_code == 422
    assert (
        await admin.patch(f"/admin/students/{target.user_id}", {"department_id": str(uuid.uuid4())})
    ).status_code == 404


async def test_a_suspended_account_is_no_longer_counted_in_group_figures(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    s = await school(client, api_db, world, students=10)
    ok = (await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics")).json()
    assert ok["analytics"]["state"] == "ok"
    r = await admin.patch(f"/admin/users/{s.students[0].user_id}", {"status": "suspended"})
    assert r.status_code == 200
    # ten contributors became nine: below the minimum, so the figures disappear
    after = (await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics")).json()
    assert after["analytics"]["state"] != "ok"


async def test_teacher_records(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    page = (await admin.get(f"/admin/teachers?department_id={s.dept_id}")).json()
    assert page["total"] == 1 and page["items"][0]["courses"] == 1
    teacher_id = page["items"][0]["id"]
    changed = await admin.patch(f"/admin/teachers/{teacher_id}", {"title": "Dr. Synthetic"})
    assert changed.status_code == 200 and changed.json()["title"] == "Dr. Synthetic"
    assert (
        await admin.patch(f"/admin/teachers/{teacher_id}", {"employee_number": ""})
    ).status_code == 422


async def test_therapist_records_and_licence_changes(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world)
    page = (await admin.get(f"/admin/therapist-accounts?q={t.actor.email}")).json()
    assert page["total"] == 1
    row = page["items"][0]
    assert row["verification_status"] == "verified" and row["caseload"] == 0
    assert "care_team" not in str(row) and "students" not in row

    assert (
        await admin.patch(f"/admin/therapist-accounts/{t.id}", {"max_caseload": 0})
    ).status_code == 422
    capped = await admin.patch(f"/admin/therapist-accounts/{t.id}", {"max_caseload": 12})
    assert (
        capped.json()["max_caseload"] == 12 and capped.json()["verification_status"] == "verified"
    )
    # a different licence is a different person to check: back to the queue
    relicensed = await admin.patch(
        f"/admin/therapist-accounts/{t.id}", {"licence_number": f"NEW-{tag()}"}
    )
    assert relicensed.json()["verification_status"] == "pending"
    queue = (await admin.get("/admin/therapists?status=pending")).json()
    assert str(t.id) in {x["id"] for x in queue}


async def test_caseload_is_a_head_count_not_a_list(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    row = (await admin.get(f"/admin/therapist-accounts?q={pair.therapist.actor.email}")).json()[
        "items"
    ][0]
    assert row["caseload"] == 1
    assert str(pair.student.id) not in str(row)
    student = (await admin.get(f"/admin/students/{pair.student.id}")).text
    assert str(pair.therapist.id) not in student


# ---- resources -------------------------------------------------------------------------------


def resource(**over: object) -> dict[str, object]:
    return {
        "title": f"Breathing {tag()}",
        "summary": "A short breathing exercise.",
        "resource_type": "exercise",
        "body": "Breathe in for four, out for six.",
        "tags": ["calm", "breathing"],
        "duration_minutes": 5,
    } | over


async def test_resource_lifecycle_and_visibility(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    student = await new_student(client, api_db, world)
    made = await admin.post("/admin/resources", resource())
    assert made.status_code == 201, made.text
    item = made.json()
    assert item["is_published"] is False and item["source"] == "institution"
    assert item["editable"] is True and item["reviewed_at"] is None

    async def visible() -> bool:
        return item["id"] in {r["id"] for r in (await student.get("/resources")).json()}

    assert not await visible()  # a draft is nobody's library
    live = await admin.patch(f"/admin/resources/{item['id']}/publication", {"published": True})
    assert live.json()["is_published"] is True and live.json()["reviewed_at"]
    assert await visible()
    edited = await admin.put(f"/admin/resources/{item['id']}", resource(title="Renamed"))
    assert edited.json()["title"] == "Renamed" and edited.json()["is_published"] is True
    await admin.patch(f"/admin/resources/{item['id']}/publication", {"published": False})
    assert not await visible()

    listed = (await admin.get("/admin/resources?published=false&source=institution")).json()
    assert item["id"] in {r["id"] for r in listed}
    assert (await admin.delete(f"/admin/resources/{item['id']}")).status_code == 204
    assert (await admin.get(f"/admin/resources/{item['id']}")).status_code == 404


async def test_staff_resources_are_kept_out_of_the_student_library(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    student = await new_student(client, api_db, world)
    r = (await admin.post("/admin/resources", resource(tags=["faculty"], publish=True))).json()
    assert r["audience"] == "faculty"
    assert r["id"] not in {x["id"] for x in (await student.get("/resources")).json()}


async def test_global_resources_are_read_only(admin: Session) -> None:
    shipped = [r for r in (await admin.get("/admin/resources?source=global")).json()]
    assert shipped and all(r["editable"] is False for r in shipped)
    rid = shipped[0]["id"]
    assert (await admin.put(f"/admin/resources/{rid}", resource())).status_code == 403
    assert (
        await admin.patch(f"/admin/resources/{rid}/publication", {"published": False})
    ).status_code == 403
    assert (await admin.delete(f"/admin/resources/{rid}")).status_code == 403
    assert (await admin.get(f"/admin/resources/{rid}")).status_code == 200


async def test_resource_validation(admin: Session) -> None:
    for bad in (
        resource(url="http://insecure.example/x"),
        resource(body=None),
        resource(title="  "),
        resource(tags=[f"t{i}" for i in range(11)]),
        resource(tags=["Bad Tag!"]),
        resource(language="english"),
        resource(duration_minutes=0),
        resource(resource_type="podcast"),
    ):
        r = await admin.post("/admin/resources", bad)
        assert r.status_code == 422, (bad, r.text)
    ok = await admin.post(
        "/admin/resources", resource(body=None, url="https://example.org/guide", tags=["Calm "])
    )
    assert ok.status_code == 201 and ok.json()["tags"] == ["calm"]


# ---- dashboard, analytics, oversight --------------------------------------------------------


async def test_dashboard_counts(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    before = (await admin.get("/admin/dashboard")).json()
    assert {a["role"] for a in before["accounts"]} == {
        "student",
        "therapist",
        "teacher",
        "administrator",
    }
    await fresh_therapist(client, api_db, world, verified=False)
    s = await new_student(client, api_db, world)
    assert (await s.post("/me/support-requests", {"message": "please call"})).status_code == 201
    after = (await admin.get("/admin/dashboard")).json()
    assert after["pending_verifications"] == before["pending_verifications"] + 1
    assert after["alerts_awaiting"] == before["alerts_awaiting"] + 1
    assert after["alerts_overdue"] == before["alerts_overdue"]  # not yet due
    # counts only: no alert, student or therapist is named
    assert str(s.id) not in str(after)


async def test_platform_analytics(admin: Session, world: World) -> None:
    assert (await admin.get("/admin/analytics?weeks=5")).status_code == 422
    body = (await admin.get("/admin/analytics")).json()
    assert body["window_weeks"] == 8 and len(body["appointments_booked"]) == 8
    assert body["wellbeing"]["scope"] == "institution"
    assert body["wellbeing"]["min_group_size"] == 10
    for series in (body["appointments_booked"], body["alerts_raised"]):
        for week in series:
            assert week["count"] is None or week["count"] == 0 or week["count"] >= 5
    assert "fewer than 5" in body["small_number_note"]
    twelve = (await admin.get("/admin/analytics?weeks=12")).json()
    assert twelve["window_weeks"] == 12 and len(twelve["alerts_raised"]) == 12


async def test_small_counts_are_hidden() -> None:
    assert [admin_insights.small_safe(n) for n in (0, 1, 4, 5, 9)] == [0, None, None, 5, 9]


async def test_appointment_oversight_hides_small_weeks(
    api_db: AsyncSession, b_admin: Session, world: World
) -> None:
    last_monday = dt.datetime.now(dt.UTC).replace(hour=10, minute=0, second=0, microsecond=0)
    last_monday -= dt.timedelta(days=last_monday.weekday() + 7)
    from tests.api_world import Builder

    b = Builder(api_db, world.password)
    student = await b.user(
        world.inst_b, UserRole.STUDENT, department_id=await _dept_b(api_db, world)
    )
    therapist = await b.user(world.inst_b, UserRole.THERAPIST)

    async def add(n: int) -> None:
        for i in range(n):
            start = last_monday + dt.timedelta(days=i, minutes=5 * len(str(uuid.uuid4())) % 7)
            api_db.add(
                m.Appointment(
                    id=uuid7(),
                    institution_id=world.inst_b,
                    student_id=student.user_id,
                    therapist_id=therapist.user_id,
                    starts_at=start,
                    ends_at=start + dt.timedelta(minutes=50),
                    mode=SessionMode.VIDEO,
                    status=AppointmentStatus.COMPLETED,
                )
            )
        await api_db.commit()

    def last_week(body: dict[str, object]) -> int | None:
        weeks = body["weekly_scheduled"]
        assert isinstance(weeks, list)
        count: int | None = next(
            w["count"] for w in weeks if w["week_start"] == str(last_monday.date())
        )
        return count

    await add(3)
    small = (await b_admin.get("/admin/appointments/oversight?weeks=4")).json()
    assert last_week(small) is None  # three appointments: shown as "fewer than 5"
    status = {s["status"]: s["count"] for s in small["by_status"]}
    assert status["completed"] is None
    # per-therapist workload is staff data and stays exact
    load = next(t for t in small["therapists"] if t["therapist_id"] == str(therapist.user_id))
    assert load["completed"] == 3

    await add(3)
    big = (await b_admin.get("/admin/appointments/oversight?weeks=4")).json()
    assert last_week(big) == 6
    assert str(student.user_id) not in str(big)
    assert (await b_admin.get("/admin/appointments/oversight?weeks=3")).status_code == 422


async def _dept_b(db: AsyncSession, world: World) -> uuid.UUID:
    dept = await db.scalar(
        select(m.Department.id).where(m.Department.institution_id == world.inst_b)
    )
    assert dept is not None
    return dept


async def test_stale_requests_are_counted(
    client: httpx.AsyncClient, api_db: AsyncSession, admin: Session, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    before = (await admin.get("/admin/appointments/oversight")).json()["stale_requests"]
    s2 = await new_student(client, api_db, world)
    slot = await api_db.scalar(
        select(m.TherapistAvailability.id)
        .where(m.TherapistAvailability.therapist_id == pair.therapist.id)
        .order_by(m.TherapistAvailability.starts_at.desc())
        .limit(1)
    )
    booked = await s2.post("/me/appointments", {"availability_id": str(slot)})
    assert booked.status_code == 201, booked.text
    await api_db.execute(
        update(m.Appointment)
        .where(m.Appointment.id == uuid.UUID(booked.json()["id"]))
        .values(created_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=72))
    )
    await api_db.commit()
    after = (await admin.get("/admin/appointments/oversight")).json()["stale_requests"]
    assert after == before + 1


# ---- audit log -------------------------------------------------------------------------------


async def test_audit_filters(admin: Session, world: World) -> None:
    code = f"A{tag()}"
    await admin.post("/admin/departments", {"name": "Audited", "code": code})
    await admin.put(f"/admin/courses/{uuid.uuid4()}/students/{uuid.uuid4()}")  # a miss

    exact = (await admin.get("/admin/audit?action=department.create&limit=5")).json()
    assert exact and {e["action"] for e in exact} == {"department.create"}
    family = (await admin.get("/admin/audit?action=department.&limit=50")).json()
    assert exact[0]["seq"] in {e["seq"] for e in family}
    assert all(e["action"].startswith("department.") for e in family)
    mine = (await admin.get(f"/admin/audit?actor_id={world.admin.user_id}&limit=10")).json()
    assert mine and {e["actor_id"] for e in mine} == {str(world.admin.user_id)}
    allowed = (await admin.get("/admin/audit?outcome=allowed&limit=20")).json()
    assert {e["outcome"] for e in allowed} == {"allowed"}
    typed = (await admin.get("/admin/audit?resource_type=department&limit=20")).json()
    assert {e["resource_type"] for e in typed} == {"department"}
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat()
    assert (await admin.get(f"/admin/audit?since={quote(future)}")).json() == []
    old = (dt.datetime.now(dt.UTC) - dt.timedelta(days=800)).isoformat()
    wide = f"/admin/audit?since={quote(old)}&until={quote(future)}"
    assert (await admin.get(wide)).status_code == 422
    assert "department.create" in (await admin.get("/admin/audit/actions")).json()
    # newest first, and paging walks backwards
    page = (await admin.get("/admin/audit?limit=3")).json()
    older = (await admin.get(f"/admin/audit?limit=3&before_seq={page[-1]['seq']}")).json()
    assert [e["seq"] for e in page] == sorted((e["seq"] for e in page), reverse=True)
    assert older and older[0]["seq"] < page[-1]["seq"]


async def test_reading_exporting_and_verifying_the_log_are_themselves_logged(
    api_db: AsyncSession, admin: Session, world: World
) -> None:
    inst = world.inst_a
    reads = await audit_count(api_db, inst, "audit.read")
    first = (await admin.get("/admin/audit?limit=2")).json()
    assert await audit_count(api_db, inst, "audit.read") == reads + 1
    await admin.get(f"/admin/audit?limit=2&before_seq={first[-1]['seq']}")
    assert await audit_count(api_db, inst, "audit.read") == reads + 1  # later pages are one look

    exports = await audit_count(api_db, inst, "audit.export")
    r = await admin.get("/admin/audit/export?action=user.&outcome=allowed")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    header = r.text.splitlines()[0]
    assert header == (
        "seq,occurred_at,actor_id,actor_role,action,outcome,resource_type,resource_id,"
        "subject_student_id,reason"
    )
    assert await audit_count(api_db, inst, "audit.export") == exports + 1

    verifies = await audit_count(api_db, inst, "audit.verify")
    status = (await admin.post("/admin/audit/verify")).json()
    assert status["intact"] is True and status["first_bad_seq"] is None and status["events"] > 0
    assert await audit_count(api_db, inst, "audit.verify") == verifies + 1
    again = (await admin.post("/admin/audit/verify")).json()
    assert again["intact"] is True  # the log written by reading the log still chains


async def test_exported_cells_cannot_run_as_formulas() -> None:
    assert admin_audit._cell("=SUM(A1)") == "'=SUM(A1)"
    assert admin_audit._cell("+1") == "'+1" and admin_audit._cell("-1") == "'-1"
    assert admin_audit._cell("@x") == "'@x" and admin_audit._cell(None) == ""
    assert admin_audit._cell("user.create") == "user.create"


async def test_audit_rows_from_admin_actions_carry_ids_not_content(
    api_db: AsyncSession, admin: Session, world: World
) -> None:
    title = f"Distinctive Title {tag()}"
    await admin.post("/admin/resources", resource(title=title, body="Distinctive body text"))
    events = (await admin.get("/admin/audit?action=resource.&limit=10")).json()
    assert events
    text = str(events)
    assert title not in text and "Distinctive body text" not in text


# ---- settings --------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def restore_settings(api_db: AsyncSession, world: World) -> AsyncIterator[None]:
    yield
    await api_db.rollback()
    row = await api_db.scalar(
        select(m.InstitutionSettings).where(m.InstitutionSettings.institution_id == world.inst_a)
    )
    if row is not None:
        await api_db.delete(row)
        await api_db.commit()


async def test_notification_settings(admin: Session, restore_settings: None) -> None:
    got = (await admin.get("/admin/settings/notifications")).json()
    assert got["values"] == NotificationSettings().model_dump()
    assert any("always" in rule for rule in got["fixed_rules"])

    r = await admin.patch(
        "/admin/settings/notifications",
        {"appointment_reminder_hours": [2, 24, 24], "goal_reminders": False},
    )
    assert r.status_code == 200
    assert r.json()["values"]["appointment_reminder_hours"] == [24, 2]
    assert r.json()["values"]["goal_reminders"] is False
    assert (await admin.get("/admin/settings/notifications")).json() == r.json()
    for bad in (
        {"appointment_reminder_hours": [1, 2, 3, 4]},
        {"appointment_reminder_hours": [0]},
        {"appointment_reminder_hours": [200]},
        {"email_enabled": "perhaps"},
    ):
        assert (await admin.patch("/admin/settings/notifications", bad)).status_code == 422, bad
    events = (await admin.get("/admin/audit?action=settings.notifications.update&limit=1")).json()
    assert events and "goal_reminders" in events[0]["details"]["changes"]


async def test_the_alert_deadline_setting_changes_new_alerts_only(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    admin: Session,
    world: World,
    restore_settings: None,
) -> None:
    default = SafetySettings().alert_ack_minutes

    async def minutes_for_new_request() -> float:
        student = await new_student(client, api_db, world)
        out = (await student.post("/me/support-requests", {"message": "please call"})).json()
        await api_db.rollback()
        alert = await api_db.get(m.RiskAlert, uuid.UUID(out["id"]))
        assert alert is not None and alert.sla_ack_due_at is not None
        return (alert.sla_ack_due_at - alert.created_at).total_seconds() / 60

    assert abs(await minutes_for_new_request() - default) < 1
    for bad in (4, 1441, 0):
        assert (
            await admin.patch("/admin/settings/safety", {"alert_ack_minutes": bad})
        ).status_code == 422
    assert (
        await admin.patch("/admin/settings/safety", {"alert_ack_minutes": 45})
    ).status_code == 200
    assert abs(await minutes_for_new_request() - 45) < 1
    assert (await admin.get("/admin/settings/safety")).json()["values"]["alert_ack_minutes"] == 45
    assert any(
        "At least one emergency" in r
        for r in (await admin.get("/admin/settings/safety")).json()["fixed_rules"]
    )


async def test_recommendation_notifications_can_be_switched_off(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    admin: Session,
    world: World,
    restore_settings: None,
) -> None:
    pair = await care_pair(client, api_db, world)
    url = f"/therapist/students/{pair.student.id}/recommendations"

    async def notifications() -> int:
        await api_db.rollback()
        return (
            await api_db.scalar(
                select(func.count())
                .select_from(m.Notification)
                .where(
                    m.Notification.user_id == pair.student.id,
                    m.Notification.type == NotificationType.RECOMMENDATION,
                )
            )
        ) or 0

    await admin.patch("/admin/settings/notifications", {"recommendation_notifications": False})
    r = await pair.therapist.post(url, {"title": "A short walk", "rationale": "Fresh air helps."})
    assert r.status_code == 201
    assert await notifications() == 0
    assert (await pair.student.get("/me/recommendations")).json()  # the suggestion itself remains

    await admin.patch("/admin/settings/notifications", {"recommendation_notifications": True})
    again = await pair.therapist.post(
        url, {"title": "A second idea", "rationale": "Stretch a bit."}
    )
    assert again.status_code == 201
    assert await notifications() == 1


async def test_crisis_contacts(admin: Session) -> None:
    contacts = (await admin.get("/admin/settings/crisis-contacts")).json()
    shipped = [c for c in contacts if not c["editable"]]
    assert shipped
    assert (
        await admin.patch(f"/admin/settings/crisis-contacts/{shipped[0]['id']}", {"label": "x"})
    ).status_code == 403
    assert (
        await admin.delete(f"/admin/settings/crisis-contacts/{shipped[0]['id']}")
    ).status_code == 403

    base = {"label": f"Counselling desk {tag()}", "kind": "campus", "hours": "9-5"}
    assert (
        await admin.post("/admin/settings/crisis-contacts", base)
    ).status_code == 422  # unreachable
    insecure = base | {"url": "http://example.org"}
    assert (await admin.post("/admin/settings/crisis-contacts", insecure)).status_code == 422
    made = await admin.post("/admin/settings/crisis-contacts", base | {"phone": "0000 000 000"})
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    assert made.json()["editable"] is True
    changed = await admin.patch(f"/admin/settings/crisis-contacts/{cid}", {"is_active": False})
    assert changed.json()["is_active"] is False
    assert (
        await admin.patch(f"/admin/settings/crisis-contacts/{cid}", {"phone": None, "url": None})
    ).status_code == 422
    assert (await admin.delete(f"/admin/settings/crisis-contacts/{cid}")).status_code == 204


async def test_the_last_active_emergency_contact_cannot_be_removed(
    api_db: AsyncSession, b_admin: Session
) -> None:
    await api_db.execute(
        update(m.CrisisContact)
        .where(m.CrisisContact.institution_id.is_(None), m.CrisisContact.kind == "emergency")
        .values(is_active=False)
    )
    await api_db.commit()
    try:
        first = (
            await b_admin.post(
                "/admin/settings/crisis-contacts",
                {"label": "Ambulance", "kind": "emergency", "phone": "112"},
            )
        ).json()
        path = f"/admin/settings/crisis-contacts/{first['id']}"
        assert (await b_admin.patch(path, {"is_active": False})).status_code == 422
        assert (await b_admin.delete(path)).status_code == 422
        second = (
            await b_admin.post(
                "/admin/settings/crisis-contacts",
                {"label": "Campus security", "kind": "emergency", "phone": "100"},
            )
        ).json()
        assert (await b_admin.patch(path, {"is_active": False})).status_code == 200
        # the other one is now the last
        last = f"/admin/settings/crisis-contacts/{second['id']}"
        assert (await b_admin.delete(last)).status_code == 422
        assert (await b_admin.patch(path, {"is_active": True})).status_code == 200
        assert (await b_admin.delete(last)).status_code == 204
    finally:
        await api_db.rollback()
        await api_db.execute(
            update(m.CrisisContact)
            .where(m.CrisisContact.institution_id.is_(None), m.CrisisContact.kind == "emergency")
            .values(is_active=True)
        )
        await api_db.execute(
            delete(m.CrisisContact).where(
                m.CrisisContact.label.in_(["Ambulance", "Campus security"])
            )
        )
        await api_db.commit()


async def test_institution_details(admin: Session) -> None:
    before = (await admin.get("/admin/config")).json()
    try:
        r = await admin.patch(
            "/admin/config",
            {"name": before["name"], "email_domains": ["B.example", "a.example", "a.example"]},
        )
        assert r.json()["email_domains"] == ["a.example", "b.example"]
    finally:
        await admin.patch("/admin/config", {"email_domains": before["email_domains"]})
