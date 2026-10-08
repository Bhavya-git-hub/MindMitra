"""Database constraints: every rule below is enforced by PostgreSQL itself."""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event, verify_chain
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    AppointmentStatus,
    AuditOutcome,
    CareRole,
    ConsentScope,
    GoalCategory,
    GoalStatus,
    ResourceType,
    SessionMode,
    UserRole,
)
from app.infrastructure.db.ids import uuid7
from tests import helpers

NOW = dt.datetime(2030, 1, 1, 12, 0, tzinfo=dt.UTC)  # far from seed data, so no overlaps


async def rejected(
    session: AsyncSession, *objs: object, match: str, exc: type[Exception] = IntegrityError
) -> None:
    with pytest.raises(exc, match=match):
        async with session.begin_nested():
            session.add_all(objs)
            await session.flush()


async def raw_rejected(session: AsyncSession, sql: str, match: str) -> None:
    with pytest.raises(DBAPIError, match=match):
        async with session.begin_nested():
            await session.execute(text(sql))


# ---- identity -------------------------------------------------------------------------


async def test_user_email_must_be_lowercase_unique_per_institution(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    base = dict(institution_id=inst.id, full_name="X Y", role=UserRole.STUDENT)
    await rejected(
        session, m.User(id=uuid7(), email="Mixed@Case.example", **base), match="email_lowercase"
    )
    await rejected(session, m.User(id=uuid7(), email="no-at-sign", **base), match="email_has_at")
    await rejected(
        session,
        m.User(id=uuid7(), email="x@y.example", **{**base, "full_name": "  "}),
        match="full_name_not_blank",
    )
    await helpers.new_user(session, inst, UserRole.STUDENT, "dup")
    await rejected(
        session,
        m.User(id=uuid7(), email="t-dup@test.example", **base),
        match="uq_users_institution_email",
    )


async def test_same_email_allowed_in_a_different_institution(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    other = m.Institution(id=uuid7(), name="Other", slug="other-inst")
    session.add(other)
    await session.flush()
    await helpers.new_user(session, inst, UserRole.STUDENT, "same")
    session.add(
        m.User(
            id=uuid7(),
            institution_id=other.id,
            email="t-same@test.example",
            full_name="Z",
            role=UserRole.STUDENT,
        )
    )
    await session.flush()


async def test_profile_must_match_user_role_and_tenant(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    dept = await helpers.first(session, select(m.Department))
    therapist_user = await helpers.new_user(session, inst, UserRole.THERAPIST)
    # a student profile cannot attach to a therapist account
    await rejected(
        session,
        m.Student(
            user_id=therapist_user.id,
            institution_id=inst.id,
            department_id=dept.id,
            student_number="BAD-1",
            enrollment_year=2025,
            year_of_study=1,
        ),
        match="fk_students_user_role",
    )
    # a profile cannot claim a different institution than its user ...
    other = m.Institution(id=uuid7(), name="Other", slug="other-inst-2")
    session.add(other)
    await session.flush()
    stu_user = await helpers.new_user(session, inst, UserRole.STUDENT)
    await rejected(
        session,
        m.Student(
            user_id=stu_user.id,
            institution_id=other.id,
            department_id=dept.id,
            student_number="BAD-2",
            enrollment_year=2025,
            year_of_study=1,
        ),
        match="fk_students_(user_role|department_institution)",
    )
    # ... nor point at a department of another institution
    other_user = await helpers.new_user(session, other, UserRole.STUDENT, "otherinst")
    await rejected(
        session,
        m.Student(
            user_id=other_user.id,
            institution_id=other.id,
            department_id=dept.id,
            student_number="BAD-4",
            enrollment_year=2025,
            year_of_study=1,
        ),
        match="fk_students_department_institution",
    )


async def test_profile_role_column_cannot_be_forged(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    dept = await helpers.first(session, select(m.Department))
    u = await helpers.new_user(session, inst, UserRole.STUDENT)
    await rejected(
        session,
        m.Student(
            user_id=u.id,
            role="therapist",
            institution_id=inst.id,
            department_id=dept.id,
            student_number="BAD-3",
            enrollment_year=2025,
            year_of_study=1,
        ),
        match="role_matches",
    )


async def test_student_profile_ranges_and_unique_number(session: AsyncSession) -> None:
    s = await helpers.any_student(session)
    inst = await helpers.institution(session)
    dept = await helpers.first(session, select(m.Department))
    u = await helpers.new_user(session, inst, UserRole.STUDENT)
    await rejected(
        session,
        m.Student(
            user_id=u.id,
            institution_id=inst.id,
            department_id=dept.id,
            student_number=s.student_number,
            enrollment_year=2025,
            year_of_study=1,
        ),
        match="uq_students_institution_number",
    )
    await rejected(
        session,
        m.Student(
            user_id=u.id,
            institution_id=inst.id,
            department_id=dept.id,
            student_number="OK-1",
            enrollment_year=2025,
            year_of_study=12,
        ),
        match="year_of_study_range",
    )


# ---- wellness ---------------------------------------------------------------------------


async def test_mood_scores_are_bounded(session: AsyncSession) -> None:
    s = await helpers.any_student(session)
    mk = lambda score, **kw: m.MoodEntry(
        institution_id=s.institution_id, student_id=s.user_id, mood_score=score, **kw
    )  # noqa: E731
    await rejected(session, mk(0), match="mood_score_range")
    await rejected(session, mk(6), match="mood_score_range")
    await rejected(session, mk(3, energy_level=9), match="energy_range")
    session.add(mk(5))
    await session.flush()


async def test_sleep_entry_rules(session: AsyncSession) -> None:
    s = await helpers.new_student(session)
    bed = NOW
    mk = lambda **kw: m.SleepEntry(  # noqa: E731
        institution_id=s.institution_id,
        student_id=s.user_id,
        sleep_date=NOW.date(),
        bedtime=bed,
        wake_time=bed + dt.timedelta(hours=8),
        duration_minutes=480,
        quality=3,
        **kw,
    )
    session.add(mk())
    await session.flush()
    await rejected(session, mk(), match="uq_sleep_entries_student_date")
    other = m.SleepEntry(
        institution_id=s.institution_id,
        student_id=s.user_id,
        sleep_date=NOW.date() + dt.timedelta(days=1),
        bedtime=bed,
        wake_time=bed - dt.timedelta(hours=1),
        duration_minutes=60,
        quality=3,
    )
    await rejected(session, other, match="wake_after_bedtime")
    bad = m.SleepEntry(
        institution_id=s.institution_id,
        student_id=s.user_id,
        sleep_date=NOW.date() + dt.timedelta(days=2),
        bedtime=bed,
        wake_time=bed + dt.timedelta(hours=1),
        duration_minutes=2000,
        quality=3,
    )
    await rejected(session, bad, match="duration_range")


async def test_assessment_scores_cannot_exceed_maximum(session: AsyncSession) -> None:
    s = await helpers.any_student(session)
    common = dict(institution_id=s.institution_id, student_id=s.user_id)
    await rejected(
        session,
        m.WellnessAssessment(instrument="x", score=Decimal(30), max_score=Decimal(25), **common),
        match="score_within_max",
    )
    await rejected(
        session,
        m.WellnessAssessment(instrument="x", score=Decimal(-1), max_score=Decimal(25), **common),
        match="score_within_max",
    )
    await rejected(
        session,
        m.StressAssessment(
            scale="x", score=Decimal(5), max_score=Decimal(40), perceived_stress_level=7, **common
        ),
        match="stress_level_range",
    )


async def test_goal_lifecycle_rules(session: AsyncSession) -> None:
    s = await helpers.any_student(session)
    mk = lambda **kw: m.WellnessGoal(  # noqa: E731
        institution_id=s.institution_id,
        student_id=s.user_id,
        title="Sleep more",
        category=GoalCategory.SLEEP,
        start_date=NOW.date(),
        **kw,
    )
    await rejected(session, mk(status=GoalStatus.COMPLETED), match="completed_at_matches_status")
    await rejected(
        session, mk(status=GoalStatus.ACTIVE, completed_at=NOW), match="completed_at_matches_status"
    )
    await rejected(
        session, mk(target_date=NOW.date() - dt.timedelta(days=1)), match="target_after_start"
    )
    await rejected(session, mk(target_value=Decimal(0)), match="target_positive")


async def test_published_resources_must_be_reviewed(session: AsyncSession) -> None:
    await rejected(
        session,
        m.Resource(title="T", summary="S", resource_type=ResourceType.ARTICLE, is_published=True),
        match="published_requires_review",
    )
    session.add(
        m.Resource(title="T", summary="S", resource_type=ResourceType.ARTICLE, is_published=False)
    )
    await session.flush()


async def test_journal_share_unique_and_revocation_order(session: AsyncSession) -> None:
    s = await helpers.new_student(session)
    th = await helpers.any_therapist(session)
    e = m.JournalEntry(
        id=uuid7(), institution_id=s.institution_id, student_id=s.user_id, body="private thoughts"
    )
    session.add(e)
    await session.flush()
    session.add(m.JournalShare(entry_id=e.id, therapist_id=th.user_id, shared_at=NOW))
    await session.flush()
    await rejected(
        session,
        m.JournalShare(entry_id=e.id, therapist_id=th.user_id),
        match="uq_journal_shares_entry_therapist",
    )
    e2 = m.JournalEntry(
        id=uuid7(), institution_id=s.institution_id, student_id=s.user_id, body="more"
    )
    session.add(e2)
    await session.flush()
    await rejected(
        session,
        m.JournalShare(
            entry_id=e2.id,
            therapist_id=th.user_id,
            shared_at=NOW,
            revoked_at=NOW - dt.timedelta(days=1),
        ),
        match="revoked_after_shared",
    )


# ---- care team & scheduling ----------------------------------------------------------------


async def test_one_active_primary_therapist_per_student(session: AsyncSession) -> None:
    s = await helpers.new_student(session)
    t1, t2 = (await session.execute(select(m.Therapist).limit(2))).scalars().all()
    session.add(
        m.CareTeamMember(
            student_id=s.user_id, therapist_id=t1.user_id, role=CareRole.PRIMARY, starts_at=NOW
        )
    )
    await session.flush()
    await rejected(
        session,
        m.CareTeamMember(
            student_id=s.user_id, therapist_id=t2.user_id, role=CareRole.PRIMARY, starts_at=NOW
        ),
        match="uq_care_team_active_primary",
    )
    session.add(
        m.CareTeamMember(
            student_id=s.user_id, therapist_id=t2.user_id, role=CareRole.SECONDARY, starts_at=NOW
        )
    )
    await session.flush()
    await rejected(
        session,
        m.CareTeamMember(
            student_id=s.user_id, therapist_id=t2.user_id, role=CareRole.SECONDARY, starts_at=NOW
        ),
        match="uq_care_team_active_pair",
    )
    await rejected(
        session,
        m.CareTeamMember(
            student_id=(await helpers.new_student(session)).user_id,
            therapist_id=t1.user_id,
            starts_at=NOW,
            ends_at=NOW - dt.timedelta(days=1),
        ),
        match="period_valid",
    )


async def test_therapist_cannot_offer_overlapping_slots(session: AsyncSession) -> None:
    th = await helpers.any_therapist(session)
    mk = lambda start, mins: m.TherapistAvailability(  # noqa: E731
        institution_id=th.institution_id,
        therapist_id=th.user_id,
        starts_at=start,
        ends_at=start + dt.timedelta(minutes=mins),
    )
    session.add(mk(NOW, 60))
    await session.flush()
    await rejected(
        session,
        mk(NOW + dt.timedelta(minutes=30), 60),
        match="ex_therapist_availability_no_overlap",
    )
    session.add(mk(NOW + dt.timedelta(minutes=60), 60))  # back-to-back is fine
    await session.flush()
    await rejected(session, mk(NOW + dt.timedelta(days=2), 0), match="slot_valid")


def _appt(student: m.Student, th: m.Therapist, start: dt.datetime, **kw: object) -> m.Appointment:
    return m.Appointment(
        id=uuid7(),
        institution_id=student.institution_id,
        student_id=student.user_id,
        therapist_id=th.user_id,
        starts_at=start,
        ends_at=start + dt.timedelta(hours=1),
        mode=SessionMode.VIDEO,
        **kw,  # type: ignore[arg-type]
    )


async def test_no_double_booking_for_therapist_or_student(session: AsyncSession) -> None:
    th = await helpers.any_therapist(session)
    s1, s2 = await helpers.new_student(session), await helpers.new_student(session)
    t0 = NOW + dt.timedelta(days=3)
    session.add(_appt(s1, th, t0, status=AppointmentStatus.CONFIRMED))
    await session.flush()
    await rejected(
        session,
        _appt(s2, th, t0 + dt.timedelta(minutes=15), status=AppointmentStatus.CONFIRMED),
        match="ex_appointments_therapist_no_overlap",
    )
    th2 = (
        await session.execute(select(m.Therapist).where(m.Therapist.user_id != th.user_id).limit(1))
    ).scalar_one()
    await rejected(
        session,
        _appt(s1, th2, t0 + dt.timedelta(minutes=15), status=AppointmentStatus.CONFIRMED),
        match="ex_appointments_student_no_overlap",
    )
    # a cancelled booking frees the time
    session.add(_appt(s2, th, t0, status=AppointmentStatus.CANCELLED, cancelled_at=NOW))
    await session.flush()


async def test_appointment_rules(session: AsyncSession) -> None:
    th = await helpers.any_therapist(session)
    s = await helpers.new_student(session)
    t0 = NOW + dt.timedelta(days=5)
    await rejected(
        session,
        _appt(s, th, t0, status=AppointmentStatus.CANCELLED),
        match="cancelled_at_matches_status",
    )
    bad = _appt(s, th, t0)
    bad.ends_at = t0 - dt.timedelta(minutes=1)
    await rejected(session, bad, match="period_valid")


async def test_slot_belongs_to_the_appointment_therapist_and_is_booked_once(
    session: AsyncSession,
) -> None:
    th_a, th_b = (await session.execute(select(m.Therapist).limit(2))).scalars().all()
    s1, s2 = await helpers.new_student(session), await helpers.new_student(session)
    start = NOW + dt.timedelta(days=7)
    slot = m.TherapistAvailability(
        id=uuid7(),
        institution_id=th_a.institution_id,
        therapist_id=th_a.user_id,
        starts_at=start,
        ends_at=start + dt.timedelta(hours=1),
    )
    session.add(slot)
    await session.flush()
    await rejected(
        session,
        _appt(s1, th_b, start, availability_id=slot.id),
        match="fk_appointments_availability_therapist",
    )
    session.add(_appt(s1, th_a, start, availability_id=slot.id, status=AppointmentStatus.REQUESTED))
    await session.flush()
    # same slot, non-overlapping time label is irrelevant: the slot itself is single-use
    await rejected(
        session,
        _appt(
            s2,
            th_a,
            start + dt.timedelta(hours=3),
            availability_id=slot.id,
            status=AppointmentStatus.REQUESTED,
        ),
        match="uq_appointments_live_slot",
    )


async def test_only_the_sessions_therapist_can_author_its_notes(session: AsyncSession) -> None:
    sess = await helpers.completed_session(session)
    other = (
        await session.execute(
            select(m.Therapist).where(m.Therapist.user_id != sess.therapist_id).limit(1)
        )
    ).scalar_one()
    common = dict(institution_id=sess.institution_id, session_id=sess.id, body="x")
    await rejected(
        session,
        m.TherapyNote(author_id=other.user_id, version=50, **common),
        match="fk_therapy_notes_session_author",
    )
    await rejected(
        session,
        m.TherapyNote(author_id=sess.therapist_id, version=0, **common),
        match="version_positive",
    )
    session.add(m.TherapyNote(author_id=sess.therapist_id, version=99, **common))
    await session.flush()
    await rejected(
        session,
        m.TherapyNote(author_id=sess.therapist_id, version=99, **common),
        match="uq_therapy_notes_session_version",
    )


async def test_session_must_reference_the_appointments_parties(session: AsyncSession) -> None:
    ap = await helpers.first(
        session,
        select(m.Appointment).where(~m.Appointment.id.in_(select(m.TherapySession.appointment_id))),
    )
    other_student = await helpers.new_student(session)
    await rejected(
        session,
        m.TherapySession(
            institution_id=ap.institution_id,
            appointment_id=ap.id,
            student_id=other_student.user_id,
            therapist_id=ap.therapist_id,
            started_at=NOW,
        ),
        match="fk_therapy_sessions_appointment_parties",
    )


# ---- communication, AI, safety, consent, notifications ------------------------------------------


async def test_message_sender_must_be_a_participant(session: AsyncSession) -> None:
    pair = await helpers.first(session, select(m.CareTeamMember))
    stranger = await helpers.new_user(session, await helpers.institution(session), UserRole.TEACHER)
    common = dict(
        institution_id=pair.student.institution_id
        if False
        else (await helpers.institution(session)).id,
        student_id=pair.student_id,
        therapist_id=pair.therapist_id,
        body="hi",
    )
    await rejected(
        session, m.Message(sender_id=stranger.id, **common), match="sender_is_participant"
    )
    session.add(m.Message(sender_id=pair.student_id, client_msg_id=uuid7(), **common))
    await session.flush()


async def test_message_retries_are_idempotent(session: AsyncSession) -> None:
    pair = await helpers.first(session, select(m.CareTeamMember))
    inst = await helpers.institution(session)
    cid = uuid.uuid4()
    mk = lambda: m.Message(
        institution_id=inst.id,
        student_id=pair.student_id,
        therapist_id=pair.therapist_id,
        sender_id=pair.student_id,
        body="hi",
        client_msg_id=cid,
    )  # noqa: E731
    session.add(mk())
    await session.flush()
    await rejected(session, mk(), match="uq_messages_sender_client_msg")


async def test_ai_message_ordering_is_unique(session: AsyncSession) -> None:
    conv = await helpers.first(session, select(m.AIConversation))
    from app.infrastructure.db.enums import AIMessageRole

    await rejected(
        session,
        m.AIMessage(conversation_id=conv.id, seq=1, role=AIMessageRole.USER, content="dup"),
        match="uq_ai_messages_conversation_seq",
    )
    await rejected(
        session,
        m.AIMessage(conversation_id=conv.id, seq=0, role=AIMessageRole.USER, content="zero"),
        match="seq_positive",
    )


async def test_model_recommendations_require_a_model_version(session: AsyncSession) -> None:
    from app.infrastructure.db.enums import RecommendationSource

    s = await helpers.any_student(session)
    await rejected(
        session,
        m.Recommendation(
            institution_id=s.institution_id,
            student_id=s.user_id,
            source=RecommendationSource.MODEL,
            title="t",
            rationale="r",
        ),
        match="model_source_has_version",
    )


def _alert(s: m.Student, **kw: object) -> m.RiskAlert:
    base: dict[str, object] = dict(
        institution_id=s.institution_id,
        student_id=s.user_id,
        source=AlertSource.MOOD_ENTRY,
        detector=AlertDetector.RULES,
        category=AlertCategory.ACUTE_DISTRESS,
        severity=AlertSeverity.MODERATE,
    )
    base.update(kw)
    return m.RiskAlert(**base)  # type: ignore[arg-type]


async def test_risk_alert_invariants(session: AsyncSession) -> None:
    s = await helpers.any_student(session)
    await rejected(session, _alert(s, requires_human=False), match="always_requires_human")
    await rejected(session, _alert(s, severity=AlertSeverity.HIGH), match="high_severity_has_sla")
    await rejected(
        session,
        _alert(s, status=AlertStatus.RESOLVED, acknowledged_at=NOW),
        match="resolved_at_matches_status",
    )
    await rejected(
        session,
        _alert(s, status=AlertStatus.OPEN, resolved_at=NOW),
        match="resolved_at_matches_status",
    )
    await rejected(
        session, _alert(s, status=AlertStatus.IN_PROGRESS), match="acknowledged_before_progress"
    )
    await rejected(session, _alert(s, source_type="mood_entry"), match="source_ref_complete")
    await rejected(session, _alert(s, confidence=Decimal("1.5")), match="confidence_range")
    session.add(_alert(s, severity=AlertSeverity.HIGH, sla_ack_due_at=NOW))
    await session.flush()


async def test_alert_categories_contain_no_diagnostic_labels() -> None:
    banned = ("depress", "disorder", "anxiety", "bipolar", "ptsd", "schizo", "diagnos")
    for cat in AlertCategory:
        assert not any(b in cat.value for b in banned), cat


async def test_one_active_consent_per_scope_and_history_is_kept(session: AsyncSession) -> None:
    s = await helpers.new_student(session)
    mk = lambda **kw: m.Consent(
        institution_id=s.institution_id,
        user_id=s.user_id,
        scope=ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
        policy_version="v1",
        **kw,
    )  # noqa: E731
    g = mk(granted_at=NOW)
    session.add(g)
    await session.flush()
    await rejected(session, mk(granted_at=NOW), match="uq_consents_active_user_scope")
    g.revoked_at = NOW + dt.timedelta(days=1)
    await session.flush()
    session.add(mk(granted_at=NOW + dt.timedelta(days=2)))  # re-grant is a new row
    await session.flush()
    await rejected(
        session,
        m.Consent(
            institution_id=s.institution_id,
            user_id=s.user_id,
            scope=ConsentScope.AI_COMPANION_HISTORY,
            policy_version="v1",
            granted_at=NOW,
            revoked_at=NOW - dt.timedelta(days=1),
        ),
        match="revoked_after_granted",
    )


async def test_notification_payload_must_be_an_object(session: AsyncSession) -> None:
    from app.infrastructure.db.enums import NotificationType

    s = await helpers.any_student(session)
    await rejected(
        session,
        m.Notification(
            institution_id=s.institution_id,
            user_id=s.user_id,
            type=NotificationType.SYSTEM,
            title="t",
            payload=["a"],
        ),
        match="payload_is_object",
    )  # type: ignore[arg-type]


async def test_enum_values_are_enforced_by_check_constraints(session: AsyncSession) -> None:
    await raw_rejected(
        session,
        "UPDATE iam.users SET role = 'superuser' WHERE id = (SELECT id FROM iam.users LIMIT 1)",
        "user_role",
    )
    await raw_rejected(
        session,
        "UPDATE therapy.appointments SET status = 'maybe' "
        "WHERE id = (SELECT id FROM therapy.appointments LIMIT 1)",
        "appointment_status",
    )


# ---- audit log -----------------------------------------------------------------------------------


async def test_audit_log_is_append_only(session: AsyncSession) -> None:
    await raw_rejected(session, "UPDATE audit.audit_logs SET reason = 'edited'", "append-only")
    await raw_rejected(session, "DELETE FROM audit.audit_logs", "append-only")
    await raw_rejected(session, "TRUNCATE audit.audit_logs", "append-only")


async def test_audit_chain_verifies_and_detects_tampering(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    inst_id = inst.id
    assert await verify_chain(session, inst_id) is None
    row = await append_audit_event(
        session,
        institution_id=inst_id,
        action="consent.update",
        outcome=AuditOutcome.ALLOWED,
        details={"scope": "x"},
    )
    seq = row.seq
    assert row.prev_hash is not None and len(row.hash) == 64
    assert await verify_chain(session, inst_id) is None
    # Superuser-only simulation of tampering (triggers disabled inside this rolled-back transaction)
    is_super = (
        await session.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
    ).scalar_one()
    if not is_super:
        pytest.skip("needs superuser to simulate tampering")
    await session.execute(
        text("ALTER TABLE audit.audit_logs DISABLE TRIGGER audit_logs_no_update_delete")
    )
    await session.execute(
        text("UPDATE audit.audit_logs SET action = 'forged' WHERE id = :i"), {"i": row.id}
    )
    session.expire_all()
    assert await verify_chain(session, inst_id) == seq


async def test_seeded_audit_chain_is_intact_and_has_denials(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    assert await verify_chain(session, inst.id) is None
    denied = await helpers.count(
        session, "audit.audit_logs", "outcome = 'denied' AND actor_role = 'teacher'"
    )
    assert denied >= 1
