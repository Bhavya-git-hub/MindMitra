"""Administrator dashboard, platform analytics and appointment oversight (aggregates only)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.schemas import admin as s
from app.application import admin_insights
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal

router = APIRouter(prefix="/admin", tags=["admin"])
Db = Annotated[AsyncSession, Depends(get_db)]
Analytics = Annotated[Principal, Depends(require_permission(Permission.PLATFORM_ANALYTICS_READ))]
Oversight = Annotated[Principal, Depends(require_permission(Permission.APPOINTMENT_OVERSIGHT))]
Weeks = Annotated[int | None, Query(description="4, 8 or 12 completed calendar weeks")]


@router.get("/dashboard")
async def dashboard(db: Db, principal: Analytics) -> s.DashboardOut:
    return s.dashboard_out(await admin_insights.dashboard(db, principal))


@router.get("/analytics")
async def analytics(db: Db, principal: Analytics, weeks: Weeks = None) -> s.PlatformAnalyticsOut:
    return s.analytics_out(await admin_insights.platform_analytics(db, principal, weeks))


@router.get("/appointments/oversight")
async def appointment_oversight(
    db: Db, principal: Oversight, weeks: Weeks = None
) -> s.OversightOut:
    return s.oversight_out(await admin_insights.appointment_oversight(db, principal, weeks))
