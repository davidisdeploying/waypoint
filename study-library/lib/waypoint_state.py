"""Validated, optimistic-revision persistence for Waypoint milestones."""

import json
from datetime import date, datetime, timezone

from lib.api_logic import ApiError

MAX_STATE_BYTES = 500_000


def _text(value, name, maximum=2048, allow_empty=True):
    if not isinstance(value, str):
        raise ApiError(400, f"{name} must be a string")
    if not allow_empty and not value:
        raise ApiError(400, f"{name} must not be empty")
    if len(value) > maximum:
        raise ApiError(400, f"{name} is too long")


def _iso_date(value, name, allow_empty=True):
    _text(value, name, 10, allow_empty)
    if not value:
        return
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(400, f"{name} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ApiError(400, f"{name} must be an ISO date")


def validate(state):
    if not isinstance(state, dict):
        raise ApiError(400, "state must be an object")
    for key in ("meta", "certs", "courses", "log"):
        if key not in state:
            raise ApiError(400, f"missing state field: {key}")

    meta = state["meta"]
    if not isinstance(meta, dict):
        raise ApiError(400, "meta must be an object")
    _text(meta.get("name", ""), "meta.name", 200)
    _iso_date(meta.get("startDate", ""), "meta.startDate")
    _iso_date(meta.get("wguStartDate", ""), "meta.wguStartDate")

    certs = state["certs"]
    if not isinstance(certs, list) or not 1 <= len(certs) <= 30:
        raise ApiError(400, "certs must contain 1 to 30 items")
    ids = set()
    for index, cert in enumerate(certs):
        if not isinstance(cert, dict):
            raise ApiError(400, f"certs[{index}] must be an object")
        cert_id = cert.get("id")
        _text(cert_id, f"certs[{index}].id", 80, False)
        if cert_id in ids:
            raise ApiError(400, "cert ids must be unique")
        ids.add(cert_id)
        if cert.get("status") not in ("todo", "studying", "scheduled", "passed"):
            raise ApiError(400, f"certs[{index}].status is invalid")
        for field in ("name", "kind", "code", "exam", "pass", "started"):
            _text(cert.get(field, ""), f"certs[{index}].{field}", 300)
        for field in ("order", "price", "cu", "wlo", "whi", "estHoursLow", "estHoursHigh"):
            value = cert.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ApiError(400, f"certs[{index}].{field} must be numeric")
        actual_hours = cert.get("actualHours")
        if actual_hours is not None and (
            not isinstance(actual_hours, (int, float)) or isinstance(actual_hours, bool)
        ):
            raise ApiError(400, f"certs[{index}].actualHours must be numeric or null")

    courses = state["courses"]
    if not isinstance(courses, list) or len(courses) > 100:
        raise ApiError(400, "courses must contain at most 100 items")
    codes = set()
    for index, course in enumerate(courses):
        if not isinstance(course, dict):
            raise ApiError(400, f"courses[{index}] must be an object")
        code = course.get("code")
        _text(code, f"courses[{index}].code", 40, False)
        if code in codes:
            raise ApiError(400, "course codes must be unique")
        codes.add(code)
        if course.get("status") not in ("todo", "in_progress", "done"):
            raise ApiError(400, f"courses[{index}].status is invalid")
        _text(course.get("name", ""), f"courses[{index}].name", 300)
        _text(course.get("note", ""), f"courses[{index}].note", 1000)
        if not isinstance(course.get("cu"), (int, float)) or isinstance(course.get("cu"), bool):
            raise ApiError(400, f"courses[{index}].cu must be numeric")

    log = state["log"]
    if not isinstance(log, list) or len(log) > 5000:
        raise ApiError(400, "log must contain at most 5000 items")
    for index, entry in enumerate(log):
        if not isinstance(entry, dict):
            raise ApiError(400, f"log[{index}] must be an object")
        for field, maximum in (("id", 100), ("date", 20), ("certId", 80), ("note", 2000)):
            _text(entry.get(field, ""), f"log[{index}].{field}", maximum)
        hours = entry.get("hours")
        if not isinstance(hours, (int, float)) or isinstance(hours, bool) or not 0 < hours <= 24:
            raise ApiError(400, f"log[{index}].hours is invalid")

    _text(state.get("studyEndpoint", ""), "studyEndpoint", 2048)
    if state.get("studySummary") is not None and not isinstance(state["studySummary"], dict):
        raise ApiError(400, "studySummary must be an object or null")
    if state.get("studySummaryReceivedAt") is not None:
        _text(state["studySummaryReceivedAt"], "studySummaryReceivedAt", 80)

    encoded = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
        raise ApiError(400, "state is too large")
    return encoded


def get(conn):
    row = conn.execute(
        "SELECT revision, state_json, updated_at, migration_id "
        "FROM waypoint_state WHERE singleton_id = 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "schema_version": 1,
        "revision": row["revision"],
        "state": json.loads(row["state_json"]),
        "updated_at": row["updated_at"],
        "migration_id": row["migration_id"],
    }


def save(conn, state, expected_revision, migration_id=None):
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise ApiError(400, "expected_revision must be an integer")
    if expected_revision < 0:
        raise ApiError(400, "expected_revision must be non-negative")
    if migration_id is not None:
        _text(migration_id, "migration_id", 120)
    state_json = validate(state)
    updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn.execute("BEGIN IMMEDIATE")
    current = conn.execute(
        "SELECT revision FROM waypoint_state WHERE singleton_id = 1"
    ).fetchone()
    current_revision = current["revision"] if current else 0
    if current_revision != expected_revision:
        conn.rollback()
        raise ApiError(409, f"expected revision {expected_revision}, found {current_revision}")
    revision = current_revision + 1
    conn.execute(
        "INSERT INTO waypoint_state(singleton_id, revision, state_json, updated_at, migration_id) "
        "VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(singleton_id) DO UPDATE SET revision=excluded.revision, "
        "state_json=excluded.state_json, updated_at=excluded.updated_at, "
        "migration_id=COALESCE(excluded.migration_id, waypoint_state.migration_id)",
        (revision, state_json, updated_at, migration_id),
    )
    conn.commit()
    return get(conn)


def import_snapshot(conn, envelope, migration_id):
    if get(conn) is not None:
        raise ApiError(409, "Waypoint state is already initialized")
    revision = envelope.get("revision")
    updated_at = envelope.get("updated_at")
    if not isinstance(revision, int) or revision < 1 or not isinstance(updated_at, str):
        raise ApiError(400, "invalid source state envelope")
    state_json = validate(envelope.get("state"))
    _text(migration_id, "migration_id", 120, False)
    conn.execute(
        "INSERT INTO waypoint_state(singleton_id, revision, state_json, updated_at, migration_id) "
        "VALUES (1, ?, ?, ?, ?)",
        (revision, state_json, updated_at, migration_id),
    )
    conn.commit()
    return get(conn)
