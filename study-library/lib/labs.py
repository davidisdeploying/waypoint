"""Objective-linked hands-on lab plans and learner evidence."""

import json

from lib.api_logic import ApiError, now_iso


STATUSES = {"planned", "in_progress", "completed"}
COMPLETION_LEVELS = {"guided", "referenced", "unaided"}
MAX_TITLE = 200
MAX_TEXT = 10000
MAX_CLIENT_KEY = 240


def _text(value, label, maximum=MAX_TEXT, *, required=False):
    if value is None:
        if required:
            raise ApiError(400, f"{label} is required")
        return None
    if not isinstance(value, str):
        raise ApiError(400, f"{label} must be a string")
    value = value.strip()
    if required and not value:
        raise ApiError(400, f"{label} is required")
    if len(value) > maximum:
        raise ApiError(400, f"{label} is too long")
    return value or None


def _lab(row):
    payload = dict(row)
    payload["archived"] = bool(payload["archived"])
    raw_snapshot = payload.pop("template_snapshot_json", None)
    payload["template"] = json.loads(raw_snapshot) if raw_snapshot else None
    return payload


def list_labs(conn, objective_id=None, *, include_archived=False):
    where = []
    params = []
    if objective_id is not None:
        where.append("l.objective_id = ?")
        params.append(objective_id)
    if not include_archived:
        where.append("l.archived = 0")
    rows = conn.execute(
        "SELECT l.*, x.template_slug, x.catalog_version, x.template_snapshot_json, "
        "o.code AS objective_code, o.description AS objective_description, "
        "e.code AS exam_code, d.name AS domain_name "
        "FROM hands_on_labs l "
        "LEFT JOIN lab_template_launches x ON x.lab_id = l.id "
        "JOIN objectives o ON o.id = l.objective_id "
        "JOIN exams e ON e.id = o.exam_id "
        "JOIN domains d ON d.id = o.domain_id "
        + (f"WHERE {' AND '.join(where)} " if where else "")
        + "ORDER BY CASE l.status WHEN 'in_progress' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END, "
        "l.updated_at DESC, l.id DESC",
        params,
    ).fetchall()
    labs = [_lab(row) for row in rows]
    return {
        "labs": labs,
        "summary": {
            "total": len(labs),
            "planned": sum(item["status"] == "planned" for item in labs),
            "in_progress": sum(item["status"] == "in_progress" for item in labs),
            "completed": sum(item["status"] == "completed" for item in labs),
            "unaided": sum(
                item["status"] == "completed"
                and item["completion_level"] == "unaided"
                for item in labs
            ),
        },
        "evidence_note": (
            "Lab records are learner-supplied hands-on evidence. They do not "
            "create assessment mastery or exam-readiness claims."
        ),
    }


def create_lab(
    conn,
    objective_id,
    title,
    goal_text,
    *,
    environment_text=None,
    client_key=None,
):
    if not isinstance(objective_id, int):
        raise ApiError(400, "objective_id is required")
    if conn.execute(
        "SELECT id FROM objectives WHERE id = ?", (objective_id,)
    ).fetchone() is None:
        raise ApiError(404, "objective not found")
    title = _text(title, "title", MAX_TITLE, required=True)
    goal_text = _text(goal_text, "goal_text", required=True)
    environment_text = _text(environment_text, "environment_text")
    client_key = _text(client_key, "client_key", MAX_CLIENT_KEY)
    timestamp = now_iso()
    try:
        cursor = conn.execute(
            "INSERT INTO hands_on_labs("
            "objective_id, title, goal_text, environment_text, status, "
            "client_key, archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, 'planned', ?, 0, ?, ?)",
            (
                objective_id,
                title,
                goal_text,
                environment_text,
                client_key,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
    except Exception as exc:
        if client_key and "UNIQUE constraint failed" in str(exc):
            existing = conn.execute(
                "SELECT id FROM hands_on_labs WHERE client_key = ?", (client_key,)
            ).fetchone()
            if existing:
                return next(
                    item for item in list_labs(
                        conn, objective_id, include_archived=True
                    )["labs"] if item["id"] == existing["id"]
                )
        raise
    return next(
        item for item in list_labs(conn, objective_id)["labs"]
        if item["id"] == cursor.lastrowid
    )


def update_lab(
    conn,
    lab_id,
    *,
    title=None,
    goal_text=None,
    environment_text=None,
    evidence_text=None,
    reflection_text=None,
    status=None,
    completion_level=None,
    archived=None,
):
    row = conn.execute(
        "SELECT * FROM hands_on_labs WHERE id = ?", (lab_id,)
    ).fetchone()
    if row is None:
        return None
    values = dict(row)
    changes = {}
    for key, value, label, maximum in (
        ("title", title, "title", MAX_TITLE),
        ("goal_text", goal_text, "goal_text", MAX_TEXT),
        ("environment_text", environment_text, "environment_text", MAX_TEXT),
        ("evidence_text", evidence_text, "evidence_text", MAX_TEXT),
        ("reflection_text", reflection_text, "reflection_text", MAX_TEXT),
    ):
        if value is not None:
            changes[key] = _text(
                value, label, maximum, required=key in {"title", "goal_text"}
            )
    if status is not None:
        if status not in STATUSES:
            raise ApiError(400, "invalid lab status")
        changes["status"] = status
    if completion_level is not None:
        if completion_level not in COMPLETION_LEVELS:
            raise ApiError(400, "invalid completion_level")
        changes["completion_level"] = completion_level
    if archived is not None:
        if not isinstance(archived, bool):
            raise ApiError(400, "archived must be a boolean")
        changes["archived"] = 1 if archived else 0
    candidate = {**values, **changes}
    timestamp = now_iso()
    if candidate["status"] == "completed":
        if not candidate.get("evidence_text") or not candidate.get("reflection_text"):
            raise ApiError(
                400, "completed labs require evidence_text and reflection_text"
            )
        if candidate.get("completion_level") not in COMPLETION_LEVELS:
            raise ApiError(400, "completed labs require completion_level")
        if not candidate.get("started_at"):
            changes["started_at"] = timestamp
        if not candidate.get("completed_at"):
            changes["completed_at"] = timestamp
    elif candidate["status"] == "in_progress" and not candidate.get("started_at"):
        changes["started_at"] = timestamp
    if not changes:
        raise ApiError(400, "no updatable lab fields provided")
    changes["updated_at"] = timestamp
    conn.execute(
        "UPDATE hands_on_labs SET "
        + ", ".join(f"{key} = ?" for key in changes)
        + " WHERE id = ?",
        (*changes.values(), lab_id),
    )
    conn.commit()
    return next(
        item for item in list_labs(
            conn, row["objective_id"], include_archived=True
        )["labs"] if item["id"] == lab_id
    )
