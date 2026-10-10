"""The viewer's IANA time zone, passed per request as ``?tz=`` (default UTC)."""

import datetime as dt
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Query

from app.application.timeutil import day_bounds, local_today, parse_zone


def get_zone(
    tz: Annotated[str, Query(max_length=64, description="IANA zone, e.g. Asia/Kolkata")] = "UTC",
) -> ZoneInfo:
    return parse_zone(tz)


Zone = Annotated[ZoneInfo, Depends(get_zone)]


def since_days(days: int | None, zone: ZoneInfo) -> dt.datetime | None:
    """Start of the local day ``days - 1`` days ago, as a UTC instant (None: no limit)."""
    if days is None:
        return None
    return day_bounds(local_today(zone) - dt.timedelta(days=days - 1), zone)[0]
