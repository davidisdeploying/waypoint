"""Private learner annotations attached to governed objectives and sources."""

import re

from lib.api_logic import ApiError, now_iso


KINDS = {"highlight", "note", "bookmark"}
MAX_QUOTE_CHARS = 2000
MAX_CONTEXT_CHARS = 240
MAX_NOTE_CHARS = 5000
MAX_CLIENT_KEY_CHARS = 240


def _clean_optional(value, label, maximum):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, f"{label} must be a string")
    value = value.strip()
    if len(value) > maximum:
        raise ApiError(400, f"{label} is too long")
    return value or None


def _normalized_source(content):
    text = re.sub(r"(?m)^#{1,6}\s+", "", content or "")
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    return " ".join(text.split())


def _annotation(row):
    payload = dict(row)
    payload["archived"] = bool(payload["archived"])
    current_hash = payload.pop("current_content_sha256", None)
    current_content = payload.pop("current_content", None)
    if payload["section_stable_id"] is None:
        payload["anchor_status"] = "objective"
    elif current_hash == payload["content_sha256"]:
        payload["anchor_status"] = "exact"
    elif payload["quote_text"] and payload["quote_text"] in _normalized_source(current_content):
        payload["anchor_status"] = "relocated"
    else:
        payload["anchor_status"] = "unresolved"
    payload["current_content_sha256"] = current_hash
    return payload


def list_annotations(conn, objective_id=None, *, include_archived=False):
    where = []
    params = []
    if objective_id is not None:
        where.append("a.objective_id = ?")
        params.append(objective_id)
    if not include_archived:
        where.append("a.archived = 0")
    rows = conn.execute(
        "SELECT a.id, a.objective_id, a.section_stable_id, a.kind, "
        "a.quote_text, a.prefix_text, a.suffix_text, a.note_text, "
        "a.content_sha256, a.anchor_start, a.anchor_end, a.client_key, "
        "a.archived, a.created_at, a.updated_at, "
        "o.code AS objective_code, e.code AS exam_code, "
        "s.title AS section_title, s.content_sha256 AS current_content_sha256, "
        "s.content AS current_content, b.title AS book_title "
        "FROM study_annotations a "
        "JOIN objectives o ON o.id = a.objective_id "
        "JOIN exams e ON e.id = o.exam_id "
        "LEFT JOIN sections s ON s.stable_id = a.section_stable_id "
        "LEFT JOIN books b ON b.id = s.book_id "
        + (f"WHERE {' AND '.join(where)} " if where else "")
        + "ORDER BY a.created_at DESC, a.id DESC",
        params,
    ).fetchall()
    return [_annotation(row) for row in rows]


def _validated_section(conn, objective_id, stable_id, supplied_hash):
    row = conn.execute(
        "SELECT s.stable_id, s.content_sha256 FROM sections s "
        "JOIN objective_chunk_links l ON l.section_id = s.id "
        "WHERE l.objective_id = ? AND s.stable_id = ?",
        (objective_id, stable_id),
    ).fetchone()
    if row is None:
        raise ApiError(400, "section is not an approved source for this objective")
    if supplied_hash != row["content_sha256"]:
        raise ApiError(409, "source changed; reopen the lesson before annotating")
    return row


def create_annotation(
    conn,
    objective_id,
    kind,
    *,
    section_stable_id=None,
    quote_text=None,
    prefix_text=None,
    suffix_text=None,
    note_text=None,
    content_sha256=None,
    anchor_start=None,
    anchor_end=None,
    client_key=None,
):
    if not isinstance(objective_id, int):
        raise ApiError(400, "objective_id is required")
    if conn.execute(
        "SELECT id FROM objectives WHERE id = ?", (objective_id,)
    ).fetchone() is None:
        raise ApiError(404, "objective not found")
    if kind not in KINDS:
        raise ApiError(400, "kind must be highlight, note, or bookmark")
    quote_text = _clean_optional(quote_text, "quote_text", MAX_QUOTE_CHARS)
    prefix_text = _clean_optional(prefix_text, "prefix_text", MAX_CONTEXT_CHARS)
    suffix_text = _clean_optional(suffix_text, "suffix_text", MAX_CONTEXT_CHARS)
    note_text = _clean_optional(note_text, "note_text", MAX_NOTE_CHARS)
    client_key = _clean_optional(client_key, "client_key", MAX_CLIENT_KEY_CHARS)
    if kind == "highlight" and (not section_stable_id or not quote_text):
        raise ApiError(400, "a highlight requires a source section and selected text")
    if kind == "note" and not note_text:
        raise ApiError(400, "a note requires note_text")
    if kind in {"highlight", "bookmark"} and section_stable_id:
        if not isinstance(content_sha256, str) or not content_sha256:
            raise ApiError(400, "content_sha256 is required for source annotations")
        _validated_section(
            conn, objective_id, section_stable_id, content_sha256
        )
    if anchor_start is not None or anchor_end is not None:
        if (
            not isinstance(anchor_start, int)
            or not isinstance(anchor_end, int)
            or anchor_start < 0
            or anchor_end < anchor_start
        ):
            raise ApiError(400, "invalid annotation offsets")
    timestamp = now_iso()
    try:
        cursor = conn.execute(
            "INSERT INTO study_annotations("
            "objective_id, section_stable_id, kind, quote_text, prefix_text, "
            "suffix_text, note_text, content_sha256, anchor_start, anchor_end, "
            "client_key, archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (
                objective_id,
                section_stable_id,
                kind,
                quote_text,
                prefix_text,
                suffix_text,
                note_text,
                content_sha256,
                anchor_start,
                anchor_end,
                client_key,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
    except Exception as exc:
        if client_key and "UNIQUE constraint failed" in str(exc):
            existing = conn.execute(
                "SELECT id FROM study_annotations WHERE client_key = ?",
                (client_key,),
            ).fetchone()
            if existing:
                return next(
                    item for item in list_annotations(
                        conn, objective_id, include_archived=True
                    ) if item["id"] == existing["id"]
                )
        raise
    return next(
        item for item in list_annotations(conn, objective_id)
        if item["id"] == cursor.lastrowid
    )


def update_annotation(conn, annotation_id, *, note_text=None, archived=None):
    row = conn.execute(
        "SELECT id, objective_id FROM study_annotations WHERE id = ?",
        (annotation_id,),
    ).fetchone()
    if row is None:
        return None
    fields = []
    params = []
    if note_text is not None:
        note_text = _clean_optional(note_text, "note_text", MAX_NOTE_CHARS)
        fields.append("note_text = ?")
        params.append(note_text)
    if archived is not None:
        if not isinstance(archived, bool):
            raise ApiError(400, "archived must be a boolean")
        fields.append("archived = ?")
        params.append(1 if archived else 0)
    if not fields:
        raise ApiError(400, "no updatable annotation fields provided")
    fields.append("updated_at = ?")
    params.append(now_iso())
    params.append(annotation_id)
    conn.execute(
        f"UPDATE study_annotations SET {', '.join(fields)} WHERE id = ?",
        params,
    )
    conn.commit()
    return next(
        item for item in list_annotations(
            conn, row["objective_id"], include_archived=True
        ) if item["id"] == annotation_id
    )
