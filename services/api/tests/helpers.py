"""Small query helpers shared by the tests."""

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AppointmentStatus, UserRole
from app.infrastructure.db.ids import uuid7


async def first(session: AsyncSession, stmt: Any) -> Any:
    row = (await session.execute(stmt.limit(1))).scalars().first()
    assert row is not None, "seed data missing"
    return row


async def institution(session: AsyncSession) -> m.Institution:
    return await first(session, select(m.Institution))  # type: ignore[no-any-return]


async def student_without_clinical_records(session: AsyncSession) -> m.Student:
    """A seeded student with no therapy/alerts/messages (so hard delete is allowed)."""
    stmt = (
        select(m.Student)
        .where(~m.Student.user_id.in_(select(m.Appointment.student_id)))
        .where(~m.Student.user_id.in_(select(m.RiskAlert.student_id)))
        .where(~m.Student.user_id.in_(select(m.Message.student_id)))
        .where(~m.Student.user_id.in_(select(m.CareTeamMember.student_id)))
    )
    return await first(session, stmt)  # type: ignore[no-any-return]


async def student_with_sessions(session: AsyncSession) -> m.Student:
    stmt = select(m.Student).where(m.Student.user_id.in_(select(m.TherapySession.student_id)))
    return await first(session, stmt)  # type: ignore[no-any-return]


async def completed_session(session: AsyncSession) -> m.TherapySession:
    return await first(session, select(m.TherapySession))  # type: ignore[no-any-return]


async def any_therapist(session: AsyncSession) -> m.Therapist:
    return await first(session, select(m.Therapist))  # type: ignore[no-any-return]


async def any_student(session: AsyncSession) -> m.Student:
    return await first(session, select(m.Student))  # type: ignore[no-any-return]


async def new_user(
    session: AsyncSession, inst: m.Institution, role: UserRole, tag: str | None = None
) -> m.User:
    tag = tag or uuid.uuid4().hex[:8]
    u = m.User(
        id=uuid7(),
        institution_id=inst.id,
        email=f"t-{tag}@test.example",
        full_name=f"Test {tag}",
        role=role,
    )
    session.add(u)
    await session.flush()
    return u


async def new_student(session: AsyncSession) -> m.Student:
    """A fresh student with no history."""
    inst = await institution(session)
    dept = await first(session, select(m.Department).where(m.Department.institution_id == inst.id))
    u = await new_user(session, inst, UserRole.STUDENT)
    s = m.Student(
        user_id=u.id,
        institution_id=inst.id,
        department_id=dept.id,
        student_number=f"T-{uuid.uuid4().hex[:8]}",
        enrollment_year=2025,
        year_of_study=2,
    )
    session.add(s)
    await session.flush()
    return s


async def count(session: AsyncSession, table: str, where: str = "true", **params: Any) -> int:
    r = await session.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)  # noqa: S608
    return int(r.scalar_one())


LIVE = (AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED)
