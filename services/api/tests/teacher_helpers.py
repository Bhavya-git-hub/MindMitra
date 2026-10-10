"""Arrange helpers for the teacher-portal API tests.

``school`` builds a department of its own with one teacher, one class and a chosen number of
students, so a test controls exactly how many people are in a group and how many have agreed to
be counted. Data is written straight to the database; everything else goes through the real API.
"""

import dataclasses
import datetime as dt
import uuid
from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.wellness import instruments
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import UserRole
from app.infrastructure.db.ids import uuid7
from tests.api_world import Actor, Builder, World
from tests.student_helpers import Session, sign_in


@dataclasses.dataclass
class School:
    dept_id: uuid.UUID
    course_id: uuid.UUID
    teacher: Session
    students: list[Actor]
    consenting: list[Actor]


def wednesday(weeks_ago: int) -> dt.datetime:
    """Noon UTC on the Wednesday of a calendar week that has already begun (1 = last week)."""
    today = dt.datetime.now(dt.UTC).date()
    monday = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=weeks_ago)
    return dt.datetime.combine(monday + dt.timedelta(days=2), dt.time(12), tzinfo=dt.UTC)


async def add_week(
    db: AsyncSession,
    inst: uuid.UUID,
    student: Actor,
    weeks_ago: int,
    *,
    mood: int = 3,
    energy: int = 3,
    stress: int | None = 3,
    stressors: list[str] | None = None,
    sleep_hours: float | None = 7.0,
    note: str = "private synthetic note",
) -> None:
    when = wednesday(weeks_ago)
    db.add(
        m.MoodEntry(
            institution_id=inst,
            student_id=student.user_id,
            mood_score=mood,
            energy_level=energy,
            emotions=["calm"],
            note=note,
            logged_at=when,
        )
    )
    if stress is not None:
        db.add(
            m.StressAssessment(
                institution_id=inst,
                student_id=student.user_id,
                scale="perceived_stress_10",
                score=Decimal(stress * 8),
                max_score=Decimal(40),
                perceived_stress_level=stress,
                stressors=stressors or ["exams"],
                completed_at=when,
            )
        )
    if sleep_hours is not None:
        wake = when.replace(hour=6)
        db.add(
            m.SleepEntry(
                institution_id=inst,
                student_id=student.user_id,
                sleep_date=wake.date(),
                bedtime=wake - dt.timedelta(hours=sleep_hours),
                wake_time=wake,
                duration_minutes=round(sleep_hours * 60),
                quality=3,
            )
        )


async def add_wellbeing_check(
    db: AsyncSession, inst: uuid.UUID, student: Actor, raw_score: int
) -> None:
    db.add(
        m.WellnessAssessment(
            institution_id=inst,
            student_id=student.user_id,
            instrument=instruments.INSTRUMENT_ID,
            score=Decimal(raw_score),
            max_score=Decimal(25),
            responses={"1": 3},
            completed_at=wednesday(1),
        )
    )


async def school(
    client: httpx.AsyncClient,
    db: AsyncSession,
    world: World,
    *,
    students: int = 12,
    consenting: int | None = None,
    data: bool = True,
    teacher_in: uuid.UUID | None = None,
) -> School:
    """A new department with a teacher teaching one class of ``students``; the first
    ``consenting`` of them (default: all) have agreed to anonymous group figures."""
    b = Builder(db, world.password)
    tag = uuid.uuid4().hex[:8]
    dept = m.Department(id=uuid7(), institution_id=world.inst_a, name=f"Dept {tag}", code=tag)
    db.add(dept)
    await db.flush()
    course = m.Course(
        id=uuid7(),
        institution_id=world.inst_a,
        department_id=dept.id,
        code=f"C{tag[:6]}",
        title=f"Course {tag}",
        term="2026-autumn",
    )
    db.add(course)
    await db.flush()
    teacher = await b.user(world.inst_a, UserRole.TEACHER, department_id=teacher_in or dept.id)
    db.add(
        m.CourseTeacher(
            institution_id=world.inst_a, course_id=course.id, teacher_id=teacher.user_id
        )
    )
    people = [
        await b.user(world.inst_a, UserRole.STUDENT, department_id=dept.id) for _ in range(students)
    ]
    for p in people:
        db.add(
            m.CourseEnrollment(
                institution_id=world.inst_a, course_id=course.id, student_id=p.user_id
            )
        )
    agreed = people if consenting is None else people[:consenting]
    for p in agreed:
        await b.aggregate_consent(world.inst_a, p)
    if data:
        for i, p in enumerate(people):
            for weeks_ago in (1, 2):
                await add_week(
                    db,
                    world.inst_a,
                    p,
                    weeks_ago,
                    mood=1 + i % 5,
                    energy=1 + (i + 1) % 5,
                    stress=1 + (i + 2) % 5,
                    stressors=["exams", "finances"] if i % 2 == 0 else ["relationships"],
                )
    await db.commit()
    return School(
        dept.id, course.id, await sign_in(client, teacher, world.password), people, agreed
    )


async def another_teacher(
    client: httpx.AsyncClient, db: AsyncSession, world: World, dept_id: uuid.UUID
) -> Session:
    actor = await Builder(db, world.password).user(
        world.inst_a, UserRole.TEACHER, department_id=dept_id
    )
    await db.commit()
    return await sign_in(client, actor, world.password)
