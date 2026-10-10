"""A closed window is stored once it closes, so later edits to its weeks cannot move it.

Stored figures are dropped when a member's consent or account status changes, so withdrawing
consent (or being suspended) still takes effect on the next request.
"""

import datetime as dt
import uuid

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import cohort_stats
from app.domain.wellness import cohort
from app.domain.wellness.cohort import StudentWeek, analyse
from app.infrastructure.db import models as m
from tests.api_helpers import call, token_for
from tests.api_world import World
from tests.student_helpers import sign_in
from tests.teacher_helpers import add_week, school

MON = dt.date(2026, 9, 28)
STARTS = cohort.week_starts(MON + dt.timedelta(weeks=1), 4)


async def stored_rows(db: AsyncSession, group: uuid.UUID) -> int:
    await db.rollback()  # read what the API committed, not this session's cached view
    return (
        await db.scalar(
            select(func.count())
            .select_from(m.GroupSnapshot)
            .where(m.GroupSnapshot.group_id == group)
        )
    ) or 0


def without_timestamp(body: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in body.items() if k != "generated_at"}


def test_stored_figures_survive_the_round_trip_unchanged() -> None:
    rows = [
        StudentWeek(
            key=i,
            week_start=STARTS[-1],
            mood=3.0,
            energy=2.0,
            stress=4.5,
            academic_stress=True,
            stressors=frozenset({"exams"}),
            sleep_minutes=330.0,
            sleep_quality=2.0,
            checked_in=True,
        )
        for i in range(10)
    ]
    analytics = analyse(rows, 12, STARTS)
    figures = cohort_stats.GroupFigures(
        analytics=analytics,
        wellbeing=[cohort_stats.WellbeingBand("lower", "Lower lately", cohort.share(3, 10))],
        starts=STARTS,
    )
    decoded = cohort_stats.decode_figures(cohort_stats.encode_figures(figures))
    assert decoded == figures
    assert analytics.state == "ok" and analytics.weeks[-1].strain.state != "hidden"


async def test_a_late_edit_to_a_closed_week_does_not_move_its_figures(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    first = (await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics")).json()["analytics"]
    assert await stored_rows(api_db, s.course_id) == 1

    for student in s.consenting:  # a back-dated, unusually bad week lands after the first read
        await add_week(
            api_db, world.inst_a, student, 1, mood=1, energy=1, stress=5, sleep_hours=None
        )
    await api_db.commit()

    again = (await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics")).json()["analytics"]
    assert without_timestamp(again) == without_timestamp(first)


async def test_a_late_edit_does_not_move_the_stored_department_mood_summary(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    url = f"/insights/mood-summary?department_id={s.dept_id}"
    first = (await s.teacher.get(url)).json()
    assert first["suppressed"] is False

    for student in s.consenting:
        await add_week(api_db, world.inst_a, student, 1, mood=1, sleep_hours=None)
    await api_db.commit()
    assert (await s.teacher.get(url)).json() == first


async def test_withdrawing_consent_drops_the_stored_window_at_once(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    assert (await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics")).status_code == 200
    assert await stored_rows(api_db, s.course_id) == 1

    leaver = await sign_in(client, s.consenting[0], world.password)
    r = await leaver.put("/me/consents/anonymous_aggregate_research", {"granted": False})
    assert r.status_code == 200, r.text
    assert await stored_rows(api_db, s.course_id) == 0


async def test_suspending_a_student_drops_the_stored_windows(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=12)
    assert (await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics")).status_code == 200
    assert await stored_rows(api_db, s.course_id) == 1

    admin = await token_for(client, world.admin, world.password)
    r = await call(
        client,
        "PATCH",
        f"/admin/users/{s.consenting[0].user_id}",
        token=admin,
        json={"status": "suspended"},
    )
    assert r.status_code == 200, r.text
    assert await stored_rows(api_db, s.course_id) == 0


@pytest.mark.parametrize("weeks", [4, 8])
async def test_each_window_size_is_stored_separately(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, weeks: int
) -> None:
    s = await school(client, api_db, world, students=12)
    assert (
        await s.teacher.get(f"/teacher/classes/{s.course_id}/analytics?weeks={weeks}")
    ).status_code == 200
    rows = await api_db.scalar(
        select(func.count())
        .select_from(m.GroupSnapshot)
        .where(m.GroupSnapshot.group_id == s.course_id, m.GroupSnapshot.weeks == weeks)
    )
    assert rows == 1
