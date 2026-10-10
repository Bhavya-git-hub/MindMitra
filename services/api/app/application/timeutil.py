"""Student-local "today": the API stores UTC and takes the viewer's IANA zone per request."""

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.errors import InvalidInput


class InvalidTimezone(InvalidInput):
    pass


def parse_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise InvalidTimezone("Unknown time zone.") from exc


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def local_today(zone: ZoneInfo, now: dt.datetime | None = None) -> dt.date:
    return (now or now_utc()).astimezone(zone).date()


def day_bounds(day: dt.date, zone: ZoneInfo) -> tuple[dt.datetime, dt.datetime]:
    """Start (inclusive) and end (exclusive) of a local calendar day, as UTC instants."""
    start = dt.datetime.combine(day, dt.time.min, tzinfo=zone)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, tzinfo=zone)
    return start.astimezone(dt.UTC), end.astimezone(dt.UTC)
