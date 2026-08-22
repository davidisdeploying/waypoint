"""Durable state machine for book conversion and indexing jobs."""

import json
import uuid
from datetime import datetime, timezone

from lib.api_logic import ApiError


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _row(row):
    if row is None:
        return None
    result = dict(row)
    result["result"] = json.loads(result.pop("result_json")) if result["result_json"] else None
    return result


def enqueue(conn, *, idempotency_key, kind, source_path, output_path, book_slug, book_kind):
    values = (idempotency_key, source_path, output_path, book_slug)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ApiError(400, "job identifiers and paths must be non-empty strings")
    if len(idempotency_key) > 160 or len(source_path) > 2000 or len(output_path) > 2000:
        raise ApiError(400, "job field is too long")
    if kind not in ("convert_index", "reindex"):
        raise ApiError(400, "invalid job kind")
    if book_kind not in ("guide", "review", "practice", "supplemental"):
        raise ApiError(400, "invalid book kind")
    if not book_slug.replace("-", "").isalnum() or len(book_slug) > 100:
        raise ApiError(400, "book_slug must contain letters, numbers, and hyphens")

    existing = conn.execute(
        "SELECT * FROM library_jobs WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    if existing:
        return _row(existing)
    job_id = str(uuid.uuid4())
    ts = now_iso()
    conn.execute(
        "INSERT INTO library_jobs(id,idempotency_key,kind,status,source_path,output_path,"
        "book_slug,book_kind,phase,message,created_at,updated_at) "
        "VALUES (?,?,?,'queued',?,?,?,?,'queued','Waiting for the book worker.',?,?)",
        (job_id, idempotency_key, kind, source_path, output_path, book_slug, book_kind, ts, ts),
    )
    conn.commit()
    return get(conn, job_id)


def get(conn, job_id):
    return _row(conn.execute("SELECT * FROM library_jobs WHERE id = ?", (job_id,)).fetchone())


def list_recent(conn, limit=20):
    limit = max(1, min(int(limit), 100))
    return [
        _row(row) for row in conn.execute(
            "SELECT * FROM library_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    ]


def claim_next(conn):
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT id FROM library_jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
    ).fetchone()
    if not row:
        conn.commit()
        return None
    ts = now_iso()
    conn.execute(
        "UPDATE library_jobs SET status='converting',phase='converting',"
        "message='Converting EPUB to verified Markdown.',started_at=?,updated_at=? WHERE id=?",
        (ts, ts, row["id"]),
    )
    conn.commit()
    return get(conn, row["id"])


def transition(conn, job_id, status, phase, message, *, result=None, error=None):
    if status not in ("converting", "indexing", "succeeded", "failed"):
        raise ValueError("invalid job transition")
    ts = now_iso()
    finished = ts if status in ("succeeded", "failed") else None
    conn.execute(
        "UPDATE library_jobs SET status=?,phase=?,message=?,error=?,result_json=?,"
        "finished_at=COALESCE(?,finished_at),updated_at=? WHERE id=?",
        (
            status, phase, message[:1000], error[:4000] if error else None,
            json.dumps(result, separators=(",", ":")) if result is not None else None,
            finished, ts, job_id,
        ),
    )
    conn.commit()
    return get(conn, job_id)
