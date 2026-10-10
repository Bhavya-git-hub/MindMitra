"""Wellness goals: a student's own, private to them."""

import dataclasses
import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce
from app.application.errors import InvalidInput
from app.application.student_wellness import MAX_LIMIT, authorize_own
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal, can_use_own_student_record
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import GoalCategory, GoalStatus
from app.infrastructure.db.ids import uuid7

MAX_ACTIVE_GOALS = 10
UNSET: object = object()


@dataclasses.dataclass(frozen=True)
class GoalInput:
    title: str
    category: GoalCategory
    description: str | None = None
    target_value: Decimal | None = None
    unit: str | None = None
    target_date: dt.date | None = None


async def create_goal(db: AsyncSession, actor: Principal, data: GoalInput) -> m.WellnessGoal:
    authorize_own(db, actor, "goal.create", "wellness_goal")
    title = " ".join(data.title.split())
    if not title:
        raise InvalidInput("Please give your goal a title.")
    today = now_utc().date()
    if data.target_date is not None and data.target_date < today:
        raise InvalidInput("The target date can't be in the past.")
    active = await db.scalars(
        select(m.WellnessGoal.id).where(
            m.WellnessGoal.student_id == actor.user_id,
            m.WellnessGoal.institution_id == actor.institution_id,
            m.WellnessGoal.status == GoalStatus.ACTIVE,
        )
    )
    if len(list(active)) >= MAX_ACTIVE_GOALS:
        raise InvalidInput(
            f"You have {MAX_ACTIVE_GOALS} active goals. Finish or pause one before adding another."
        )
    goal = m.WellnessGoal(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=actor.user_id,
        title=title,
        description=(data.description or "").strip() or None,
        category=data.category,
        status=GoalStatus.ACTIVE,
        target_value=data.target_value,
        current_value=Decimal(0),
        unit=(data.unit or "").strip() or None,
        start_date=today,
        target_date=data.target_date,
    )
    db.add(goal)
    await db.flush()
    await db.commit()
    return goal


async def list_goals(
    db: AsyncSession, actor: Principal, status: GoalStatus | None, limit: int
) -> list[m.WellnessGoal]:
    authorize_own(db, actor, "goal.list", "wellness_goal")
    stmt = select(m.WellnessGoal).where(
        m.WellnessGoal.student_id == actor.user_id,
        m.WellnessGoal.institution_id == actor.institution_id,
    )
    if status is not None:
        stmt = stmt.where(m.WellnessGoal.status == status)
    rows = await db.scalars(
        stmt.order_by(m.WellnessGoal.created_at.desc()).limit(min(limit, MAX_LIMIT))
    )
    return list(rows)


@dataclasses.dataclass(frozen=True)
class GoalPatch:
    title: str | None = None
    description: object = UNSET  # None clears it
    current_value: Decimal | None = None
    target_value: object = UNSET
    target_date: object = UNSET
    status: GoalStatus | None = None


async def update_goal(
    db: AsyncSession, actor: Principal, goal_id: uuid.UUID, patch: GoalPatch
) -> m.WellnessGoal:
    goal = await db.get(m.WellnessGoal, goal_id, with_for_update=True)
    if goal is None:
        raise NotFound
    enforce(
        can_use_own_student_record(
            actor, student_id=goal.student_id, institution_id=goal.institution_id
        ),
        action="goal.update",
        resource_type="wellness_goal",
        resource_id=goal.id,
        subject_student_id=goal.student_id,
    )
    if patch.title is not None:
        title = " ".join(patch.title.split())
        if not title:
            raise InvalidInput("Please give your goal a title.")
        goal.title = title
    if patch.description is not UNSET:
        text = patch.description
        goal.description = text.strip() or None if isinstance(text, str) else None
    if patch.target_value is not UNSET:
        goal.target_value = patch.target_value if isinstance(patch.target_value, Decimal) else None
    if patch.target_date is not UNSET:
        value = patch.target_date
        if isinstance(value, dt.date) and value < goal.start_date:
            raise InvalidInput("The target date can't be before the start date.")
        goal.target_date = value if isinstance(value, dt.date) else None
    if patch.current_value is not None:
        goal.current_value = patch.current_value

    status = patch.status or goal.status
    reached = (
        goal.target_value is not None
        and goal.current_value >= goal.target_value
        and status is GoalStatus.ACTIVE
    )
    if reached:
        status = GoalStatus.COMPLETED  # reaching the target completes the goal
    if status is GoalStatus.COMPLETED and goal.completed_at is None:
        goal.completed_at = now_utc()
    if status is not GoalStatus.COMPLETED:
        goal.completed_at = None
    goal.status = status
    await db.flush()
    await db.commit()
    return goal
