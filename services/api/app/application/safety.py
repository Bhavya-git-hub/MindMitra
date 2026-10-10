"""Crisis contacts shown on the emergency page."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m


async def crisis_contacts(db: AsyncSession, actor: Principal) -> list[m.CrisisContact]:
    """Active contacts for the caller's institution plus the national ones, in display order."""
    rows = await db.scalars(
        select(m.CrisisContact)
        .where(
            m.CrisisContact.is_active.is_(True),
            or_(
                m.CrisisContact.institution_id.is_(None),
                m.CrisisContact.institution_id == actor.institution_id,
            ),
        )
        .order_by(m.CrisisContact.sort_order, m.CrisisContact.label)
    )
    return list(rows)
