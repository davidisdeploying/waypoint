"""Planning-only learning requests imported explicitly from Prospect."""
import json

from . import api_logic
from .api_logic import ApiError

ALLOWED_SCOPE = {"published_pack", "domain_scaffold", "missing", "unmapped"}
ALLOWED_PRIORITY = {"high", "medium", "low"}


def _text(value, name, required=False, maximum=2000):
    if value is None:
        if required:
            raise ApiError(400, f"{name} is required")
        return None
    value = str(value).strip()
    if required and not value:
        raise ApiError(400, f"{name} is required")
    if len(value) > maximum:
        raise ApiError(400, f"{name} is too long")
    return value or None


def create_many(conn, payload):
    if payload.get("schema_version") != 1:
        raise ApiError(400, "unsupported proposal schema_version")
    if payload.get("source") != "prospect_job_listing_audit":
        raise ApiError(400, "unsupported proposal source")
    try:
        audit_id = int(payload.get("source_audit_id"))
        listing_id = int(payload["source_listing_id"]) if payload.get("source_listing_id") is not None else None
    except (TypeError, ValueError):
        raise ApiError(400, "source audit/listing IDs must be integers")
    if audit_id < 1:
        raise ApiError(400, "source_audit_id must be positive")
    proposals = payload.get("proposals")
    if not isinstance(proposals, list) or not proposals or len(proposals) > 12:
        raise ApiError(400, "proposals must contain 1 to 12 items")
    career_hash = _text(payload.get("career_claims_hash"), "career_claims_hash", True, 64)
    if len(career_hash) != 64 or any(char not in "0123456789abcdef" for char in career_hash.lower()):
        raise ApiError(400, "career_claims_hash must be a SHA-256")
    created = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            raise ApiError(400, "each proposal must be an object")
        priority = _text(proposal.get("priority"), "priority", True, 20)
        scope = _text(proposal.get("waypoint_scope_status"), "waypoint_scope_status", True, 30)
        if priority not in ALLOWED_PRIORITY:
            raise ApiError(400, "invalid priority")
        if scope not in ALLOWED_SCOPE:
            raise ApiError(400, "invalid waypoint_scope_status")
        requirement_ids = proposal.get("source_requirement_ids")
        if not isinstance(requirement_ids, list) or not requirement_ids or not all(isinstance(item, str) for item in requirement_ids):
            raise ApiError(400, "source_requirement_ids must be a non-empty string array")
        values = (
            payload["source"], audit_id, listing_id,
            _text(payload.get("role"), "role", False, 300),
            _text(payload.get("company"), "company", False, 300),
            _text(proposal.get("skill"), "skill", True, 300),
            _text(proposal.get("technology"), "technology", True, 300),
            _text(proposal.get("evidence_building_method"), "evidence_building_method", True, 2000),
            priority,
            _text(proposal.get("certification_id"), "certification_id", False, 100),
            _text(proposal.get("certification_label"), "certification_label", False, 200),
            scope, career_hash.lower(), json.dumps(requirement_ids), api_logic.now_iso(),
        )
        conn.execute("""
            INSERT INTO learning_requests
              (source, source_audit_id, source_listing_id, role, company, skill, technology,
               rationale, priority, certification_id, certification_label, waypoint_scope_status,
               career_claims_hash, source_requirement_ids, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_audit_id, technology) DO NOTHING
        """, values)
    conn.commit()
    return list_requests(conn, audit_id=audit_id)


def _row(row):
    value = dict(row)
    value["source_requirement_ids"] = json.loads(value["source_requirement_ids"])
    return value


def list_requests(conn, audit_id=None):
    if audit_id is None:
        rows = conn.execute("SELECT * FROM learning_requests ORDER BY created_at DESC, id DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM learning_requests WHERE source_audit_id = ? ORDER BY id", (audit_id,)).fetchall()
    return {"learning_requests": [_row(row) for row in rows], "evidence_boundary": "planning_only_no_progress_or_mastery"}
