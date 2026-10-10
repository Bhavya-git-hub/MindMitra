"""Cross-role authorization through the real API and a real PostgreSQL database.

Every test here attempts access one role (or tenant) must not have and checks that it fails,
alongside the positive case that proves the route works for the role that should have it.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AuditOutcome, UserRole
from tests.api_helpers import call, token_for
from tests.api_world import Actor, Builder, World
from tests.student_helpers import sign_in

pytestmark = pytest.mark.asyncio


def _actor(world: World, name: str) -> Actor:
    actor: Actor = getattr(world, name)
    return actor


async def _tok(client: httpx.AsyncClient, world: World, name: str) -> str:
    return await token_for(client, _actor(world, name), world.password)


# ---- role x route matrix ---------------------------------------------------------------------

ROLES = ("student", "therapist", "teacher", "admin")

# path template -> roles that get 200; every other role must get 403.
MATRIX: dict[str, set[str]] = {
    "/me": {"student", "therapist", "teacher", "admin"},
    "/me/wellness/mood-entries": {"student"},
    "/me/appointments": {"student"},
    "/me/ai-conversations": {"student"},
    "/students": {"therapist"},
    "/students/{student}/mood-entries": {"therapist"},
    "/students/{student}/therapy-notes": {"therapist"},
    "/therapist/appointments": {"therapist"},
    "/insights/mood-summary": {"teacher", "admin"},
    "/admin/users": {"admin"},
    "/admin/config": {"admin"},
    "/admin/audit": {"admin"},
}


@pytest.mark.parametrize("path", sorted(MATRIX))
@pytest.mark.parametrize("role", ROLES)
async def test_role_route_matrix(
    client: httpx.AsyncClient, world: World, role: str, path: str
) -> None:
    url = path.format(student=world.student.user_id)
    r = await call(client, "GET", url, token=await _tok(client, world, role))
    expected = 200 if role in MATRIX[path] else 403
    assert r.status_code == expected, f"{role} GET {url}: {r.status_code} {r.text}"
    if expected == 403:
        assert r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("path", sorted(MATRIX))
async def test_anonymous_is_rejected_everywhere(
    client: httpx.AsyncClient, world: World, path: str
) -> None:
    r = await call(client, "GET", path.format(student=world.student.user_id))
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_anonymous_writes_are_rejected(client: httpx.AsyncClient, world: World) -> None:
    for method, path, body in (
        ("PATCH", f"/appointments/{world.appointment}", {"status": "confirmed"}),
        (
            "POST",
            "/admin/users",
            {"email": "x@test.example", "full_name": "X", "role": "administrator"},
        ),
        ("PATCH", f"/admin/users/{world.student.user_id}", {"status": "suspended"}),
        ("PATCH", "/admin/config", {"name": "Hijacked"}),
        ("POST", "/auth/logout", None),
    ):
        r = await call(client, method, path, json=body)
        assert r.status_code == 401, (method, path, r.text)


# ---- students: own data only -----------------------------------------------------------------


async def test_student_sees_only_own_wellness_and_appointments(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    tok = await _tok(client, world, "other_student")
    moods = (await call(client, "GET", "/me/wellness/mood-entries", token=tok)).json()
    own_ids = set(
        await api_db.scalars(
            select(m.MoodEntry.id).where(m.MoodEntry.student_id == world.other_student.user_id)
        )
    )
    assert moods and {uuid.UUID(e["id"]) for e in moods} <= own_ids

    tok = await _tok(client, world, "unconsented_student")
    appts = (await call(client, "GET", "/me/appointments", token=tok)).json()
    assert {a["student_id"] for a in appts} == {str(world.unconsented_student.user_id)}


async def test_student_cannot_reach_another_students_records(
    client: httpx.AsyncClient, world: World
) -> None:
    tok = await _tok(client, world, "other_student")
    for path in ("mood-entries", "therapy-notes"):
        r = await call(client, "GET", f"/students/{world.student.user_id}/{path}", token=tok)
        assert r.status_code == 403
    r = await call(client, "GET", "/students", token=tok)
    assert r.status_code == 403


async def test_student_ai_conversations_are_their_own(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    tok = await _tok(client, world, "student")
    convs = (await call(client, "GET", "/me/ai-conversations", token=tok)).json()
    owners = set(
        await api_db.scalars(
            select(m.AIConversation.student_id).where(
                m.AIConversation.id.in_([uuid.UUID(c["id"]) for c in convs])
            )
        )
    )
    assert owners <= {world.student.user_id}
    assert all(set(c) == {"id", "status", "started_at", "ended_at"} for c in convs)


async def test_student_cannot_manage_appointments(client: httpx.AsyncClient, world: World) -> None:
    tok = await _tok(client, world, "unconsented_student")
    r = await call(
        client,
        "PATCH",
        f"/appointments/{world.appointment}",
        token=tok,
        json={"status": "cancelled"},
    )
    assert r.status_code == 403


# ---- therapists: assigned students only ------------------------------------------------------


async def test_therapist_lists_only_assigned_students(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    rows = (
        await call(client, "GET", "/students", token=await _tok(client, world, "therapist"))
    ).json()
    ids = {r["student_id"] for r in rows}
    linked = {
        str(sid)
        for sid in await api_db.scalars(
            select(m.CareTeamMember.student_id).where(
                m.CareTeamMember.therapist_id == world.therapist.user_id,
                m.CareTeamMember.ends_at.is_(None),
            )
        )
    }
    others = {
        str(sid)
        for sid in await api_db.scalars(
            select(m.CareTeamMember.student_id).where(
                m.CareTeamMember.therapist_id != world.therapist.user_id
            )
        )
    } - linked
    assert others, "seed should give other therapists their own students"
    assert ids == linked
    assert str(world.student.user_id) in ids
    assert str(world.unconsented_student.user_id) in ids
    assert str(world.other_student.user_id) not in ids
    assert str(world.b_student.user_id) not in ids


async def test_therapist_reads_consented_mood_without_private_note(
    client: httpx.AsyncClient, world: World
) -> None:
    tok = await _tok(client, world, "therapist")
    r = await call(client, "GET", f"/students/{world.student.user_id}/mood-entries", token=tok)
    assert r.status_code == 200
    assert r.json(), "seeded student should have mood entries"
    assert all("note" not in e for e in r.json())


async def test_therapist_needs_consent_for_wellness(
    client: httpx.AsyncClient, world: World
) -> None:
    tok = await _tok(client, world, "therapist")
    path = f"/students/{world.unconsented_student.user_id}/mood-entries"
    assert (await call(client, "GET", path, token=tok)).status_code == 403


@pytest.mark.parametrize("path", ["mood-entries", "therapy-notes"])
async def test_unassigned_therapist_gets_not_found(
    client: httpx.AsyncClient, world: World, path: str
) -> None:
    tok = await _tok(client, world, "therapist")
    r = await call(client, "GET", f"/students/{world.other_student.user_id}/{path}", token=tok)
    assert r.status_code == 404
    tok = await _tok(client, world, "other_therapist")
    r = await call(client, "GET", f"/students/{world.student.user_id}/{path}", token=tok)
    assert r.status_code == 404


async def test_therapy_notes_only_from_the_author(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    tok = await _tok(client, world, "therapist")
    r = await call(client, "GET", f"/students/{world.student.user_id}/therapy-notes", token=tok)
    assert r.status_code == 200
    notes = r.json()
    assert notes
    authors = set(
        await api_db.scalars(
            select(m.TherapyNote.author_id).where(
                m.TherapyNote.id.in_([uuid.UUID(n["id"]) for n in notes])
            )
        )
    )
    assert authors == {world.therapist.user_id}


async def test_unknown_student_is_not_found(client: httpx.AsyncClient, world: World) -> None:
    tok = await _tok(client, world, "therapist")
    r = await call(client, "GET", f"/students/{uuid.uuid4()}/therapy-notes", token=tok)
    assert r.status_code == 404


async def test_therapist_manages_only_own_appointments(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    b = Builder(api_db, world.password)
    appt = await b.appointment(
        world.inst_a, world.unconsented_student, world.therapist, days_ahead=500
    )
    other = await b.appointment(
        world.inst_a, world.unconsented_student, world.other_therapist, days_ahead=501
    )
    await api_db.commit()

    other_tok = await _tok(client, world, "other_therapist")
    r = await call(
        client, "PATCH", f"/appointments/{appt}", token=other_tok, json={"status": "confirmed"}
    )
    assert r.status_code == 404
    tok = await _tok(client, world, "therapist")
    r = await call(
        client, "PATCH", f"/appointments/{other}", token=tok, json={"status": "confirmed"}
    )
    assert r.status_code == 404

    r = await call(
        client, "PATCH", f"/appointments/{appt}", token=tok, json={"status": "confirmed"}
    )
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    r = await call(
        client, "PATCH", f"/appointments/{appt}", token=tok, json={"status": "confirmed"}
    )
    assert r.status_code == 409  # confirmed -> confirmed is not a transition
    r = await call(
        client, "PATCH", f"/appointments/{appt}", token=tok, json={"status": "cancelled"}
    )
    assert r.status_code == 200 and r.json()["status"] == "cancelled"

    listed = (await call(client, "GET", "/therapist/appointments", token=tok)).json()
    assert {a["therapist_id"] for a in listed} == {str(world.therapist.user_id)}


# ---- teachers: aggregates of their own department only ---------------------------------------


@pytest.mark.parametrize("path", ["therapy-notes", "mood-entries"])
async def test_teacher_cannot_read_clinical_or_wellness_records(
    client: httpx.AsyncClient, world: World, path: str
) -> None:
    tok = await _tok(client, world, "teacher")
    r = await call(client, "GET", f"/students/{world.student.user_id}/{path}", token=tok)
    assert r.status_code == 403


async def test_teacher_cannot_read_ai_conversations(
    client: httpx.AsyncClient, world: World
) -> None:
    tok = await _tok(client, world, "teacher")
    assert (await call(client, "GET", "/me/ai-conversations", token=tok)).status_code == 403


async def test_teacher_insights_limited_to_own_department(
    client: httpx.AsyncClient, world: World
) -> None:
    tok = await _tok(client, world, "teacher")
    own = await call(client, "GET", "/insights/mood-summary", token=tok)
    assert own.status_code == 200
    assert own.json()["department_id"] == str(world.dept_a)
    other = await call(
        client, "GET", f"/insights/mood-summary?department_id={world.other_dept_a}", token=tok
    )
    assert other.status_code == 403


async def test_small_cohorts_are_suppressed_and_large_ones_aggregated(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    b = Builder(api_db, world.password)
    dept = m.Department(
        institution_id=world.inst_a, name="Cohort Dept", code=f"C{uuid.uuid4().hex[:5]}"
    )
    api_db.add(dept)
    await api_db.flush()
    teacher = await b.user(world.inst_a, UserRole.TEACHER, department_id=dept.id)
    students = [
        await b.user(world.inst_a, UserRole.STUDENT, department_id=dept.id) for _ in range(10)
    ]
    for s in students:
        await b.aggregate_consent(world.inst_a, s)
    # Nine days back: inside the last four completed weeks, never the week in progress.
    for s in students[:9]:
        await b.mood_entry(world.inst_a, s, 3, days_ago=9)
    await api_db.commit()

    tok = await token_for(client, teacher, world.password)
    r = (await call(client, "GET", "/insights/mood-summary", token=tok)).json()
    assert r["suppressed"] is True and r["cohort_size"] is None and r["average_mood"] is None

    await b.mood_entry(world.inst_a, students[9], 5, days_ago=9)
    await api_db.commit()
    # The window closed at the first read, so a late entry in it does not change the stored answer.
    r = (await call(client, "GET", "/insights/mood-summary", token=tok)).json()
    assert r["suppressed"] is True
    # A consent change drops the stored window; the next read is computed from live data.
    leaver = await sign_in(client, students[9], world.password)
    for granted in (False, True):
        r = await leaver.put("/me/consents/anonymous_aggregate_research", {"granted": granted})
        assert r.status_code == 200, r.text
    r = (await call(client, "GET", "/insights/mood-summary", token=tok)).json()
    assert r["suppressed"] is False and r["cohort_size"] == 10
    assert r["average_mood"] == pytest.approx(3.2)
    assert set(r) == {
        "department_id",
        "window_days",
        "cohort_size",
        "average_mood",
        "suppressed",
        "disclaimer",
    }


# ---- admins: accounts and configuration, never clinical content -------------------------------


@pytest.mark.parametrize("path", ["therapy-notes", "mood-entries"])
async def test_admin_cannot_read_clinical_or_wellness_records(
    client: httpx.AsyncClient, world: World, path: str
) -> None:
    tok = await _tok(client, world, "admin")
    r = await call(client, "GET", f"/students/{world.student.user_id}/{path}", token=tok)
    assert r.status_code == 403


async def test_admin_cannot_read_ai_conversations(client: httpx.AsyncClient, world: World) -> None:
    tok = await _tok(client, world, "admin")
    assert (await call(client, "GET", "/me/ai-conversations", token=tok)).status_code == 403


async def test_admin_cannot_manage_appointments(client: httpx.AsyncClient, world: World) -> None:
    tok = await _tok(client, world, "admin")
    r = await call(
        client,
        "PATCH",
        f"/appointments/{world.appointment}",
        token=tok,
        json={"status": "cancelled"},
    )
    assert r.status_code == 403


async def test_admin_audit_view_is_metadata_only(client: httpx.AsyncClient, world: World) -> None:
    # Make sure there is a clinical read in the log first.
    await call(
        client,
        "GET",
        f"/students/{world.student.user_id}/therapy-notes",
        token=await _tok(client, world, "therapist"),
    )
    tok = await _tok(client, world, "admin")
    events = (await call(client, "GET", "/admin/audit?limit=200", token=tok)).json()
    assert events
    allowed_keys = {
        "seq",
        "occurred_at",
        "actor_id",
        "actor_role",
        "action",
        "outcome",
        "resource_type",
        "resource_id",
        "subject_student_id",
        "reason",
        "details",
    }
    assert all(set(e) == allowed_keys for e in events)
    for e in events:
        assert not {"body", "content", "note", "text"} & set(e["details"])


async def test_admin_cannot_change_own_status(client: httpx.AsyncClient, world: World) -> None:
    tok = await _tok(client, world, "admin")
    r = await call(
        client,
        "PATCH",
        f"/admin/users/{world.admin.user_id}",
        token=tok,
        json={"status": "suspended"},
    )
    assert r.status_code == 403


# ---- tenants are isolated --------------------------------------------------------------------


async def test_other_tenant_therapist_cannot_reach_students(
    client: httpx.AsyncClient, world: World
) -> None:
    tok = await _tok(client, world, "b_therapist")
    for path in ("mood-entries", "therapy-notes"):
        r = await call(client, "GET", f"/students/{world.student.user_id}/{path}", token=tok)
        assert r.status_code == 404
    rows = (await call(client, "GET", "/students", token=tok)).json()
    assert {r["student_id"] for r in rows} == {str(world.b_student.user_id)}
    r = await call(
        client,
        "PATCH",
        f"/appointments/{world.appointment}",
        token=tok,
        json={"status": "confirmed"},
    )
    assert r.status_code == 404


async def test_therapist_cannot_reach_other_tenant_appointment(
    client: httpx.AsyncClient, world: World
) -> None:
    tok = await _tok(client, world, "therapist")
    r = await call(
        client,
        "PATCH",
        f"/appointments/{world.b_appointment}",
        token=tok,
        json={"status": "confirmed"},
    )
    assert r.status_code == 404


async def test_other_tenant_admin_sees_only_own_institution(
    client: httpx.AsyncClient, world: World
) -> None:
    tok = await _tok(client, world, "b_admin")
    users = (await call(client, "GET", "/admin/users?limit=200", token=tok)).json()
    assert users and {u["id"] for u in users} <= {
        str(a.user_id) for a in (world.b_student, world.b_therapist, world.b_teacher, world.b_admin)
    }
    cfg = (await call(client, "GET", "/admin/config", token=tok)).json()
    assert cfg["id"] == str(world.inst_b)
    events = (await call(client, "GET", "/admin/audit?limit=200", token=tok)).json()
    a_actors = {str(world.student.user_id), str(world.therapist.user_id), str(world.admin.user_id)}
    assert not {e["actor_id"] for e in events} & a_actors

    r = await call(
        client,
        "PATCH",
        f"/admin/users/{world.student.user_id}",
        token=tok,
        json={"status": "suspended"},
    )
    assert r.status_code == 404
    r = await call(client, "GET", f"/insights/mood-summary?department_id={world.dept_a}", token=tok)
    assert r.status_code == 404


async def test_other_tenant_teacher_cannot_query_foreign_department(
    client: httpx.AsyncClient, world: World
) -> None:
    tok = await _tok(client, world, "b_teacher")
    r = await call(client, "GET", f"/insights/mood-summary?department_id={world.dept_a}", token=tok)
    assert r.status_code == 403


# ---- denials and clinical reads are audited --------------------------------------------------


async def test_denials_are_audited(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    tok = await _tok(client, world, "other_therapist")
    await call(client, "GET", f"/students/{world.student.user_id}/therapy-notes", token=tok)
    tok = await _tok(client, world, "teacher")
    await call(client, "GET", f"/students/{world.student.user_id}/therapy-notes", token=tok)

    rows = (
        await api_db.execute(
            select(m.AuditLog.actor_id, m.AuditLog.reason, m.AuditLog.subject_student_id).where(
                m.AuditLog.outcome == AuditOutcome.DENIED,
                m.AuditLog.actor_id.in_([world.other_therapist.user_id, world.teacher.user_id]),
            )
        )
    ).all()
    reasons = {(r.actor_id, r.reason) for r in rows}
    assert (world.other_therapist.user_id, "no_care_team_link") in reasons
    assert (world.teacher.user_id, "missing_permission") in reasons


async def test_therapy_note_reads_are_audited(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    tok = await _tok(client, world, "therapist")
    before = await api_db.scalar(
        select(m.AuditLog.seq)
        .where(m.AuditLog.institution_id == world.inst_a)
        .order_by(m.AuditLog.seq.desc())
        .limit(1)
    )
    r = await call(client, "GET", f"/students/{world.student.user_id}/therapy-notes", token=tok)
    assert r.status_code == 200
    row = (
        await api_db.execute(
            select(m.AuditLog).where(
                m.AuditLog.seq > (before or 0),
                m.AuditLog.action == "therapy_note.list",
                m.AuditLog.actor_id == world.therapist.user_id,
            )
        )
    ).scalar_one()
    assert row.outcome is AuditOutcome.ALLOWED
    assert row.subject_student_id == world.student.user_id
    assert row.details == {"count": len(r.json())}
