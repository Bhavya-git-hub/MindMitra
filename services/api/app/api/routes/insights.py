"""Aggregated insights for teachers (own department) and administrators."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.application import insights
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal

router = APIRouter(prefix="/insights", tags=["insights"])


class MoodSummaryOut(BaseModel):
    department_id: uuid.UUID | None
    window_days: int
    cohort_size: int | None
    average_mood: float | None
    suppressed: bool
    disclaimer: str = (
        "Aggregated self-reported check-ins. Not a measure of any individual and not a "
        "clinical assessment. Groups smaller than 10 students are not shown."
    )


@router.get("/mood-summary")
async def mood_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.INSIGHTS_READ_AGGREGATE))
    ],
    department_id: uuid.UUID | None = None,
) -> MoodSummaryOut:
    s = await insights.mood_summary(db, principal, department_id)
    return MoodSummaryOut(
        department_id=s.department_id,
        window_days=s.window_days,
        cohort_size=s.cohort_size,
        average_mood=s.average_mood,
        suppressed=s.suppressed,
    )
