"""Resumable daily study-session lifecycle and bounded activity recaps."""

import json
from datetime import datetime, timedelta, timezone

from lib import study_clock
from lib.api_logic import ApiError, now_iso


EVENT_TYPES = {
    "reading_opened",
    "gap_reviewed",
    "knowledge_check_completed",
    "task_completed",
    "coach_used",
}


def _json(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _loads(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _row(row):
    return dict(row) if row else None


# A running client pings every HEARTBEAT_INTERVAL; GRACE covers a late or
# dropped ping. STALE is when we stop believing the session is live at all.
HEARTBEAT_INTERVAL_SECONDS = 60
HEARTBEAT_GRACE_SECONDS = 90
STALE_AFTER_SECONDS = 600


def _utcnow():
    return datetime.now(timezone.utc)


def _column(row, key, default=None):
    """Read a column that may be absent on older rows or plain dicts."""
    try:
        value = row[key]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _iso(value):
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _running_horizon(row):
    """Latest instant an open running segment may be credited to.

    Without this, a session whose browser was killed before it could pause
    keeps accruing wall-clock time forever -- a force quit, a dead battery or
    iOS evicting the PWA would all bank hours that were never studied.
    """
    resumed = _datetime(row["resumed_at"])
    last_seen = _column(row, "last_seen_at")
    seen = _datetime(last_seen) if last_seen else resumed
    return max(resumed, seen + timedelta(seconds=HEARTBEAT_GRACE_SECONDS))


def _effective_seconds(row, at=None):
    total = max(0, int(row["active_seconds"] or 0))
    if row["status"] == "active" and row["tracking_state"] == "running" and row["resumed_at"]:
        current = at or _utcnow()
        resumed = _datetime(row["resumed_at"])
        credited = min(current, _running_horizon(row))
        total += max(0, int((credited - resumed).total_seconds()))
    return total


def _pause_time(row, occurred_at):
    now = _utcnow()
    if occurred_at is None:
        return now
    if not isinstance(occurred_at, str) or len(occurred_at) > 64:
        raise ApiError(400, "occurred_at must be an ISO timestamp")
    try:
        value = _datetime(occurred_at)
    except (TypeError, ValueError):
        raise ApiError(400, "occurred_at must be an ISO timestamp") from None
    if value.tzinfo is None:
        raise ApiError(400, "occurred_at must include a timezone")
    if value > now + timedelta(minutes=1):
        raise ApiError(400, "occurred_at cannot be in the future")
    started = _datetime(row["started_at"])
    return max(started, min(value, now))


def _events(conn, session_id):
    return [
        {
            **dict(row),
            "metadata": _loads(row["metadata_json"], {}),
        }
        for row in conn.execute(
            "SELECT id, session_id, event_type, label, event_key, metadata_json, occurred_at "
            "FROM guided_study_events WHERE session_id = ? ORDER BY occurred_at, id",
            (session_id,),
        ).fetchall()
    ]


def _hydrate(conn, row):
    if not row:
        return None
    result = _row(row)
    result.pop("history_session_id", None)
    result.pop("deleted_at", None)
    result["task_action"] = _loads(result.pop("task_action_json"), None)
    result["recap"] = _loads(result.pop("recap_json"), None)
    result["events"] = _events(conn, result["id"])
    result["elapsed_seconds"] = _effective_seconds(result)
    if result["status"] == "active":
        result["elapsed_minutes"] = result["elapsed_seconds"] // 60
    return result


def _current_plan_context(conn):
    row = conn.execute(
        "SELECT w.id AS week_id, w.exam_id FROM plan_weeks w "
        "JOIN study_plans p ON p.id = w.plan_id "
        "ORDER BY w.week_number LIMIT 1"
    ).fetchone()
    return _row(row) or {"week_id": None, "exam_id": None}


def overview(conn, primary):
    active = conn.execute(
        "SELECT * FROM guided_study_sessions "
        "WHERE status = 'active' AND deleted_at IS NULL LIMIT 1"
    ).fetchone()
    active = reconcile_stale(conn, active)
    recent = conn.execute(
        "SELECT * FROM guided_study_sessions "
        "WHERE status = 'completed' AND deleted_at IS NULL "
        "ORDER BY ended_at DESC LIMIT 5"
    ).fetchall()
    # Local day, not UTC: bucketing by UTC date rolls "today" over at 19:00
    # Central, crediting an evening session to tomorrow.
    day_begin, day_end = study_clock.day_bounds_utc()
    today = conn.execute(
        "SELECT COALESCE(SUM(duration_minutes), 0) AS minutes, COUNT(*) AS sessions "
        "FROM guided_study_sessions WHERE status = 'completed' AND deleted_at IS NULL "
        "AND ended_at >= ? AND ended_at < ?",
        (day_begin, day_end),
    ).fetchone()
    return {
        "active": _hydrate(conn, active),
        "suggested": primary,
        "today": {"minutes": today["minutes"], "sessions": today["sessions"]},
        "recent": [_hydrate(conn, row) for row in recent],
    }


def start(conn, target_minutes, primary):
    if not isinstance(target_minutes, int) or not 5 <= target_minutes <= 240:
        raise ApiError(400, "target_minutes must be an integer between 5 and 240")
    active = conn.execute(
        "SELECT * FROM guided_study_sessions "
        "WHERE status = 'active' AND deleted_at IS NULL LIMIT 1"
    ).fetchone()
    if active:
        return _hydrate(conn, active)
    primary = primary or {}
    title = primary.get("title") or "Choose the next useful study task"
    if not isinstance(title, str) or len(title) > 500:
        raise ApiError(400, "invalid suggested task title")
    context = _current_plan_context(conn)
    ts = _iso(_utcnow())
    cur = conn.execute(
        "INSERT INTO guided_study_sessions("
        "status, started_at, target_minutes, active_seconds, tracking_state, resumed_at, "
        "last_seen_at, exam_id, week_id, task_kind, task_title, "
        "task_action_json, created_at, updated_at"
        ") VALUES ('active', ?, ?, 0, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ts,
            target_minutes,
            ts,
            ts,
            context["exam_id"],
            context["week_id"],
            primary.get("kind"),
            title,
            _json(primary.get("action")) if primary.get("action") else None,
            ts,
            ts,
        ),
    )
    conn.commit()
    return _hydrate(
        conn,
        conn.execute(
            "SELECT * FROM guided_study_sessions WHERE id = ?", (cur.lastrowid,)
        ).fetchone(),
    )


def pause(conn, session_id, occurred_at=None):
    row = conn.execute(
        "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise ApiError(404, "study session not found")
    if row["status"] != "active":
        raise ApiError(409, "study session is not active")
    if row["tracking_state"] == "running":
        paused_at = _pause_time(row, occurred_at)
        resumed_at = _datetime(row["resumed_at"] or row["started_at"])
        paused_at = max(resumed_at, paused_at)
        active_seconds = max(0, int(row["active_seconds"] or 0)) + max(
            0, int((paused_at - resumed_at).total_seconds())
        )
        ts = _iso(_utcnow())
        conn.execute(
            "UPDATE guided_study_sessions SET active_seconds = ?, tracking_state = 'paused', "
            "resumed_at = NULL, updated_at = ? WHERE id = ?",
            (active_seconds, ts, session_id),
        )
        conn.commit()
    return _hydrate(
        conn,
        conn.execute(
            "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
        ).fetchone(),
    )


def heartbeat(conn, session_id):
    """Record that the client is still alive, extending the credit horizon."""
    row = conn.execute(
        "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise ApiError(404, "study session not found")
    if row["status"] != "active":
        raise ApiError(409, "study session is not active")
    ts = _iso(_utcnow())
    conn.execute(
        "UPDATE guided_study_sessions SET last_seen_at = ?, updated_at = ? WHERE id = ?",
        (ts, ts, session_id),
    )
    conn.commit()
    return _hydrate(
        conn,
        conn.execute(
            "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
        ).fetchone(),
    )


def reconcile_stale(conn, row):
    """Pause a running session whose client stopped proving it was alive.

    Self-healing on read, so a session abandoned by a crash settles at its
    real last-seen time instead of sitting 'recording' indefinitely.
    """
    if not row or row["status"] != "active" or row["tracking_state"] != "running":
        return row
    if not row["resumed_at"]:
        return row
    horizon = _running_horizon(row)
    if _utcnow() - horizon <= timedelta(seconds=STALE_AFTER_SECONDS):
        return row
    pause(conn, row["id"], _iso(horizon))
    return conn.execute(
        "SELECT * FROM guided_study_sessions WHERE id = ?", (row["id"],)
    ).fetchone()


def resume(conn, session_id):
    row = conn.execute(
        "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise ApiError(404, "study session not found")
    if row["status"] != "active":
        raise ApiError(409, "study session is not active")
    if row["tracking_state"] == "paused":
        ts = _iso(_utcnow())
        conn.execute(
            "UPDATE guided_study_sessions SET tracking_state = 'running', resumed_at = ?, "
            "last_seen_at = ?, updated_at = ? WHERE id = ?",
            (ts, ts, ts, session_id),
        )
        conn.commit()
    return _hydrate(
        conn,
        conn.execute(
            "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
        ).fetchone(),
    )


def log_event(conn, event_type, label, event_key=None, metadata=None):
    if event_type not in EVENT_TYPES:
        raise ApiError(400, "unsupported study event type")
    if not isinstance(label, str) or not label.strip() or len(label) > 500:
        raise ApiError(400, "event label must be between 1 and 500 characters")
    if event_key is not None and (
        not isinstance(event_key, str) or not event_key or len(event_key) > 200
    ):
        raise ApiError(400, "event_key must be a non-empty string under 200 characters")
    if metadata is not None and not isinstance(metadata, dict):
        raise ApiError(400, "metadata must be an object")
    active = conn.execute(
        "SELECT id FROM guided_study_sessions WHERE status = 'active' LIMIT 1"
    ).fetchone()
    if not active:
        raise ApiError(409, "no active study session")
    ts = now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO guided_study_events("
        "session_id, event_type, label, event_key, metadata_json, occurred_at"
        ") VALUES (?, ?, ?, ?, ?, ?)",
        (
            active["id"],
            event_type,
            label.strip(),
            event_key,
            _json(metadata or {}),
            ts,
        ),
    )
    conn.execute(
        "UPDATE guided_study_sessions SET updated_at = ? WHERE id = ?",
        (ts, active["id"]),
    )
    conn.commit()
    return _hydrate(
        conn,
        conn.execute(
            "SELECT * FROM guided_study_sessions WHERE id = ?", (active["id"],)
        ).fetchone(),
    )


def _recap(task_title, events):
    counts = {event_type: 0 for event_type in EVENT_TYPES}
    for event in events:
        counts[event["event_type"]] += 1
    lines = []
    if counts["gap_reviewed"]:
        lines.append(f"Reviewed {counts['gap_reviewed']} missed question"
                     f"{'s' if counts['gap_reviewed'] != 1 else ''}.")
    if counts["reading_opened"]:
        lines.append(f"Opened {counts['reading_opened']} cited book section"
                     f"{'s' if counts['reading_opened'] != 1 else ''}.")
    if counts["knowledge_check_completed"]:
        lines.append(f"Completed {counts['knowledge_check_completed']} knowledge check"
                     f"{'s' if counts['knowledge_check_completed'] != 1 else ''}.")
    if counts["task_completed"]:
        lines.append(f"Completed {counts['task_completed']} curriculum task"
                     f"{'s' if counts['task_completed'] != 1 else ''}.")
    if counts["coach_used"]:
        lines.append(f"Used Study Coach {counts['coach_used']} time"
                     f"{'s' if counts['coach_used'] != 1 else ''}.")
    if not lines:
        lines.append(f"Focused on {task_title}.")
    return {"counts": counts, "lines": lines}


def finish(conn, session_id, notes=None):
    row = conn.execute(
        "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise ApiError(404, "study session not found")
    if row["status"] != "active":
        raise ApiError(409, "study session is not active")
    if notes is not None and (not isinstance(notes, str) or len(notes) > 2000):
        raise ApiError(400, "notes must be a string under 2000 characters")
    ended_dt = _utcnow()
    ended = _iso(ended_dt)
    # Finishing is itself proof the client is alive right now, so the final
    # segment is credited in full instead of being clamped to the last ping.
    conn.execute(
        "UPDATE guided_study_sessions SET last_seen_at = ? WHERE id = ?", (ended, session_id)
    )
    row = conn.execute(
        "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    active_seconds = _effective_seconds(row, ended_dt)
    duration = max(1, min(1440, round(active_seconds / 60)))
    events = _events(conn, session_id)
    recap = _recap(row["task_title"], events)
    legacy_notes = " ".join(recap["lines"])
    if notes and notes.strip():
        legacy_notes += f" Notes: {notes.strip()}"
    conn.execute(
        "UPDATE guided_study_sessions SET status = 'completed', ended_at = ?, "
        "duration_minutes = ?, active_seconds = ?, tracking_state = 'paused', resumed_at = NULL, "
        "notes = ?, recap_json = ?, updated_at = ? WHERE id = ?",
        (ended, duration, active_seconds, notes.strip() if notes else None, _json(recap), ended, session_id),
    )
    history = conn.execute(
        "INSERT INTO study_sessions(occurred_at, duration_minutes, exam_id, week_id, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (row["started_at"], duration, row["exam_id"], row["week_id"], legacy_notes, ended),
    )
    conn.execute(
        "UPDATE guided_study_sessions SET history_session_id = ? WHERE id = ?",
        (history.lastrowid, session_id),
    )
    conn.commit()
    return _hydrate(
        conn,
        conn.execute(
            "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
        ).fetchone(),
    )


def abandon(conn, session_id):
    row = conn.execute(
        "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise ApiError(404, "study session not found")
    if row["status"] != "active":
        raise ApiError(409, "study session is not active")
    ended_dt = _utcnow()
    ts = _iso(ended_dt)
    active_seconds = _effective_seconds(row, ended_dt)
    conn.execute(
        "UPDATE guided_study_sessions SET status = 'abandoned', ended_at = ?, "
        "active_seconds = ?, tracking_state = 'paused', resumed_at = NULL, updated_at = ? WHERE id = ?",
        (ts, active_seconds, ts, session_id),
    )
    conn.commit()
    return _hydrate(
        conn,
        conn.execute(
            "SELECT * FROM guided_study_sessions WHERE id = ?", (session_id,)
        ).fetchone(),
    )


def history(conn, limit=50):
    try:
        limit = max(1, min(int(limit or 50), 100))
    except (TypeError, ValueError):
        raise ApiError(400, "limit must be an integer") from None
    rows = conn.execute(
        "SELECT * FROM guided_study_sessions "
        "WHERE status = 'completed' AND deleted_at IS NULL "
        "ORDER BY ended_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_hydrate(conn, row) for row in rows]


def delete_recorded(conn, session_id):
    row = conn.execute(
        "SELECT * FROM guided_study_sessions WHERE id = ? AND deleted_at IS NULL",
        (session_id,),
    ).fetchone()
    if not row:
        raise ApiError(404, "recorded study session not found")
    if row["status"] != "completed":
        raise ApiError(409, "only completed study sessions can be deleted")
    deleted_at = _iso(_utcnow())
    conn.execute(
        "UPDATE guided_study_sessions SET deleted_at = ?, updated_at = ? WHERE id = ?",
        (deleted_at, deleted_at, session_id),
    )
    if row["history_session_id"] is not None:
        conn.execute(
            "DELETE FROM study_sessions WHERE id = ?",
            (row["history_session_id"],),
        )
    conn.commit()
    return {"id": session_id, "deleted": True, "deleted_at": deleted_at}
