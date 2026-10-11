"""Wellness indicators from a student's own check-ins, scored by the AI service (ADR 0011).

The student sees their own. A therapist sees them only when the student is on their care team
and has turned on ``share_ai_signals_with_care_team`` (see ``therapist_students.indicators``);
the therapist's view leaves out the tone of the student's private notes, which are not even sent
for it. Indicators are estimates from models trained on synthetic data, not a diagnosis: nothing
here raises an alert, notifies anyone or changes anything about the student. Nothing a student
wrote is logged.
"""

import dataclasses
import datetime as dt
import uuid
from collections import defaultdict
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import student_wellness
from app.application.timeutil import day_bounds, local_today
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.ml_client import (
    DayRecord,
    Indicator,
    IndicatorClient,
    IndicatorReport,
    IndicatorsUnavailable,
)

WINDOW_DAYS = 28
MAX_NOTES = 60
MAX_NOTE_CHARS = 2000
MAX_EMOTIONS = 14
MAX_STRESSORS = 8
NOTE_TONE = "sentiment"  # the one indicator read from what a student wrote


class IndicatorsOff(Exception):
    """No AI service is configured, or it could not score right now (answered with 503)."""


@dataclasses.dataclass(frozen=True)
class Result:
    window_start: dt.date
    window_end: dt.date
    checkin_days: int
    notes_considered: int
    indicators: tuple[Indicator, ...]
    disclaimer: str


def _mean(values: list[int]) -> int | None:
    # Every value is a positive 1-5 answer, so adding a half and truncating rounds half up.
    return int(sum(values) / len(values) + 0.5) if values else None


def _tags(groups: list[list[str]], limit: int) -> tuple[str, ...]:
    return tuple(sorted({t for g in groups for t in g}))[:limit]


async def collect(
    db: AsyncSession,
    student_id: uuid.UUID,
    institution_id: uuid.UUID,
    zone: ZoneInfo,
    *,
    with_notes: bool,
) -> tuple[dt.date, list[DayRecord], list[str]]:
    """The last 28 local days of check-ins, one record per day. Callers MUST have authorised
    access to this student first."""
    today = local_today(zone)
    first = today - dt.timedelta(days=WINDOW_DAYS - 1)
    start, _ = day_bounds(first, zone)

    moods = await db.execute(
        select(
            m.MoodEntry.logged_at,
            m.MoodEntry.mood_score,
            m.MoodEntry.energy_level,
            m.MoodEntry.emotions,
        ).where(
            m.MoodEntry.student_id == student_id,
            m.MoodEntry.institution_id == institution_id,
            m.MoodEntry.logged_at >= start,
        )
    )
    stresses = await db.execute(
        select(
            m.StressAssessment.completed_at,
            m.StressAssessment.perceived_stress_level,
            m.StressAssessment.stressors,
        ).where(
            m.StressAssessment.student_id == student_id,
            m.StressAssessment.institution_id == institution_id,
            m.StressAssessment.completed_at >= start,
        )
    )
    sleeps = await db.execute(
        select(
            m.SleepEntry.sleep_date,
            m.SleepEntry.duration_minutes,
            m.SleepEntry.quality,
            m.SleepEntry.bedtime,
        )
        .where(
            m.SleepEntry.student_id == student_id,
            m.SleepEntry.institution_id == institution_id,
            m.SleepEntry.sleep_date >= first,
            m.SleepEntry.sleep_date <= today,
        )
        .order_by(m.SleepEntry.bedtime)
    )

    mood_by: dict[dt.date, list[int]] = defaultdict(list)
    energy_by: dict[dt.date, list[int]] = defaultdict(list)
    emotions_by: dict[dt.date, list[list[str]]] = defaultdict(list)
    for at, score, energy, emotions in moods.all():
        day = at.astimezone(zone).date()
        mood_by[day].append(score)
        if energy is not None:
            energy_by[day].append(energy)
        emotions_by[day].append([e.lower() for e in emotions])
    stress_by: dict[dt.date, list[int]] = defaultdict(list)
    stressors_by: dict[dt.date, list[list[str]]] = defaultdict(list)
    for at, level, stressors in stresses.all():
        day = at.astimezone(zone).date()
        stress_by[day].append(level)
        stressors_by[day].append([s.lower() for s in stressors])
    sleep_by: dict[dt.date, tuple[int, int, float]] = {}
    for day, minutes, quality, bedtime in sleeps.all():
        local = bedtime.astimezone(zone)
        sleep_by[day] = (minutes, quality, round(local.hour + local.minute / 60, 2))

    days: list[DayRecord] = []
    for day in sorted(set(mood_by) | set(stress_by) | set(sleep_by)):
        if not first <= day <= today:
            continue
        sleep = sleep_by.get(day)
        days.append(
            DayRecord(
                day=day,
                mood=_mean(mood_by.get(day, [])),
                energy=_mean(energy_by.get(day, [])),
                stress=_mean(stress_by.get(day, [])),
                sleep_minutes=sleep[0] if sleep else None,
                sleep_quality=sleep[1] if sleep else None,
                bedtime_hour=sleep[2] if sleep else None,
                emotions=_tags(emotions_by.get(day, []), MAX_EMOTIONS),
                stressors=_tags(stressors_by.get(day, []), MAX_STRESSORS),
            )
        )

    notes: list[str] = []
    if with_notes:
        rows = await db.scalars(
            select(m.MoodEntry.note)
            .where(
                m.MoodEntry.student_id == student_id,
                m.MoodEntry.institution_id == institution_id,
                m.MoodEntry.logged_at >= start,
                m.MoodEntry.note.is_not(None),
            )
            .order_by(m.MoodEntry.logged_at.desc())
            .limit(MAX_NOTES)
        )
        notes = [n.strip()[:MAX_NOTE_CHARS] for n in rows if n and n.strip()]
    return today, days, notes


async def score(
    client: IndicatorClient | None, window_end: dt.date, days: list[DayRecord], notes: list[str]
) -> IndicatorReport:
    if client is None:
        raise IndicatorsOff("not configured")
    try:
        return await client.indicators(window_end, days, notes)
    except IndicatorsUnavailable as exc:
        raise IndicatorsOff(str(exc)) from exc


def result(window_end: dt.date, report: IndicatorReport, *, include_note_tone: bool) -> Result:
    shown = tuple(i for i in report.indicators if include_note_tone or i.indicator != NOTE_TONE)
    return Result(
        window_start=window_end - dt.timedelta(days=WINDOW_DAYS - 1),
        window_end=window_end,
        checkin_days=report.checkin_days,
        notes_considered=report.notes_considered if include_note_tone else 0,
        indicators=shown,
        disclaimer=report.disclaimer,
    )


async def own(
    db: AsyncSession, actor: Principal, zone: ZoneInfo, client: IndicatorClient | None
) -> Result:
    """The caller's own indicators, including the tone of their own notes."""
    student_wellness.authorize_own(db, actor, "wellness_indicator.read", "wellness_indicator")
    if client is None:
        raise IndicatorsOff("not configured")
    window_end, days, notes = await collect(
        db, actor.user_id, actor.institution_id, zone, with_notes=True
    )
    report = await score(client, window_end, days, notes)
    return result(window_end, report, include_note_tone=True)
