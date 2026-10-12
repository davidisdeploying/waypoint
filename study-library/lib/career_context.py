"""Read-only bridge from Career's canonical claims into Waypoint.

Waypoint stores claim IDs and relevance policy only.  Career remains authoritative
for the claim text, evidence class, safe wording, and prohibited inferences.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


CONTEXT_PATH = (
    Path(__file__).resolve().parent.parent
    / "sources"
    / "career"
    / "career-context-v1.json"
)


class CareerContextError(ValueError):
    pass


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_context(path=None):
    context_path = Path(path or CONTEXT_PATH)
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CareerContextError(f"career context is unreadable: {exc}") from exc
    if payload.get("schema_version") != 1:
        raise CareerContextError("career context schema_version must be 1")
    source = payload.get("canonical_source") or {}
    if not source.get("path") or len(source.get("sha256", "")) != 64:
        raise CareerContextError("career context canonical source is incomplete")
    policy = payload.get("policy") or {}
    claim_groups = (
        policy.get("target_claim_ids", []),
        policy.get("exclusion_claim_ids", []),
        policy.get("boundary_claim_ids", []),
    )
    if not policy.get("rule") or any(
        not isinstance(group, list) or len(group) != len(set(group))
        for group in claim_groups
    ):
        raise CareerContextError("career context policy is invalid")
    certifications = payload.get("certifications")
    if not isinstance(certifications, dict) or not certifications:
        raise CareerContextError("career context must map certifications")
    for cert_id, entry in certifications.items():
        claim_ids = entry.get("claim_ids")
        if (
            entry.get("relevance") not in {"direct", "supporting"}
            or not isinstance(claim_ids, list)
            or len(claim_ids) != len(set(claim_ids))
            or not entry.get("job_families")
        ):
            raise CareerContextError(f"career context entry is invalid for {cert_id}")
    return payload


def _source_status(payload):
    source = payload["canonical_source"]
    source_path = Path(
        os.environ.get("CAREER_CLAIMS_PATH", source["path"])
    )
    if not source_path.is_file():
        return {
            "status": "unavailable",
            "path": str(source_path),
            "expected_sha256": source["sha256"],
            "observed_sha256": None,
            "last_verified": source["last_verified"],
        }
    observed = _sha256(source_path)
    return {
        "status": "verified" if observed == source["sha256"] else "changed_review_required",
        "path": str(source_path),
        "expected_sha256": source["sha256"],
        "observed_sha256": observed,
        "last_verified": source["last_verified"],
    }


def get_context(certification_id=None, path=None):
    payload = load_context(path)
    certifications = payload["certifications"]
    selected = certifications.get(certification_id) if certification_id else None
    return {
        "schema_version": payload["schema_version"],
        "context_version": payload["context_version"],
        "canonical_source": _source_status(payload),
        "policy": payload["policy"],
        "certification_id": certification_id,
        "alignment": selected,
        "available_certifications": sorted(certifications),
    }
