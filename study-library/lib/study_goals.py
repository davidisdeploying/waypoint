"""Weekly study-time goal: one daily rate chosen per week, tracked live.

The goal is a rate ("45 minutes a day") rather than a lump weekly total, so
the weekly target is that rate times seven. Progress counts every completed
session in the local week plus whatever the currently running session has
already banked, so the bar moves while studying instead of jumping at the end.

Only real recorded time counts. Nothing here creates, extends, or estimates a
session; if tracking paused because you stepped away, the bar stops with it.
"""

from __future__ import annotations

from datetime import timedelta

from lib import study_clock
from lib.api_logic import ApiError, now_iso

PRESET_MINUTES = (30, 45, 60)
MIN_DAILY_MINUTES = 5
MAX_DAILY_MINUTES = 240
DAYS_PER_WEEK = 7


def _validate_daily_minutes(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(400, "daily_target_minutes must be an integer")
    if not MIN_DAILY_MINUTES <= value <= MAX_DAILY_MINUTES:
        raise ApiError(
            400,
            f"daily_target_minutes must be between {MIN_DAILY_MINUTES} and {MAX_DAILY_MINUTES}",
        )
    return value


def _goal_row(conn, week_start):
    return conn.execute(
        "SELECT week_start, daily_target_minutes FROM study_week_goals WHERE week_start = ?",
        (week_start.isoformat(),),
    ).fetchone()


def set_goal(conn, daily_target_minutes, week_start=None):
    """Set (or change) the current week's rate. Past weeks are not rewritten."""
    minutes = _validate_daily_minutes(daily_target_minutes)
    monday = week_start or study_clock.week_start()
    ts = now_iso()
    conn.execute(
        "INSERT INTO study_week_goals(week_start, daily_target_minutes, created_at, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(week_start) DO UPDATE SET "
        "  daily_target_minutes = excluded.daily_target_minutes, updated_at = excluded.updated_at",
        (monday.isoformat(), minutes, ts, ts),
    )
    conn.commit()
    return get_goal(conn, week_start=monday)


def _completed_minutes(conn, begin_utc, end_utc):
    row = conn.execute(
        "SELECT COALESCE(SUM(duration_minutes), 0) AS minutes, COUNT(*) AS sessions "
        "FROM guided_study_sessions "
        "WHERE status = 'completed' AND deleted_at IS NULL "
        "AND ended_at >= ? AND ended_at < ?",
        (begin_utc, end_utc),
    ).fetchone()
    return int(row["minutes"] or 0), int(row["sessions"] or 0)


def _active_seconds(conn, begin_utc, end_utc, effective_seconds, now_utc):
    """Banked seconds of the running session, credited to the week it would end in.

    A running session has no ended_at yet, so there is nothing to bucket by the
    week-it-ended rule _completed_minutes uses. The week containing right now is
    where the session would land if it ended this instant, so that -- not
    started_at -- is what has to gate the live view: otherwise a session that
    started last week but is still running now would show 0 live minutes here
    (started_at fails this week's bounds) and then jump to full credit the
    moment it closes and ended_at lands in this week.
    """
    row = conn.execute(
        "SELECT * FROM guided_study_sessions "
        "WHERE status = 'active' AND deleted_at IS NULL LIMIT 1"
    ).fetchone()
    if not row:
        return 0
    if not (begin_utc <= now_utc < end_utc):
        return 0
    return max(0, int(effective_seconds(row)))


def get_goal(conn, week_start=None, effective_seconds=None, now_utc=None):
    """Current-week goal and progress, including the live active session."""
    monday = week_start or study_clock.week_start()
    begin_utc, end_utc = study_clock.week_bounds_utc(monday)
    row = _goal_row(conn, monday)
    daily = int(row["daily_target_minutes"]) if row else None
    weekly_target = daily * DAYS_PER_WEEK if daily else None

    completed, sessions = _completed_minutes(conn, begin_utc, end_utc)
    live_minutes = 0
    if effective_seconds is not None:
        live_minutes = _active_seconds(
            conn, begin_utc, end_utc, effective_seconds, now_utc or now_iso()
        ) // 60
    minutes_done = completed + live_minutes

    days = []
    for offset in range(DAYS_PER_WEEK):
        day = monday + timedelta(days=offset)
        day_begin, day_end = study_clock.day_bounds_utc(day)
        day_minutes, _ = _completed_minutes(conn, day_begin, day_end)
        days.append({
            "date": day.isoformat(),
            "minutes": day_minutes,
            "met_target": bool(daily and day_minutes >= daily),
        })

    return {
        "week_start": monday.isoformat(),
        "week_begin_utc": begin_utc,
        "week_end_utc": end_utc,
        "timezone": str(study_clock.study_zone()),
        "daily_target_minutes": daily,
        "weekly_target_minutes": weekly_target,
        "minutes_done": minutes_done,
        "completed_minutes": completed,
        "live_minutes": live_minutes,
        "sessions": sessions,
        # Deliberately uncapped denominators stay honest: percent is clamped for
        # the bar, but minutes_done is not, so a big week still reads as a big week.
        "percent": (
            min(100, round(minutes_done / weekly_target * 100)) if weekly_target else None
        ),
        "minutes_remaining": max(0, weekly_target - minutes_done) if weekly_target else None,
        "needs_selection": daily is None,
        "presets": list(PRESET_MINUTES),
        "days": days,
    }
