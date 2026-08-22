"""Objective-level spaced-retention scheduling.

Retention reviews are active-recall learning evidence, not assessment mastery.
The schedule is deterministic and local; no model decides when an item is due.
"""

from datetime import datetime, timedelta, timezone

from lib.api_logic import ApiError, now_iso


RATINGS = {"again", "hard", "good", "easy"}
INTERVALS = (1, 3, 7, 14, 30, 60, 90, 120)
MAX_EVENT_KEY_CHARS = 240


def _parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(500, "invalid retention timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _state(row, now=None):
    if not row:
        return None
    payload = dict(row)
    current = now or datetime.now(timezone.utc)
    payload["due"] = _parse_timestamp(payload["due_at"]) <= current
    payload["evidence_note"] = (
        "A retention review records active recall and schedules another review. "
        "It does not create assessment mastery or exam-readiness evidence."
    )
    return payload


def get_objective_state(conn, objective_id):
    row = conn.execute(
        "SELECT objective_id, stage, interval_days, due_at, last_reviewed_at, "
        "last_rating, review_count, created_at, updated_at "
        "FROM objective_retention_state WHERE objective_id = ?",
        (objective_id,),
    ).fetchone()
    return _state(row)


def schedule_initial(conn, objective_id, *, completed_at=None):
    """Schedule the first review one day after a completed lesson.

    Existing schedules are never moved by duplicate completion events.
    """
    timestamp = completed_at or now_iso()
    due = (_parse_timestamp(timestamp) + timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO objective_retention_state("
        "objective_id, stage, interval_days, due_at, last_reviewed_at, "
        "last_rating, review_count, created_at, updated_at"
        ") VALUES (?, 0, 1, ?, NULL, NULL, 0, ?, ?)",
        (objective_id, due, timestamp, timestamp),
    )
    conn.commit()
    return get_objective_state(conn, objective_id)


def _next_schedule(state, rating):
    stage = int(state["stage"])
    current_interval = int(state["interval_days"])
    if rating == "again":
        return 0, 1
    if rating == "hard":
        return max(1, stage), min(120, max(2, current_interval + 1))
    advance = 1 if rating == "good" else 2
    next_stage = min(len(INTERVALS) - 1, stage + advance)
    return next_stage, INTERVALS[next_stage]


def record_review(conn, objective_id, rating, *, event_key=None, reviewed_at=None):
    if not isinstance(objective_id, int):
        raise ApiError(400, "objective_id is required")
    if rating not in RATINGS:
        raise ApiError(400, "rating must be again, hard, good, or easy")
    if event_key is not None:
        if not isinstance(event_key, str) or not event_key.strip():
            raise ApiError(400, "event_key must be a non-empty string")
        event_key = event_key.strip()
        if len(event_key) > MAX_EVENT_KEY_CHARS:
            raise ApiError(400, "event_key is too long")

    state = get_objective_state(conn, objective_id)
    if state is None:
        completed = conn.execute(
            "SELECT occurred_at FROM learning_events "
            "WHERE objective_id = ? AND event_type = 'lesson_completed' "
            "ORDER BY occurred_at DESC, id DESC LIMIT 1",
            (objective_id,),
        ).fetchone()
        if completed is None:
            raise ApiError(409, "complete the lesson before scheduling retention")
        state = schedule_initial(
            conn, objective_id, completed_at=completed["occurred_at"]
        )

    timestamp = reviewed_at or now_iso()
    next_stage, interval = _next_schedule(state, rating)
    next_due = (_parse_timestamp(timestamp) + timedelta(days=interval)).isoformat()
    try:
        conn.execute(
            "INSERT INTO objective_retention_reviews("
            "objective_id, rating, previous_stage, next_stage, previous_due_at, "
            "next_due_at, interval_days, event_key, occurred_at, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                objective_id,
                rating,
                state["stage"],
                next_stage,
                state["due_at"],
                next_due,
                interval,
                event_key,
                timestamp,
                timestamp,
            ),
        )
        conn.execute(
            "UPDATE objective_retention_state SET stage = ?, interval_days = ?, "
            "due_at = ?, last_reviewed_at = ?, last_rating = ?, "
            "review_count = review_count + 1, updated_at = ? WHERE objective_id = ?",
            (
                next_stage,
                interval,
                next_due,
                timestamp,
                rating,
                timestamp,
                objective_id,
            ),
        )
        conn.commit()
    except Exception as exc:
        if event_key and "UNIQUE constraint failed" in str(exc):
            existing = conn.execute(
                "SELECT objective_id, rating FROM objective_retention_reviews "
                "WHERE event_key = ?",
                (event_key,),
            ).fetchone()
            if (
                existing
                and existing["objective_id"] == objective_id
                and existing["rating"] == rating
            ):
                return get_objective_state(conn, objective_id)
            raise ApiError(409, "event_key belongs to another retention review") from exc
        raise
    return get_objective_state(conn, objective_id)


def get_queue(conn, *, exam=None, horizon_days=7, limit=50):
    try:
        horizon_days = max(1, min(int(horizon_days), 30))
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "horizon_days and limit must be integers") from exc
    current = datetime.now(timezone.utc)
    horizon = (current + timedelta(days=horizon_days)).isoformat()
    params = [horizon]
    exam_clause = ""
    if exam:
        exam_clause = " AND e.code = ?"
        params.append(exam)
    rows = conn.execute(
        "SELECT r.objective_id, r.stage, r.interval_days, r.due_at, "
        "r.last_reviewed_at, r.last_rating, r.review_count, "
        "o.code, o.description, e.code AS exam_code, "
        "d.code AS domain_code, d.name AS domain_name "
        "FROM objective_retention_state r "
        "JOIN objectives o ON o.id = r.objective_id "
        "JOIN exams e ON e.id = o.exam_id "
        "JOIN domains d ON d.id = o.domain_id "
        "WHERE r.due_at <= ?" + exam_clause +
        " ORDER BY r.due_at, e.code, CAST(d.code AS REAL), o.code LIMIT ?",
        (*params, limit),
    ).fetchall()
    items = [_state(row, current) for row in rows]
    return {
        "generated_at": now_iso(),
        "horizon_days": horizon_days,
        "due_count": sum(item["due"] for item in items),
        "upcoming_count": sum(not item["due"] for item in items),
        "next_due_at": items[0]["due_at"] if items else None,
        "items": items,
        "evidence_note": (
            "Retention reviews are active-recall learning records. "
            "Assessment mastery remains separate."
        ),
    }
