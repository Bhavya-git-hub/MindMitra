"""The cast for the API authorization tests: two institutions and one actor per role.

Institution A is the synthetic seed; its clinical records give the therapist a real care-team
link, consented mood data and authored therapy notes. Institution B is built here and holds a
full set of actors too, so every cross-tenant attempt has a live target.

Every actor is ACTIVE and signs in with the same random per-run password.
"""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AdminLevel,
    AppointmentStatus,
    CareRole,
    ConsentScope,
    SessionMode,
    UserRole,
    UserStatus,
    VerificationStatus,
)
from app.infrastructure.db.ids import uuid7

NOW = dt.datetime.now(dt.UTC)


@dataclasses.dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    institution_id: uuid.UUID
    email: str
    role: UserRole


@dataclasses.dataclass(frozen=True)
class World:
    password: str
    inst_a: uuid.UUID
    inst_b: uuid.UUID
    dept_a: uuid.UUID  # the teacher's department
    other_dept_a: uuid.UUID
    student: Actor  # on ``therapist``'s care team, shares mood, has notes written about them
    other_student: Actor  # same institution, nobody's business but their own
    unconsented_student: Actor  # on ``therapist``'s care team, has NOT consented to sharing
    therapist: Actor
    other_therapist: Actor  # same institution, no link to ``student``
    teacher: Actor
    admin: Actor
    b_student: Actor
    b_therapist: Actor
    b_teacher: Actor
    b_admin: Actor
    appointment: uuid.UUID  # requested, ``therapist`` with ``unconsented_student``
    other_appointment: uuid.UUID  # requested, ``other_therapist`` with ``unconsented_student``
    b_appointment: uuid.UUID  # requested, institution B


class Builder:
    """Creates users with credentials and role profiles directly in the database."""

    def __init__(self, db: AsyncSession, password: str) -> None:
        self.db = db
        self.password_hash = hash_password(password)  # hashed once; Argon2 is slow on purpose

    async def user(
        self,
        inst_id: uuid.UUID,
        role: UserRole,
        *,
        department_id: uuid.UUID | None = None,
        status: UserStatus = UserStatus.ACTIVE,
        tag: str | None = None,
        verified: bool = True,
    ) -> Actor:
        tag = tag or uuid.uuid4().hex[:10]
        u = m.User(
            id=uuid7(),
            institution_id=inst_id,
            email=f"{role.value}.{tag}@test.example",
            full_name=f"Test {role.value.title()} {tag}",
            role=role,
            status=status,
        )
        u.credential = m.Credential(password_hash=self.password_hash)
        self.db.add(u)
        await self.db.flush()
        if role is UserRole.STUDENT:
            assert department_id is not None
            self.db.add(
                m.Student(
                    user_id=u.id,
                    institution_id=inst_id,
                    department_id=department_id,
                    student_number=f"T-{tag}",
                    enrollment_year=2025,
                    year_of_study=2,
                )
            )
        elif role is UserRole.TEACHER:
            assert department_id is not None
            self.db.add(
                m.Teacher(
                    user_id=u.id,
                    institution_id=inst_id,
                    department_id=department_id,
                    employee_number=f"E-{tag}",
                )
            )
        elif role is UserRole.THERAPIST:
            self.db.add(
                m.Therapist(
                    user_id=u.id,
                    institution_id=inst_id,
                    licence_number=f"L-{tag}",
                    verification_status=(
                        VerificationStatus.VERIFIED if verified else VerificationStatus.PENDING
                    ),
                    verified_at=NOW if verified else None,
                )
            )
        else:
            self.db.add(
                m.Administrator(
                    user_id=u.id, institution_id=inst_id, admin_level=AdminLevel.INSTITUTION_ADMIN
                )
            )
        await self.db.flush()
        return Actor(u.id, inst_id, u.email, role)

    async def institution(self, tag: str) -> tuple[uuid.UUID, uuid.UUID]:
        inst = m.Institution(
            id=uuid7(), name=f"Other College {tag}", slug=f"other-{tag}", email_domains=[]
        )
        self.db.add(inst)
        await self.db.flush()
        dept = m.Department(id=uuid7(), institution_id=inst.id, name="Other Dept", code="OTH")
        self.db.add(dept)
        await self.db.flush()
        return inst.id, dept.id

    async def care_link(self, inst_id: uuid.UUID, student: Actor, therapist: Actor) -> None:
        self.db.add(
            m.CareTeamMember(
                institution_id=inst_id,
                student_id=student.user_id,
                therapist_id=therapist.user_id,
                role=CareRole.PRIMARY,
                starts_at=NOW - dt.timedelta(days=10),
            )
        )
        await self.db.flush()

    async def appointment(
        self, inst_id: uuid.UUID, student: Actor, therapist: Actor, *, days_ahead: int
    ) -> uuid.UUID:
        start = NOW.replace(minute=0, second=0, microsecond=0) + dt.timedelta(days=days_ahead)
        appt = m.Appointment(
            id=uuid7(),
            institution_id=inst_id,
            student_id=student.user_id,
            therapist_id=therapist.user_id,
            starts_at=start,
            ends_at=start + dt.timedelta(minutes=50),
            mode=SessionMode.VIDEO,
            status=AppointmentStatus.REQUESTED,
        )
        self.db.add(appt)
        await self.db.flush()
        return appt.id

    async def aggregate_consent(self, inst_id: uuid.UUID, student: Actor) -> None:
        """The student agrees to be counted, anonymously, in group figures."""
        self.db.add(
            m.Consent(
                institution_id=inst_id,
                user_id=student.user_id,
                scope=ConsentScope.ANONYMOUS_AGGREGATE_RESEARCH,
                policy_version="test",
                granted_at=NOW - dt.timedelta(days=30),
            )
        )
        await self.db.flush()

    async def mood_entry(
        self, inst_id: uuid.UUID, student: Actor, score: int, *, days_ago: int = 1
    ) -> None:
        self.db.add(
            m.MoodEntry(
                institution_id=inst_id,
                student_id=student.user_id,
                mood_score=score,
                emotions=["calm"],
                note="private synthetic note",
                logged_at=NOW - dt.timedelta(days=days_ago),
            )
        )
        await self.db.flush()


async def _actor(db: AsyncSession, user_id: uuid.UUID) -> Actor:
    u = await db.get(m.User, user_id)
    assert u is not None
    return Actor(u.id, u.institution_id, u.email, u.role)


async def build_world(db: AsyncSession, password: str) -> World:
    """Run once against a freshly seeded database; commits."""
    b = Builder(db, password)
    inst_a = await db.scalar(
        select(m.Institution.id).where(m.Institution.slug == "synthetic-institute")
    )
    assert inst_a is not None

    # A therapist and student from the seed with an active link, sharing consent, mood entries
    # and notes the therapist wrote.
    active_link = exists().where(
        m.CareTeamMember.student_id == m.TherapySession.student_id,
        m.CareTeamMember.therapist_id == m.TherapyNote.author_id,
        m.CareTeamMember.ends_at.is_(None),
    )
    consented = exists().where(
        m.Consent.user_id == m.TherapySession.student_id,
        m.Consent.scope == ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
        m.Consent.revoked_at.is_(None),
    )
    has_mood = exists().where(m.MoodEntry.student_id == m.TherapySession.student_id)
    row = (
        await db.execute(
            select(m.TherapySession.student_id, m.TherapyNote.author_id)
            .join(m.TherapyNote, m.TherapyNote.session_id == m.TherapySession.id)
            .join(m.User, m.User.id == m.TherapySession.student_id)
            .where(
                m.TherapyNote.author_id == m.TherapySession.therapist_id,
                m.User.status == UserStatus.ACTIVE,
                and_(active_link, consented, has_mood),
            )
            .limit(1)
        )
    ).first()
    assert row is not None, "seed has no linked, consented student with therapy notes"
    student = await _actor(db, row.student_id)
    therapist = await _actor(db, row.author_id)

    other_therapist_id = await db.scalar(
        select(m.Therapist.user_id).where(
            m.Therapist.institution_id == inst_a,
            m.Therapist.user_id != therapist.user_id,
            m.Therapist.verification_status == VerificationStatus.VERIFIED,
            ~exists().where(
                m.CareTeamMember.therapist_id == m.Therapist.user_id,
                m.CareTeamMember.student_id == student.user_id,
            ),
        )
    )
    assert other_therapist_id is not None
    other_therapist = await _actor(db, other_therapist_id)

    student_dept = await db.scalar(
        select(m.Student.department_id).where(m.Student.user_id == student.user_id)
    )
    other_dept = await db.scalar(
        select(m.Department.id).where(
            m.Department.institution_id == inst_a, m.Department.id != student_dept
        )
    )
    assert student_dept is not None and other_dept is not None

    other_student = await b.user(inst_a, UserRole.STUDENT, department_id=student_dept)
    await b.mood_entry(inst_a, other_student, 3)
    unconsented = await b.user(inst_a, UserRole.STUDENT, department_id=student_dept)
    await b.care_link(inst_a, unconsented, therapist)
    await b.mood_entry(inst_a, unconsented, 4)
    teacher = await b.user(inst_a, UserRole.TEACHER, department_id=student_dept)
    admin = await b.user(inst_a, UserRole.ADMINISTRATOR)
    appt = await b.appointment(inst_a, unconsented, therapist, days_ahead=400)
    other_appt = await b.appointment(inst_a, unconsented, other_therapist, days_ahead=401)

    inst_b, dept_b = await b.institution(uuid.uuid4().hex[:8])
    b_student = await b.user(inst_b, UserRole.STUDENT, department_id=dept_b)
    b_therapist = await b.user(inst_b, UserRole.THERAPIST)
    b_teacher = await b.user(inst_b, UserRole.TEACHER, department_id=dept_b)
    b_admin = await b.user(inst_b, UserRole.ADMINISTRATOR)
    await b.care_link(inst_b, b_student, b_therapist)
    await b.mood_entry(inst_b, b_student, 5)
    b_appt = await b.appointment(inst_b, b_student, b_therapist, days_ahead=400)

    # Seeded users share a different password; give the two seeded actors the test one.
    for uid in (student.user_id, therapist.user_id, other_therapist.user_id):
        cred = await db.get(m.Credential, uid)
        assert cred is not None
        cred.password_hash = b.password_hash
    await db.commit()

    return World(
        password=password,
        inst_a=inst_a,
        inst_b=inst_b,
        dept_a=student_dept,
        other_dept_a=other_dept,
        student=student,
        other_student=other_student,
        unconsented_student=unconsented,
        therapist=therapist,
        other_therapist=other_therapist,
        teacher=teacher,
        admin=admin,
        b_student=b_student,
        b_therapist=b_therapist,
        b_teacher=b_teacher,
        b_admin=b_admin,
        appointment=appt,
        other_appointment=other_appt,
        b_appointment=b_appt,
    )
