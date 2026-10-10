"""Persistent learning activity that is independent of timed study sessions.

These events prove that material was opened or completed. They never claim
assessment, mastery, hands-on ability, or exam readiness.
"""

import json

from lib.api_logic import ApiError, now_iso


EVENT_TYPES = {
    "objective_opened",
    "reading_opened",
    "lesson_completed",
    "recall_completed",
    "coach_used",
}
MAX_EVENT_KEY_CHARS = 240
MAX_METADATA_CHARS = 4000


def _event(row):
    if not row:
        return None
    payload = dict(row)
    try:
        payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
    except json.JSONDecodeError:
        payload["metadata"] = {}
    return payload


def get_objective_state(conn, objective_id):
    if conn.execute(
        "SELECT id FROM objectives WHERE id = ?", (objective_id,)
    ).fetchone() is None:
        return None
    rows = conn.execute(
        "SELECT id, objective_id, event_type, event_key, metadata_json, occurred_at "
        "FROM learning_events WHERE objective_id = ? "
        "ORDER BY occurred_at DESC, id DESC",
        (objective_id,),
    ).fetchall()
    events = [_event(row) for row in rows]
    counts = {
        event_type: sum(event["event_type"] == event_type for event in events)
        for event_type in sorted(EVENT_TYPES)
    }
    return {
        "objective_id": objective_id,
        "started": any(
            counts[event_type] > 0
            for event_type in ("reading_opened", "lesson_completed", "recall_completed")
        ),
        "lesson_completed": counts["lesson_completed"] > 0,
        "recall_completed": counts["recall_completed"] > 0,
        "counts": counts,
        "last_activity_at": events[0]["occurred_at"] if events else None,
        "recent_events": events[:12],
        "evidence_note": (
            "Learning activity proves that material was opened or completed. "
            "It does not prove assessment, mastery, hands-on ability, or exam readiness."
        ),
    }


def record_event(
    conn,
    objective_id,
    event_type,
    *,
    event_key=None,
    metadata=None,
):
    if not isinstance(objective_id, int):
        raise ApiError(400, "objective_id is required")
    if conn.execute(
        "SELECT id FROM objectives WHERE id = ?", (objective_id,)
    ).fetchone() is None:
        raise ApiError(404, "objective not found")
    if event_type not in EVENT_TYPES:
        raise ApiError(400, "invalid learning event type")
    if event_key is not None:
        if not isinstance(event_key, str) or not event_key.strip():
            raise ApiError(400, "event_key must be a non-empty string")
        event_key = event_key.strip()
        if len(event_key) > MAX_EVENT_KEY_CHARS:
            raise ApiError(400, "event_key is too long")
    metadata = metadata or {}
    if not isinstance(metadata, dict):
        raise ApiError(400, "metadata must be an object")
    metadata_json = json.dumps(
        metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if len(metadata_json) > MAX_METADATA_CHARS:
        raise ApiError(400, "metadata is too large")

    timestamp = now_iso()
    try:
        conn.execute(
            "INSERT INTO learning_events("
            "objective_id, event_type, event_key, metadata_json, occurred_at, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                objective_id,
                event_type,
                event_key,
                metadata_json,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
        if event_type == "lesson_completed":
            from lib import retention

            retention.schedule_initial(conn, objective_id, completed_at=timestamp)
    except Exception as exc:
        if event_key and "UNIQUE constraint failed: learning_events.event_key" in str(exc):
            existing = conn.execute(
                "SELECT objective_id, event_type FROM learning_events "
                "WHERE event_key = ?",
                (event_key,),
            ).fetchone()
            if (
                existing
                and existing["objective_id"] == objective_id
                and existing["event_type"] == event_type
            ):
                return get_objective_state(conn, objective_id)
            raise ApiError(409, "event_key belongs to another learning event") from exc
        raise
    return get_objective_state(conn, objective_id)


def counts_by_objective(conn):
    rows = conn.execute(
        "SELECT objective_id, event_type, COUNT(*) AS n "
        "FROM learning_events GROUP BY objective_id, event_type"
    ).fetchall()
    result = {}
    for row in rows:
        result.setdefault(row["objective_id"], {})[row["event_type"]] = row["n"]
    return result
