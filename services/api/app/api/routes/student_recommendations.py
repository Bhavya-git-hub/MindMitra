"""A student's recommendations: the open list, history, "helpful" / "not helpful", and the
settings that shape what they are offered. Every route is the caller's own; there is no student
id in any path.
"""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_indicator_client, require_permission
from app.api.schemas import student as s
from app.api.zone import Zone
from app.application import recommendation_engine, recommendation_feedback, recommendations
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db.enums import FeedbackRating, FeedbackReason, RecommendationStatus
from app.infrastructure.ml_client import IndicatorClient

router = APIRouter(prefix="/me", tags=["student"])
Db = Annotated[AsyncSession, Depends(get_db)]
RecManager = Annotated[Principal, Depends(require_permission(Permission.RECOMMENDATION_MANAGE_OWN))]
Indicators = Annotated[IndicatorClient | None, Depends(get_indicator_client)]


@router.get("/recommendations")
async def list_recommendations(
    db: Db, principal: RecManager, include_closed: bool = False
) -> list[s.RecommendationOut]:
    rows = await recommendations.list_recommendations(db, principal, include_closed=include_closed)
    return [s.recommendation_out(r) for r in rows]


@router.get("/recommendations/history")
async def recommendation_history(
    db: Db,
    principal: RecManager,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: dt.datetime | None = None,
) -> list[s.RecommendationOut]:
    """Everything suggested so far, newest first, with the student's own ratings."""
    rows = await recommendations.list_recommendations(
        db, principal, include_closed=True, limit=limit, before=before
    )
    return [s.recommendation_out(r) for r in rows]


@router.post("/recommendations/refresh")
async def refresh_recommendations(
    db: Db, principal: RecManager, zone: Zone, indicators: Indicators
) -> list[s.RecommendationOut]:
    rows = await recommendation_engine.refresh_recommendations(db, principal, zone, indicators)
    return [s.recommendation_out(r) for r in rows]


@router.get("/recommendations/preferences")
async def get_preferences(db: Db, principal: RecManager) -> s.RecommendationPreferencesOut:
    return s.preferences_out(await recommendation_feedback.get_preferences(db, principal))


@router.patch("/recommendations/preferences")
async def update_preferences(
    body: s.RecommendationPreferencesPatchIn, db: Db, principal: RecManager
) -> s.RecommendationPreferencesOut:
    sent = body.model_fields_set
    patch = recommendation_feedback.PreferencesPatch(
        preferred_formats=None if body.preferred_formats is None else tuple(body.preferred_formats),
        max_minutes=body.max_minutes if "max_minutes" in sent else recommendation_feedback.UNSET,
        muted_areas=None if body.muted_areas is None else tuple(body.muted_areas),
        use_indicators=body.use_indicators,
    )
    return s.preferences_out(await recommendation_feedback.update_preferences(db, principal, patch))


@router.patch("/recommendations/{recommendation_id}")
async def respond_to_recommendation(
    recommendation_id: uuid.UUID, body: s.RecommendationPatchIn, db: Db, principal: RecManager
) -> s.RecommendationOut:
    view = await recommendations.respond(
        db, principal, recommendation_id, RecommendationStatus(body.status)
    )
    return s.recommendation_out(view)


@router.put("/recommendations/{recommendation_id}/feedback")
async def rate_recommendation(
    recommendation_id: uuid.UUID, body: s.RecommendationFeedbackIn, db: Db, principal: RecManager
) -> s.RecommendationOut:
    """Say whether a suggestion was helpful. Saying it again replaces the earlier answer."""
    view = await recommendation_feedback.rate(
        db,
        principal,
        recommendation_id,
        FeedbackRating(body.rating),
        FeedbackReason(body.reason) if body.reason else None,
    )
    return s.recommendation_out(view)


@router.delete("/recommendations/{recommendation_id}/feedback")
async def clear_recommendation_feedback(
    recommendation_id: uuid.UUID, db: Db, principal: RecManager
) -> s.RecommendationOut:
    return s.recommendation_out(
        await recommendation_feedback.clear(db, principal, recommendation_id)
    )
