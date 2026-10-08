"""Cross-tenant integrity: a child row can never reference a parent in another institution.

Application code and (later) row-level-security policies are the first line of defence; these
tests prove the database itself refuses mismatched ``institution_id`` values, so a bug in
either cannot silently link two institutions' data.
"""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    CareRole,
    ConsentScope,
    NotificationType,
    SessionMode,
)
from app.infrastructure.db.ids import uuid7
from tests import helpers
from tests.test_constraints import NOW, rejected

FK = "foreign key constraint"


async def test_wellness_row_cannot_use_another_institutions_id(session: AsyncSession) -> None:
    s = await helpers.any_student(session)
    other, _ = await helpers.other_institution(session)
    await rejected(
        session,
        m.MoodEntry(institution_id=other.id, student_id=s.user_id, mood_score=3),
        match="fk_mood_entries_student_id_institution_id_students",
    )
    await rejected(
        session,
        m.JournalEntry(institution_id=other.id, student_id=s.user_id, body="x"),
        match="fk_journal_entries_student_id_institution_id_students",
    )
    await rejected(
        session,
        m.AIConversation(id=uuid7(), institution_id=other.id, student_id=s.user_id),
        match="fk_ai_conversations_student_id_institution_id_students",
    )


async def test_course_department_must_belong_to_the_same_institution(
    session: AsyncSession,
) -> None:
    inst = await helpers.institution(session)
    _, other_dept = await helpers.other_institution(session)
    await rejected(
        session,
        m.Course(
            institution_id=inst.id, department_id=other_dept.id, code="X1", title="t", term="t"
        ),
        match="fk_courses_department_institution",
    )


async def test_enrollment_student_and_course_must_share_a_tenant(session: AsyncSession) -> None:
    other, dept = await helpers.other_institution(session)
    foreign_student = await helpers.student_in(session, other, dept)
    inst = await helpers.institution(session)
    course = await helpers.first(session, select(m.Course))
    await rejected(
        session,
        m.CourseEnrollment(
            institution_id=inst.id, course_id=course.id, student_id=foreign_student.user_id
        ),
        match="fk_course_enrollments_student_id_institution_id_students",
    )
    await rejected(
        session,
        m.CourseEnrollment(
            institution_id=other.id, course_id=course.id, student_id=foreign_student.user_id
        ),
        match="fk_course_enrollments_course_id_institution_id_courses",
    )


async def test_care_team_cannot_link_students_and_therapists_across_tenants(
    session: AsyncSession,
) -> None:
    s = await helpers.new_student(session)
    other, _ = await helpers.other_institution(session)
    foreign_therapist = await helpers.therapist_in(session, other)
    await rejected(
        session,
        m.CareTeamMember(
            institution_id=s.institution_id,
            student_id=s.user_id,
            therapist_id=foreign_therapist.user_id,
            role=CareRole.PRIMARY,
            starts_at=NOW,
        ),
        match="fk_care_team_members_therapist_id_institution_id_therapists",
    )


async def test_message_between_different_tenants_is_rejected(session: AsyncSession) -> None:
    s = await helpers.any_student(session)
    other, _ = await helpers.other_institution(session)
    foreign_therapist = await helpers.therapist_in(session, other)
    await rejected(
        session,
        m.Message(
            institution_id=s.institution_id,
            student_id=s.user_id,
            therapist_id=foreign_therapist.user_id,
            sender_id=s.user_id,
            body="hello",
        ),
        match="fk_messages_therapist_id_institution_id_therapists",
    )


async def test_appointment_and_availability_cannot_cross_tenants(session: AsyncSession) -> None:
    s = await helpers.any_student(session)
    other, _ = await helpers.other_institution(session)
    foreign_therapist = await helpers.therapist_in(session, other)
    await rejected(
        session,
        m.Appointment(
            institution_id=s.institution_id,
            student_id=s.user_id,
            therapist_id=foreign_therapist.user_id,
            starts_at=NOW,
            ends_at=NOW + dt.timedelta(hours=1),
            mode=SessionMode.VIDEO,
        ),
        match="fk_appointments_therapist_id_institution_id_therapists",
    )
    await rejected(
        session,
        m.TherapistAvailability(
            institution_id=s.institution_id,
            therapist_id=foreign_therapist.user_id,
            starts_at=NOW,
            ends_at=NOW + dt.timedelta(hours=1),
        ),
        match="fk_therapist_availability_therapist_id_institution_id",  # name is truncated by PG,
    )


async def test_clinical_note_cannot_claim_another_tenant(session: AsyncSession) -> None:
    ts = await helpers.completed_session(session)
    other, _ = await helpers.other_institution(session)
    await rejected(
        session,
        m.TherapyNote(
            institution_id=other.id,
            session_id=ts.id,
            author_id=ts.therapist_id,
            version=99,
            body="confidential",
        ),
        match="fk_therapy_notes_session_author",
    )


async def test_alert_consent_notification_and_share_cannot_cross_tenants(
    session: AsyncSession,
) -> None:
    from tests.test_constraints import _alert

    s = await helpers.new_student(session)  # no existing consent rows
    other, _ = await helpers.other_institution(session)
    foreign_therapist = await helpers.therapist_in(session, other)
    await rejected(
        session,
        _alert(s, assigned_to=foreign_therapist.user_id),
        match="fk_risk_alerts_assigned_to_institution_id_therapists",
    )
    await rejected(
        session,
        m.Consent(
            institution_id=other.id,
            user_id=s.user_id,
            scope=ConsentScope.TERMS_AND_PRIVACY,
            policy_version="v1",
        ),
        match="fk_consents_user_id_institution_id_users",
    )
    await rejected(
        session,
        m.Notification(
            institution_id=other.id, user_id=s.user_id, type=NotificationType.SYSTEM, title="t"
        ),
        match="fk_notifications_user_id_institution_id_users",
    )
    entry = m.JournalEntry(
        id=uuid7(), institution_id=s.institution_id, student_id=s.user_id, body="private"
    )
    session.add(entry)
    await session.flush()
    th = await helpers.any_therapist(session)
    await rejected(
        session,
        m.JournalShare(institution_id=other.id, entry_id=entry.id, therapist_id=th.user_id),
        match="fk_journal_shares_entry_id_institution_id_journal_entries",
    )


# Plain single-column references to tenant-owned rows that are intentionally *not* composite:
#   appointments.cancelled_by  - SET NULL cannot null a composite key's tenant column
#   messages.sender_id         - must be the student or therapist, both tenant-checked above
#   resources.reviewed_by      - global resources have no tenant
#   recommendations.resource_id - resources may be global (NULL tenant)
_EXEMPT = {
    ("therapy.appointments", "cancelled_by"),
    ("comm.messages", "sender_id"),
    ("wellness.resources", "reviewed_by"),
    ("ai.recommendations", "resource_id"),
    # (availability_id, therapist_id) -> availability: the slot's tenant is its therapist's,
    # which the appointment's own therapist composite FK already ties to this tenant.
    ("therapy.appointments", "availability_id"),
}


async def test_every_tenant_scoped_foreign_key_includes_institution_id(
    engine: AsyncEngine,
) -> None:
    """Catch-all: new tables cannot add a plain FK between two tenant-scoped tables."""
    sql = """
    SELECT cn.nspname||'.'||c.relname, k.conname, a.attname
    FROM pg_constraint k
    JOIN pg_class c ON c.oid = k.conrelid
    JOIN pg_namespace cn ON cn.oid = c.relnamespace
    JOIN pg_class p ON p.oid = k.confrelid
    JOIN pg_attribute ci ON ci.attrelid = c.oid AND ci.attname = 'institution_id'
         AND NOT ci.attisdropped
    JOIN pg_attribute pi ON pi.attrelid = p.oid AND pi.attname = 'institution_id'
         AND NOT pi.attisdropped
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.conkey[1]
    WHERE k.contype = 'f'
      AND cn.nspname IN ('iam','org','wellness','therapy','comm','ai','safety','consent','notify')
      AND NOT (ci.attnum = ANY (k.conkey))
    """
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql))).all()
    offenders = [(t, col) for t, _name, col in rows if (t, col) not in _EXEMPT]
    assert not offenders, (
        f"foreign keys between tenant-scoped tables without institution_id: {offenders}"
    )


@pytest.mark.parametrize(
    "table",
    [
        "org.care_team_members",
        "org.course_enrollments",
        "org.course_teachers",
        "wellness.journal_shares",
    ],
)
async def test_join_tables_carry_a_tenant_column(engine: AsyncEngine, table: str) -> None:
    schema, name = table.split(".")
    async with engine.connect() as conn:
        nullable = (
            await conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema=:s AND table_name=:t AND column_name='institution_id'"
                ),
                {"s": schema, "t": name},
            )
        ).scalar_one()
    assert nullable == "NO"


def test_uuid7_is_time_ordered_and_unique() -> None:
    ids = [uuid7() for _ in range(200)]
    assert len(set(ids)) == 200
    assert all(i.version == 7 for i in ids)
    stamps = [i.int >> 80 for i in ids]  # 48-bit millisecond prefix
    assert stamps == sorted(stamps)
    assert all(i.variant == uuid.RFC_4122 for i in ids)
    assert isinstance(ids[0], uuid.UUID)
