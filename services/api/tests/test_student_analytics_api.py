"""Student analytics: the wellness index, weekly figures, wellbeing checks and goal progress.

The pure rules are tested directly; the endpoint is tested with entries seeded at known local
days so the weekly averages, the Monday boundaries and the privacy guarantees are exact.
"""

import datetime as dt
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.wellness import indicators
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import GoalCategory, GoalStatus
from app.infrastructure.db.ids import uuid7
from tests.api_helpers import call, token_for
from tests.api_world import World
from tests.student_helpers import Session, new_student

PATH = "/me/wellness/analytics"
UTC = ZoneInfo("UTC")
IST = ZoneInfo("Asia/Kolkata")  # UTC+5:30
LA = ZoneInfo("America/Los_Angeles")  # UTC-7/-8


# ---- the index, as a pure rule ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("mood", "stress", "sleep", "expected"),
    [
        (4, 2, 3, 67),  # all three present: (75 + 75 + 50) / 3 = 66.7
        (5, 1, 5, 100),  # the best possible answers
        (1, 5, 1, 0),  # the lowest possible answers
        (3, 3, 3, 50),
        (4, None, 2, 50),  # two present: mood and sleep only
        (None, 2, 4, 75),  # two present: stress and sleep only, (75 + 75) / 2
        (3, 4, None, 38),  # two present: mood and stress only
        (5, None, None, None),  # one present is not enough
        (None, 1, None, None),
        (None, None, 4, None),
        (None, None, None, None),
    ],
)
def test_wellness_index_cases(
    mood: float | None, stress: float | None, sleep: float | None, expected: int | None
) -> None:
    assert indicators.wellness_index(mood, stress, sleep) == expected


def test_wellness_index_inverts_stress() -> None:
    calm = indicators.wellness_index(3, 1, None)
    tense = indicators.wellness_index(3, 5, None)
    assert calm == 75 and tense == 25  # same mood, so only the stress answer moves it
    assert calm is not None and tense is not None and calm > tense


def test_wellness_index_maps_each_scale_end_to_end() -> None:
    assert indicators.wellness_index(1, 5, None) == 0
    assert indicators.wellness_index(5, 1, None) == 100
    assert indicators.wellness_index(1, None, 1) == 0
    assert indicators.wellness_index(None, 1, 5) == 100


def test_wellness_index_rounds_halves_up_and_accepts_averages() -> None:
    assert indicators.wellness_index(2, 5, None) == 13  # (25 + 0) / 2 = 12.5
    assert indicators.wellness_index(2, None, 3) == 38  # (25 + 50) / 2 = 37.5
    assert indicators.wellness_index(3.5, None, 3.5) == 63  # 62.5: weekly averages are fractional
    assert isinstance(indicators.wellness_index(4, 2, 3), int)


def test_goal_progress_percent() -> None:
    assert indicators.goal_progress_percent(5, 10) == 50
    assert indicators.goal_progress_percent(25, 10) == 100  # capped
    assert indicators.goal_progress_percent(0, 10) == 0
    assert indicators.goal_progress_percent(3, None) is None
    assert indicators.goal_progress_percent(3, 0) is None


# ---- seeding helpers -------------------------------------------------------------------------


def _today(zone: ZoneInfo) -> dt.date:
    return dt.datetime.now(zone).date()


def monday(zone: ZoneInfo, weeks_ago: int = 0) -> dt.date:
    today = _today(zone)
    return today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=weeks_ago)


def local(day: dt.date, zone: ZoneInfo, hour: int = 12, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=zone).astimezone(dt.UTC)


async def add_mood(
    db: AsyncSession,
    inst: Any,
    student: Any,
    day: dt.date,
    score: int,
    zone: ZoneInfo = UTC,
    minute: int = 0,
    hour: int = 12,
) -> None:
    db.add(
        m.MoodEntry(
            id=uuid7(),
            institution_id=inst,
            student_id=student,
            mood_score=score,
            emotions=[],
            logged_at=local(day, zone, hour, minute),
        )
    )
    await db.commit()


async def add_stress(
    db: AsyncSession, inst: Any, student: Any, day: dt.date, level: int, zone: ZoneInfo = UTC
) -> None:
    db.add(
        m.StressAssessment(
            id=uuid7(),
            institution_id=inst,
            student_id=student,
            scale="daily_stress_check",
            score=Decimal(level),
            max_score=Decimal(5),
            perceived_stress_level=level,
            stressors=[],
            completed_at=local(day, zone, 13),
        )
    )
    await db.commit()


async def add_sleep(
    db: AsyncSession, inst: Any, student: Any, day: dt.date, minutes: int, quality: int
) -> None:
    wake = local(day, UTC, 7)
    db.add(
        m.SleepEntry(
            id=uuid7(),
            institution_id=inst,
            student_id=student,
            sleep_date=day,
            bedtime=wake - dt.timedelta(minutes=minutes),
            wake_time=wake,
            duration_minutes=minutes,
            quality=quality,
        )
    )
    await db.commit()


async def add_goal(
    db: AsyncSession,
    inst: Any,
    student: Any,
    category: GoalCategory,
    status: GoalStatus = GoalStatus.ACTIVE,
    *,
    target: int | None = None,
    current: int = 0,
    completed_at: dt.datetime | None = None,
) -> None:
    db.add(
        m.WellnessGoal(
            id=uuid7(),
            institution_id=inst,
            student_id=student,
            title="A synthetic goal",
            category=category,
            status=status,
            target_value=None if target is None else Decimal(target),
            current_value=Decimal(current),
            completed_at=completed_at,
        )
    )
    await db.commit()


async def add_check(
    db: AsyncSession, inst: Any, student: Any, raw: int, completed_at: dt.datetime
) -> None:
    db.add(
        m.WellnessAssessment(
            id=uuid7(),
            institution_id=inst,
            student_id=student,
            instrument="wellbeing_index_5",
            instrument_version="1",
            score=Decimal(raw),
            max_score=Decimal(25),
            responses={},
            completed_at=completed_at,
        )
    )
    await db.commit()


async def analytics(s: Session, query: str = "") -> dict[str, Any]:
    r = await s.get(f"{PATH}{query}")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def by_week(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {w["week_start"]: w for w in body["weeks"]}


# ---- weekly figures --------------------------------------------------------------------------


async def test_weekly_figures_average_a_students_own_entries(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    ia, sid = world.inst_a, s.id
    last = monday(UTC, 1)
    # last week: two moods on Monday (mean 3) and one on Tuesday (5); stress on Tuesday and
    # Wednesday; sleep on Wednesday and Thursday
    await add_mood(api_db, ia, sid, last, 4)
    await add_mood(api_db, ia, sid, last, 2, minute=1)
    await add_mood(api_db, ia, sid, last + dt.timedelta(days=1), 5)
    await add_stress(api_db, ia, sid, last + dt.timedelta(days=1), 2)
    await add_stress(api_db, ia, sid, last + dt.timedelta(days=2), 4)
    await add_sleep(api_db, ia, sid, last + dt.timedelta(days=2), 420, 4)
    await add_sleep(api_db, ia, sid, last + dt.timedelta(days=3), 360, 2)
    # this week: only Monday, mood 2 and stress 5
    this = monday(UTC)
    await add_mood(api_db, ia, sid, this, 2)
    await add_stress(api_db, ia, sid, this, 5)

    body = await analytics(s, "?weeks=4")
    weeks = body["weeks"]
    assert len(weeks) == 4
    assert [w["week_start"] for w in weeks] == [
        (this - dt.timedelta(weeks=n)).isoformat() for n in (3, 2, 1, 0)
    ]
    assert all(dt.date.fromisoformat(w["week_start"]).weekday() == 0 for w in weeks)

    prev = weeks[2]
    assert prev["mood_avg"] == 4.0  # mean of the daily means 3 and 5
    assert prev["stress_avg"] == 3.0
    assert prev["sleep_quality_avg"] == 3.0
    assert prev["sleep_hours_avg"] == 6.5
    assert prev["days_reported"] == 4  # Monday to Thursday
    assert prev["wellness_index"] == 58  # (75 + 50 + 50) / 3
    assert prev["partial"] is False

    cur = weeks[3]
    assert cur["mood_avg"] == 2.0 and cur["stress_avg"] == 5.0
    assert cur["sleep_quality_avg"] is None and cur["sleep_hours_avg"] is None
    assert cur["days_reported"] == 1
    assert cur["wellness_index"] == 13  # (25 + 0) / 2 = 12.5 rounds up
    assert cur["partial"] is True

    for quiet in weeks[:2]:
        assert quiet["days_reported"] == 0 and quiet["partial"] is False
        assert quiet["wellness_index"] is None and quiet["mood_avg"] is None
        assert quiet["stress_avg"] is None and quiet["sleep_quality_avg"] is None


async def test_only_the_current_week_is_partial_and_one_signal_gives_no_index(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await add_mood(api_db, world.inst_a, s.id, monday(UTC, 2), 5)  # mood alone
    body = await analytics(s, "?weeks=6")
    assert [w["partial"] for w in body["weeks"]] == [False] * 5 + [True]
    week = by_week(body)[monday(UTC, 2).isoformat()]
    assert week["mood_avg"] == 5.0 and week["days_reported"] == 1
    assert week["wellness_index"] is None  # one of the three is not enough


async def test_weeks_default_to_eight_and_accept_four_to_twelve(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    assert len((await analytics(s))["weeks"]) == 8
    assert len((await analytics(s, "?weeks=4"))["weeks"]) == 4
    body = await analytics(s, "?weeks=12")
    assert len(body["weeks"]) == 12
    assert body["weeks"][-1]["week_start"] == monday(UTC).isoformat()


@pytest.mark.parametrize("weeks", ["3", "13", "0", "-1", "100", "abc", "", "1.5"])
async def test_invalid_weeks_is_a_validation_error(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, weeks: str
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.get(f"{PATH}?weeks={weeks}")
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_unknown_time_zone_is_a_validation_error(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    assert (await s.get(f"{PATH}?tz=Mars/Olympus")).status_code == 422
    assert (await s.get(f"{PATH}?tz=Asia/Kolkata")).status_code == 200


@pytest.mark.parametrize("zone", [IST, LA], ids=["kolkata", "los_angeles"])
async def test_weeks_begin_on_the_students_local_monday(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, zone: ZoneInfo
) -> None:
    s = await new_student(client, api_db, world)
    ia, sid = world.inst_a, s.id
    start = monday(zone, 2)  # a Monday in the student's own zone
    before = start - dt.timedelta(days=1)  # the Sunday before it
    # just after local midnight on Monday, and just before local midnight on the Sunday
    await add_mood(api_db, ia, sid, start, 5, zone, hour=0, minute=30)
    await add_mood(api_db, ia, sid, before, 1, zone, hour=23, minute=30)
    await add_goal(
        api_db,
        ia,
        sid,
        GoalCategory.SLEEP,
        GoalStatus.COMPLETED,
        completed_at=local(start, zone, 0, 30),
    )

    tz = zone.key
    body = await analytics(s, f"?weeks=6&tz={tz}")
    weeks = by_week(body)
    assert weeks[start.isoformat()]["mood_avg"] == 5.0
    assert weeks[(start - dt.timedelta(weeks=1)).isoformat()]["mood_avg"] == 1.0
    done = {w["week_start"]: w["completed"] for w in body["goals"]["completed_by_week"]}
    assert done[start.isoformat()] == 1

    # Read in UTC the two instants fall on one UTC day (Sunday evening for Kolkata, Monday
    # morning for Los Angeles), so they are averaged together: the zone really is applied.
    utc_day = local(start, zone, 0, 30).astimezone(dt.UTC).date()
    utc_week = by_week(await analytics(s, "?weeks=6"))[
        (utc_day - dt.timedelta(days=utc_day.weekday())).isoformat()
    ]
    assert utc_week["mood_avg"] == 3.0


async def test_entries_outside_the_window_are_ignored(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await add_mood(api_db, world.inst_a, s.id, monday(UTC, 6), 1)
    body = await analytics(s, "?weeks=4")
    assert all(w["mood_avg"] is None for w in body["weeks"])
    assert by_week(await analytics(s, "?weeks=8"))[monday(UTC, 6).isoformat()]["mood_avg"] == 1.0


# ---- wellbeing checks ------------------------------------------------------------------------


async def test_wellbeing_checks_are_the_last_twelve_oldest_first(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    now = dt.datetime.now(dt.UTC)
    for i in range(14):  # raw 5 to 18, one per day, the oldest first
        await add_check(api_db, world.inst_a, s.id, 5 + i, now - dt.timedelta(days=14 - i))
    checks = (await analytics(s))["wellbeing_checks"]
    assert len(checks) == 12
    assert [c["percent"] for c in checks] == [(7 + i) * 4 for i in range(12)]
    stamps = [c["completed_at"] for c in checks]
    assert stamps == sorted(stamps)
    assert checks[0]["band"]["key"] == "lower"  # 28 %
    assert checks[6]["band"]["key"] == "mixed"  # 13 -> 52 %
    assert checks[-1]["band"]["key"] == "doing_well"  # 18 -> 72 %
    assert set(checks[0]) == {"completed_at", "percent", "band"}
    assert set(checks[0]["band"]) == {"key", "label", "message"}


async def test_wellbeing_checks_use_the_existing_band_and_percentage_rules(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    submitted = (
        await s.post("/me/wellness/assessments", {"responses": {f"q{i}": 5 for i in range(1, 6)}})
    ).json()
    (check,) = (await analytics(s))["wellbeing_checks"]
    assert check["percent"] == submitted["percent"] == 100
    assert check["band"] == submitted["band"]
    assert check["completed_at"] == submitted["completed_at"]


# ---- goals -----------------------------------------------------------------------------------


async def test_goal_counts_progress_categories_and_completions_by_week(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    ia, sid = world.inst_a, s.id
    this, two_back = monday(UTC), monday(UTC, 2)
    act, done = GoalStatus.ACTIVE, GoalStatus.COMPLETED
    await add_goal(api_db, ia, sid, GoalCategory.SLEEP, act, target=10, current=5)  # 50 %
    await add_goal(api_db, ia, sid, GoalCategory.SLEEP, act, target=4, current=1)  # 25 %
    await add_goal(api_db, ia, sid, GoalCategory.SLEEP, act)  # no target: not in the average
    await add_goal(api_db, ia, sid, GoalCategory.MOVEMENT, act, target=10, current=20)  # capped 100
    await add_goal(api_db, ia, sid, GoalCategory.MINDFULNESS, GoalStatus.PAUSED, target=5)
    await add_goal(api_db, ia, sid, GoalCategory.SOCIAL, GoalStatus.ABANDONED)
    await add_goal(api_db, ia, sid, GoalCategory.SLEEP, done, completed_at=local(this, UTC))
    await add_goal(api_db, ia, sid, GoalCategory.MOVEMENT, done, completed_at=local(two_back, UTC))
    await add_goal(
        api_db, ia, sid, GoalCategory.OTHER, done, completed_at=local(monday(UTC, 30), UTC)
    )

    goals = (await analytics(s, "?weeks=4"))["goals"]
    assert (goals["active"], goals["completed"], goals["other"]) == (4, 3, 2)
    assert goals["average_progress_percent"] == 58.3  # (50 + 25 + 100) / 3
    assert goals["by_category"] == [
        {"category": "movement", "active": 1, "completed": 1, "average_progress_percent": 100.0},
        {"category": "other", "active": 0, "completed": 1, "average_progress_percent": None},
        {"category": "sleep", "active": 3, "completed": 1, "average_progress_percent": 37.5},
    ]
    assert goals["completed_by_week"] == [
        {"week_start": (this - dt.timedelta(weeks=n)).isoformat(), "completed": c}
        for n, c in ((3, 0), (2, 1), (1, 0), (0, 1))  # the goal from 30 weeks ago is outside it
    ]


async def test_average_progress_is_null_without_any_target(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await add_goal(api_db, world.inst_a, s.id, GoalCategory.NUTRITION)
    await add_goal(api_db, world.inst_a, s.id, GoalCategory.NUTRITION, GoalStatus.PAUSED, target=5)
    goals = (await analytics(s))["goals"]
    assert goals["active"] == 1 and goals["other"] == 1
    assert goals["average_progress_percent"] is None
    assert goals["by_category"] == [
        {"category": "nutrition", "active": 1, "completed": 0, "average_progress_percent": None}
    ]


async def test_goals_completed_through_the_api_are_counted(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    goal = (
        await s.post("/me/goals", {"title": "Walk", "category": "movement", "target_value": 3})
    ).json()
    assert (await s.patch(f"/me/goals/{goal['id']}", {"current_value": 3})).json()["status"] == (
        "completed"
    )
    goals = (await analytics(s))["goals"]
    assert goals["completed"] == 1 and goals["active"] == 0
    assert goals["completed_by_week"][-1]["completed"] == 1  # completed just now


# ---- empty history ---------------------------------------------------------------------------


async def test_a_new_student_gets_empty_figures_not_an_error(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    body = await analytics(s)
    assert len(body["weeks"]) == 8
    for w in body["weeks"][:-1]:
        assert w["partial"] is False
    assert body["weeks"][-1]["partial"] is True
    for w in body["weeks"]:
        assert w["days_reported"] == 0
        for key in (
            "wellness_index",
            "mood_avg",
            "stress_avg",
            "sleep_quality_avg",
            "sleep_hours_avg",
        ):
            assert w[key] is None
    assert body["wellbeing_checks"] == []
    goals = body["goals"]
    assert (goals["active"], goals["completed"], goals["other"]) == (0, 0, 0)
    assert goals["average_progress_percent"] is None and goals["by_category"] == []
    assert [w["completed"] for w in goals["completed_by_week"]] == [0] * 8
    assert "not a diagnosis" in body["disclaimer"]


async def test_the_response_has_the_documented_shape(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    body = await analytics(s)
    assert set(body) == {"weeks", "wellbeing_checks", "goals", "disclaimer"}
    assert set(body["weeks"][0]) == {
        "week_start",
        "wellness_index",
        "mood_avg",
        "stress_avg",
        "sleep_quality_avg",
        "sleep_hours_avg",
        "days_reported",
        "partial",
    }
    assert set(body["goals"]) == {
        "active",
        "completed",
        "other",
        "average_progress_percent",
        "by_category",
        "completed_by_week",
    }


# ---- own data only ---------------------------------------------------------------------------


async def test_another_students_entries_never_change_my_numbers(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    c = await new_student(client, api_db, world, other_tenant=True)
    last = monday(UTC, 1)
    await add_mood(api_db, world.inst_a, a.id, last, 4)
    await add_stress(api_db, world.inst_a, a.id, last, 1)
    await add_goal(api_db, world.inst_a, a.id, GoalCategory.SLEEP, target=10, current=5)
    await add_check(api_db, world.inst_a, a.id, 20, dt.datetime.now(dt.UTC))
    before = await analytics(a)
    assert by_week(before)[last.isoformat()]["wellness_index"] == 88  # (75 + 100) / 2 = 87.5

    # a classmate and a student at another institution report plenty, in the same weeks
    for student, inst in ((b, world.inst_a), (c, world.inst_b)):
        for back in range(0, 4):
            day = monday(UTC, back)
            await add_mood(api_db, inst, student.id, day, 1)
            await add_stress(api_db, inst, student.id, day, 5)
            await add_sleep(api_db, inst, student.id, day, 300, 1)
        await add_goal(api_db, inst, student.id, GoalCategory.SLEEP, target=10, current=10)
        await add_goal(
            api_db,
            inst,
            student.id,
            GoalCategory.MOVEMENT,
            GoalStatus.COMPLETED,
            completed_at=dt.datetime.now(dt.UTC),
        )
        await add_check(api_db, inst, student.id, 5, dt.datetime.now(dt.UTC))

    assert await analytics(a) == before
    # and each of them sees only their own
    assert (await analytics(b))["goals"]["completed"] == 1
    assert len((await analytics(b))["wellbeing_checks"]) == 1
    assert (await analytics(c))["wellbeing_checks"][0]["percent"] == 20
    assert by_week(await analytics(b))[last.isoformat()]["mood_avg"] == 1.0


async def test_the_endpoint_takes_no_student_id(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    await add_mood(api_db, world.inst_a, b.id, monday(UTC, 1), 1)
    # an id in the query string is simply not a parameter: it cannot select someone else
    body = await analytics(a, f"?student_id={b.id}")
    assert all(w["mood_avg"] is None for w in body["weeks"])


# ---- authorization ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["therapist", "teacher", "admin"])
async def test_other_roles_are_refused(client: httpx.AsyncClient, world: World, role: str) -> None:
    token = await token_for(client, getattr(world, role), world.password)
    r = await call(client, "GET", PATH, token=token)
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_the_student_role_is_allowed(client: httpx.AsyncClient, world: World) -> None:
    token = await token_for(client, world.student, world.password)
    assert (await call(client, "GET", PATH, token=token)).status_code == 200


async def test_anonymous_is_refused(client: httpx.AsyncClient) -> None:
    r = await call(client, "GET", PATH)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
