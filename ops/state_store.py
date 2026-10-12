"""Validated, revisioned server-side persistence for Waypoint milestones."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


MAX_STATE_BYTES = 500_000


class StateValidationError(ValueError):
    """The submitted Waypoint state does not match the bounded contract."""


class StateConflictError(RuntimeError):
    """The submitted revision is stale."""


def _bounded_text(value, name, maximum=2048, allow_empty=True):
    if not isinstance(value, str):
        raise StateValidationError(f"{name} must be a string")
    if not allow_empty and not value:
        raise StateValidationError(f"{name} must not be empty")
    if len(value) > maximum:
        raise StateValidationError(f"{name} is too long")


def validate_state(state):
    if not isinstance(state, dict):
        raise StateValidationError("state must be an object")
    for key in ("meta", "certs", "courses", "log"):
        if key not in state:
            raise StateValidationError(f"missing state field: {key}")

    meta = state["meta"]
    if not isinstance(meta, dict):
        raise StateValidationError("meta must be an object")
    _bounded_text(meta.get("name", ""), "meta.name", maximum=200)
    _bounded_text(meta.get("startDate", ""), "meta.startDate", maximum=20)

    certs = state["certs"]
    if not isinstance(certs, list) or not 1 <= len(certs) <= 30:
        raise StateValidationError("certs must contain 1 to 30 items")
    cert_ids = set()
    for index, cert in enumerate(certs):
        if not isinstance(cert, dict):
            raise StateValidationError(f"certs[{index}] must be an object")
        cert_id = cert.get("id")
        _bounded_text(cert_id, f"certs[{index}].id", maximum=80, allow_empty=False)
        if cert_id in cert_ids:
            raise StateValidationError("cert ids must be unique")
        cert_ids.add(cert_id)
        if cert.get("status") not in ("todo", "studying", "scheduled", "passed"):
            raise StateValidationError(f"certs[{index}].status is invalid")
        for field in ("name", "kind", "code", "exam", "pass", "started"):
            _bounded_text(cert.get(field, ""), f"certs[{index}].{field}", maximum=300)
        for field in ("order", "price", "cu", "wlo", "whi", "estHoursLow", "estHoursHigh"):
            value = cert.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise StateValidationError(f"certs[{index}].{field} must be numeric")
        actual_hours = cert.get("actualHours")
        if actual_hours is not None and (
            not isinstance(actual_hours, (int, float)) or isinstance(actual_hours, bool)
        ):
            raise StateValidationError(f"certs[{index}].actualHours must be numeric or null")

    courses = state["courses"]
    if not isinstance(courses, list) or len(courses) > 100:
        raise StateValidationError("courses must contain at most 100 items")
    course_codes = set()
    for index, course in enumerate(courses):
        if not isinstance(course, dict):
            raise StateValidationError(f"courses[{index}] must be an object")
        code = course.get("code")
        _bounded_text(code, f"courses[{index}].code", maximum=40, allow_empty=False)
        if code in course_codes:
            raise StateValidationError("course codes must be unique")
        course_codes.add(code)
        if course.get("status") not in ("todo", "in_progress", "done"):
            raise StateValidationError(f"courses[{index}].status is invalid")
        _bounded_text(course.get("name", ""), f"courses[{index}].name", maximum=300)
        _bounded_text(course.get("note", ""), f"courses[{index}].note", maximum=1000)
        cu = course.get("cu")
        if not isinstance(cu, (int, float)) or isinstance(cu, bool):
            raise StateValidationError(f"courses[{index}].cu must be numeric")

    log = state["log"]
    if not isinstance(log, list) or len(log) > 5000:
        raise StateValidationError("log must contain at most 5000 items")
    for index, entry in enumerate(log):
        if not isinstance(entry, dict):
            raise StateValidationError(f"log[{index}] must be an object")
        for field, maximum in (
            ("id", 100),
            ("date", 20),
            ("certId", 80),
            ("note", 2000),
        ):
            _bounded_text(entry.get(field, ""), f"log[{index}].{field}", maximum=maximum)
        hours = entry.get("hours")
        if not isinstance(hours, (int, float)) or isinstance(hours, bool) or not 0 < hours <= 24:
            raise StateValidationError(f"log[{index}].hours is invalid")

    _bounded_text(state.get("studyEndpoint", ""), "studyEndpoint", maximum=2048)
    if state.get("studySummary") is not None and not isinstance(state.get("studySummary"), dict):
        raise StateValidationError("studySummary must be an object or null")
    received = state.get("studySummaryReceivedAt")
    if received is not None:
        _bounded_text(received, "studySummaryReceivedAt", maximum=80)

    encoded = json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise StateValidationError("state is too large")
    return encoded.decode("utf-8")


class WaypointStateStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS waypoint_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    migration_id TEXT
                )
                """
            )

    def get(self):
        with self._connection() as connection:
            row = connection.execute(
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

    def save(self, state, expected_revision, migration_id=None):
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            raise StateValidationError("expected_revision must be an integer")
        if expected_revision < 0:
            raise StateValidationError("expected_revision must be non-negative")
        if migration_id is not None:
            _bounded_text(migration_id, "migration_id", maximum=120)
        state_json = validate_state(state)
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision FROM waypoint_state WHERE singleton_id = 1"
            ).fetchone()
            current_revision = current["revision"] if current else 0
            if current_revision != expected_revision:
                raise StateConflictError(
                    f"expected revision {expected_revision}, found {current_revision}"
                )
            new_revision = current_revision + 1
            connection.execute(
                """
                INSERT INTO waypoint_state (
                    singleton_id, revision, state_json, updated_at, migration_id
                ) VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    revision = excluded.revision,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at,
                    migration_id = COALESCE(excluded.migration_id, waypoint_state.migration_id)
                """,
                (new_revision, state_json, updated_at, migration_id),
            )
        return self.get()
