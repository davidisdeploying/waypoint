"""Local-time day and week boundaries for study accounting.

Study time is stored in UTC, but a study *day* is a human day. Bucketing by
UTC date rolls the day over at 19:00 Central, which would credit an evening
session to tomorrow and quietly break a daily or weekly goal. Everything that
answers "which day/week does this belong to" goes through here.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "America/Chicago"


def study_zone():
    """The configured local zone, falling back to UTC if it is unknown."""
    name = os.environ.get("WAYPOINT_STUDY_TIMEZONE") or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def parse_utc(value):
    """Parse a stored ISO timestamp as an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def local_date(value, zone=None):
    """The local calendar date a stored UTC timestamp falls on."""
    parsed = parse_utc(value)
    if parsed is None:
        return None
    return parsed.astimezone(zone or study_zone()).date()


def today(zone=None, now=None):
    zone = zone or study_zone()
    current = now or datetime.now(timezone.utc)
    return current.astimezone(zone).date()


def week_start(value=None, zone=None, now=None):
    """The Monday on or before ``value`` (default: today), in local time."""
    zone = zone or study_zone()
    day = value if isinstance(value, date) else today(zone=zone, now=now)
    return day - timedelta(days=day.weekday())


def week_bounds_utc(start=None, zone=None, now=None):
    """UTC half-open range [monday 00:00, next monday 00:00) for a local week.

    Returned as ISO strings so callers can compare directly against the stored
    timestamps without converting every row.
    """
    zone = zone or study_zone()
    monday = start if isinstance(start, date) else week_start(zone=zone, now=now)
    begin = datetime.combine(monday, time.min, tzinfo=zone)
    end = datetime.combine(monday + timedelta(days=7), time.min, tzinfo=zone)
    return begin.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


def day_bounds_utc(day=None, zone=None, now=None):
    """UTC half-open range covering one local day."""
    zone = zone or study_zone()
    target = day if isinstance(day, date) else today(zone=zone, now=now)
    begin = datetime.combine(target, time.min, tzinfo=zone)
    end = datetime.combine(target + timedelta(days=1), time.min, tzinfo=zone)
    return begin.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()
