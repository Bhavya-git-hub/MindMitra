"""A student's "helpful" or "not helpful" on a suggestion, and what they want from suggestions.

Both are the student's alone. They are never shown to a therapist, teacher or admin, are not
part of any group figure, and only tune what this student is offered next. The reason for "not
helpful" is a fixed list rather than free text so it can hold nothing sensitive.
"""

import dataclasses
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import recommendations
from app.application.errors import InvalidInput
from app.application.student_wellness import authorize_own
from app.domain.auth.policies import Principal
from app.domain.wellness.recommender.catalog import MUTABLE_AREAS
from app.domain.wellness.recommender.ranking import Preferences
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    FeedbackRating,
    FeedbackReason,
    RecommendationStatus,
    ResourceType,
)
from app.infrastructure.db.ids import uuid7

MAX_MINUTES = 180
FORMATS = tuple(t.value for t in ResourceType)


class Unset:
    """Marks a field the caller did not send (so ``None`` can mean "no limit")."""


UNSET = Unset()


@dataclasses.dataclass(frozen=True)
class StoredPreferences:
    preferred_formats: tuple[str, ...] = ()
    max_minutes: int | None = None
    muted_areas: tuple[str, ...] = ()
    use_indicators: bool = True


@dataclasses.dataclass(frozen=True)
class PreferencesPatch:
    preferred_formats: tuple[str, ...] | None = None
    max_minutes: int | None | Unset = UNSET
    muted_areas: tuple[str, ...] | None = None
    use_indicators: bool | None = None


def _stored(row: m.RecommendationPreference | None) -> StoredPreferences:
    if row is None:
        return StoredPreferences()
    return StoredPreferences(
        tuple(row.preferred_formats), row.max_minutes, tuple(row.muted_areas), row.use_indicators
    )


async def load_preferences(db: AsyncSession, actor: Principal) -> StoredPreferences:
    """The caller's settings, or the defaults when they have never changed any. The caller must
    already be authorised for this student."""
    return _stored(await db.get(m.RecommendationPreference, actor.user_id))


def to_ranking(prefs: StoredPreferences, locale: str | None) -> Preferences:
    return Preferences(
        formats=frozenset(prefs.preferred_formats),
        max_minutes=prefs.max_minutes,
        muted=frozenset(prefs.muted_areas),
        locale=locale,
    )


async def get_preferences(db: AsyncSession, actor: Principal) -> StoredPreferences:
    authorize_own(db, actor, "recommendation.preferences.read", "recommendation_preference")
    return await load_preferences(db, actor)


def _check(values: tuple[str, ...], allowed: tuple[str, ...], what: str) -> tuple[str, ...]:
    unknown = sorted(set(values) - set(allowed))
    if unknown:
        raise InvalidInput(f"Unknown {what}: {', '.join(unknown)}")
    return tuple(sorted(set(values)))


async def update_preferences(
    db: AsyncSession, actor: Principal, patch: PreferencesPatch
) -> StoredPreferences:
    authorize_own(db, actor, "recommendation.preferences.update", "recommendation_preference")
    await db.execute(
        insert(m.RecommendationPreference)
        .values(
            student_id=actor.user_id,
            institution_id=actor.institution_id,
            preferred_formats=[],
            muted_areas=[],
            use_indicators=True,
        )
        .on_conflict_do_nothing(index_elements=[m.RecommendationPreference.student_id])
    )
    row = await db.get(m.RecommendationPreference, actor.user_id, with_for_update=True)
    if row is None:  # cannot happen: the row was just inserted or already exists
        raise RuntimeError("preferences row missing after upsert")
    if patch.preferred_formats is not None:
        row.preferred_formats = list(_check(patch.preferred_formats, FORMATS, "format"))
    if patch.muted_areas is not None:
        row.muted_areas = list(_check(patch.muted_areas, MUTABLE_AREAS, "topic"))
    if not isinstance(patch.max_minutes, Unset):
        if patch.max_minutes is not None and not 1 <= patch.max_minutes <= MAX_MINUTES:
            raise InvalidInput(f"Time limit must be between 1 and {MAX_MINUTES} minutes")
        row.max_minutes = patch.max_minutes
    if patch.use_indicators is not None:
        row.use_indicators = patch.use_indicators
    await db.flush()
    result = _stored(row)
    await db.commit()
    return result


async def _existing(
    db: AsyncSession, recommendation_id: uuid.UUID
) -> m.RecommendationFeedback | None:
    return await db.scalar(
        select(m.RecommendationFeedback).where(
            m.RecommendationFeedback.recommendation_id == recommendation_id
        )
    )


async def rate(
    db: AsyncSession,
    actor: Principal,
    recommendation_id: uuid.UUID,
    rating: FeedbackRating,
    reason: FeedbackReason | None,
) -> recommendations.RecommendationView:
    """Record "helpful" or "not helpful"; rating again replaces the earlier answer. A suggestion
    marked not helpful leaves the open list."""
    if reason is not None and rating != FeedbackRating.NOT_HELPFUL:
        raise InvalidInput("A reason can only be given with 'not helpful'")
    rec = await recommendations.load_own(
        db, actor, recommendation_id, "recommendation.feedback.write"
    )
    # One answer per suggestion. Two quick taps must not race into a unique-key error, so the
    # write is an upsert rather than a check followed by an insert.
    await db.execute(
        insert(m.RecommendationFeedback)
        .values(
            id=uuid7(),
            institution_id=rec.institution_id,
            student_id=rec.student_id,
            recommendation_id=rec.id,
            rating=rating,
            reason=reason,
        )
        .on_conflict_do_update(
            index_elements=[m.RecommendationFeedback.recommendation_id],
            set_={"rating": rating, "reason": reason},
        )
    )
    if rating == FeedbackRating.NOT_HELPFUL and rec.status in recommendations.OPEN_STATUSES:
        rec.status = RecommendationStatus.DISMISSED
    await db.flush()
    view = await recommendations.get_view(db, actor, rec.id)
    await db.commit()
    return view


async def clear(
    db: AsyncSession, actor: Principal, recommendation_id: uuid.UUID
) -> recommendations.RecommendationView:
    """Take back a rating."""
    rec = await recommendations.load_own(
        db, actor, recommendation_id, "recommendation.feedback.write"
    )
    row = await _existing(db, rec.id)
    if row is not None:
        await db.delete(row)
        await db.flush()
    view = await recommendations.get_view(db, actor, rec.id)
    await db.commit()
    return view
