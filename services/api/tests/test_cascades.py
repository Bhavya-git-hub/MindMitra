"""Delete behaviour: erasure cascades for wellness data, RESTRICT for clinical records."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AIMessageRole,
    AuditOutcome,
    ConsentScope,
    NotificationType,
    RecommendationSource,
    UserRole,
)
from app.infrastructure.db.ids import uuid7
from tests import helpers


async def test_deleting_a_user_erases_their_wellness_data(session: AsyncSession) -> None:
    s = await helpers.new_student(session)
    inst_id, sid = s.institution_id, s.user_id
    session.add(m.Credential(user_id=sid, password_hash="$argon2id$v=19$m=1,t=1,p=1$c2FsdA$aGFzaA"))
    session.add(m.MoodEntry(institution_id=inst_id, student_id=sid, mood_score=3, note="private"))
    session.add(
        m.JournalEntry(id=(jid := uuid7()), institution_id=inst_id, student_id=sid, body="private")
    )
    th = await helpers.any_therapist(session)
    session.add(m.WellnessGoal(institution_id=inst_id, student_id=sid, title="g", category="sleep"))  # type: ignore[arg-type]
    conv = m.AIConversation(id=uuid7(), institution_id=inst_id, student_id=sid)
    session.add(conv)
    await session.flush()
    session.add(m.AIMessage(conversation_id=conv.id, seq=1, role=AIMessageRole.USER, content="hi"))
    session.add(m.JournalShare(institution_id=inst_id, entry_id=jid, therapist_id=th.user_id))
    session.add(
        m.Consent(
            institution_id=inst_id,
            user_id=sid,
            scope=ConsentScope.TERMS_AND_PRIVACY,
            policy_version="v1",
        )
    )
    session.add(
        m.Notification(institution_id=inst_id, user_id=sid, type=NotificationType.SYSTEM, title="t")
    )
    session.add(
        m.Recommendation(
            institution_id=inst_id,
            student_id=sid,
            source=RecommendationSource.RULE,
            title="t",
            rationale="r",
        )
    )
    await session.flush()

    await session.execute(text("DELETE FROM iam.users WHERE id = :i"), {"i": sid})

    for table, col in [
        ("iam.credentials", "user_id"),
        ("org.students", "user_id"),
        ("wellness.mood_entries", "student_id"),
        ("wellness.journal_entries", "student_id"),
        ("wellness.journal_shares", "entry_id"),
        ("wellness.wellness_goals", "student_id"),
        ("ai.ai_conversations", "student_id"),
        ("consent.consents", "user_id"),
        ("notify.notifications", "user_id"),
        ("ai.recommendations", "student_id"),
    ]:
        key = jid if col == "entry_id" else sid
        assert await helpers.count(session, table, f"{col} = :k", k=key) == 0, table
    assert await helpers.count(session, "ai.ai_messages", "conversation_id = :c", c=conv.id) == 0


@pytest.mark.parametrize("victim", ["student", "therapist"])
async def test_users_with_clinical_history_cannot_be_hard_deleted(
    session: AsyncSession, victim: str
) -> None:
    if victim == "student":
        user_id = (await helpers.student_with_sessions(session)).user_id
    else:
        user_id = (await helpers.completed_session(session)).therapist_id
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(text("DELETE FROM iam.users WHERE id = :i"), {"i": user_id})


async def test_sessions_with_notes_cannot_be_deleted_or_orphaned(session: AsyncSession) -> None:
    sess = await helpers.completed_session(session)
    for sql in (
        "DELETE FROM therapy.therapy_sessions WHERE id = :i",
        "DELETE FROM therapy.appointments WHERE id = :a",
    ):
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(text(sql), {"i": sess.id, "a": sess.appointment_id})


async def test_institutions_cannot_be_deleted_while_they_have_data(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text("DELETE FROM org.institutions WHERE id = :i"), {"i": inst.id}
            )


async def test_deleting_a_resource_keeps_recommendations(session: AsyncSession) -> None:
    rec = await helpers.first(
        session, select(m.Recommendation).where(m.Recommendation.resource_id.is_not(None))
    )
    rid, rec_id = rec.resource_id, rec.id
    await session.execute(text("DELETE FROM wellness.resources WHERE id = :i"), {"i": rid})
    assert (
        await helpers.count(
            session, "ai.recommendations", "id = :i AND resource_id IS NULL", i=rec_id
        )
        == 1
    )


async def test_deleting_a_course_removes_enrollments_and_teaching_links(
    session: AsyncSession,
) -> None:
    link = await helpers.first(session, select(m.CourseTeacher))
    cid = link.course_id
    await session.execute(text("DELETE FROM org.courses WHERE id = :i"), {"i": cid})
    assert await helpers.count(session, "org.course_enrollments", "course_id = :i", i=cid) == 0
    assert await helpers.count(session, "org.course_teachers", "course_id = :i", i=cid) == 0


async def test_audit_rows_survive_deletion_of_the_people_they_describe(
    session: AsyncSession,
) -> None:
    s = await helpers.new_student(session)
    row = await append_audit_event(
        session,
        institution_id=s.institution_id,
        action="mood.read",
        outcome=AuditOutcome.ALLOWED,
        actor_id=s.user_id,
        actor_role=UserRole.STUDENT,
        subject_student_id=s.user_id,
    )
    rid = row.id
    await session.execute(text("DELETE FROM iam.users WHERE id = :i"), {"i": s.user_id})
    assert await helpers.count(session, "audit.audit_logs", "id = :i", i=rid) == 1
