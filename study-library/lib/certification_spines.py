"""Canonical, vendor-governed certification spine registry.

The registry is the one source used by Journey projections and certification-pack
validation.  A spine defines scope only; books, career context, and learner evidence
may attach to it but cannot alter its exams, domains, or weights.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent
    / "sources"
    / "certifications"
    / "certification-spines-v1.json"
)
SCOPE_STATUSES = {"domain_scaffold", "published_pack"}
VERIFICATION_STATUSES = {
    "hash_verified",
    "official_page_verified_document_hash_pending",
}


class SpineError(ValueError):
    pass


def _canonical_hash(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_registry(path=None):
    registry_path = Path(path or REGISTRY_PATH)
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpineError(f"certification spine registry is unreadable: {exc}") from exc

    if payload.get("schema_version") != 1:
        raise SpineError("certification spine registry schema_version must be 1")
    certifications = payload.get("certifications")
    if not isinstance(certifications, list) or not certifications:
        raise SpineError("certification spine registry must contain certifications")

    seen_ids = set()
    seen_orders = set()
    seen_exam_codes = set()
    for certification in certifications:
        cert_id = certification.get("id")
        order = certification.get("sequence_order")
        if not cert_id or cert_id in seen_ids:
            raise SpineError(f"duplicate or missing certification id: {cert_id!r}")
        if not isinstance(order, int) or order < 1 or order in seen_orders:
            raise SpineError(f"invalid sequence_order for {cert_id}")
        if certification.get("scope_status") not in SCOPE_STATUSES:
            raise SpineError(f"invalid scope_status for {cert_id}")
        if not isinstance(certification.get("exam_sittings"), int):
            raise SpineError(f"exam_sittings must be an integer for {cert_id}")
        exams = certification.get("exams")
        if not isinstance(exams, list) or not exams:
            raise SpineError(f"{cert_id} must declare at least one exam")
        seen_ids.add(cert_id)
        seen_orders.add(order)

        for exam in exams:
            exam_code = exam.get("code")
            if not exam_code or exam_code in seen_exam_codes:
                raise SpineError(f"duplicate or missing exam code: {exam_code!r}")
            seen_exam_codes.add(exam_code)
            domains = exam.get("domains")
            if not isinstance(domains, list) or not domains:
                raise SpineError(f"{exam_code} must declare domains")
            domain_codes = [domain.get("code") for domain in domains]
            if len(domain_codes) != len(set(domain_codes)) or any(
                not code for code in domain_codes
            ):
                raise SpineError(f"{exam_code} has duplicate or missing domain codes")
            if sum(domain.get("weight", 0) for domain in domains) != 100:
                raise SpineError(f"{exam_code} domain weights must total 100")
            if any(
                not domain.get("name") or not isinstance(domain.get("weight"), int)
                for domain in domains
            ):
                raise SpineError(f"{exam_code} has an invalid domain")

            source = exam.get("official_source") or {}
            status = source.get("verification_status")
            if status not in VERIFICATION_STATUSES:
                raise SpineError(f"{exam_code} has an invalid source verification status")
            if not source.get("url") or not source.get("last_verified"):
                raise SpineError(f"{exam_code} official source metadata is incomplete")
            sha256 = source.get("sha256")
            if status == "hash_verified" and (
                not isinstance(sha256, str) or len(sha256) != 64
            ):
                raise SpineError(f"{exam_code} hash-verified source lacks SHA-256")
            if status != "hash_verified" and sha256 is not None:
                raise SpineError(f"{exam_code} pending source must not claim a SHA-256")

    ordered = sorted(certifications, key=lambda item: item["sequence_order"])
    payload["certifications"] = ordered
    payload["registry_sha256"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "registry_sha256"}
    )
    return payload


def list_spines(path=None):
    return load_registry(path)["certifications"]


def get_spine(certification_id, path=None):
    return next(
        (
            certification
            for certification in list_spines(path)
            if certification["id"] == certification_id
        ),
        None,
    )


def certification_for_exam(exam_code, path=None):
    for certification in list_spines(path):
        if any(exam["code"] == exam_code for exam in certification["exams"]):
            return certification
    return None


def projected_domains(certification_id, path=None):
    """Return flattened official domains for timeline-only projected weeks."""
    certification = get_spine(certification_id, path)
    if not certification:
        return None
    return [
        (domain["name"], domain["weight"])
        for exam in certification["exams"]
        for domain in exam["domains"]
    ]


def validate_pack_manifest(manifest, path=None):
    """Fail when a registry-bound knowledge pack disagrees with its spine.

    Pre-registry manifests remain readable during the migration.  New and migrated
    production manifests bind themselves with ``spine_registry_version``; once
    bound, every exam, domain, weight, and official source is fail-closed.
    """
    registry = load_registry(path)
    certification = get_spine(manifest.get("certification_code"), path)
    if not certification:
        raise SpineError(
            f"manifest certification {manifest.get('certification_code')!r} "
            "is absent from the certification spine registry"
        )
    bound_version = manifest.get("spine_registry_version")
    if bound_version is None:
        return certification
    if bound_version != registry["registry_version"]:
        raise SpineError(
            f"manifest spine_registry_version {bound_version!r} does not match "
            f"canonical registry {registry['registry_version']!r}"
        )
    registry_exams = {exam["code"]: exam for exam in certification["exams"]}
    manifest_exams = {exam.get("code"): exam for exam in manifest.get("exams", [])}
    if set(registry_exams) != set(manifest_exams):
        raise SpineError(
            f"manifest exam codes {sorted(manifest_exams)} do not match canonical "
            f"spine {sorted(registry_exams)}"
        )
    for exam_code, registry_exam in registry_exams.items():
        manifest_exam = manifest_exams[exam_code]
        expected_domains = [
            (domain["code"], domain["name"], domain["weight"])
            for domain in registry_exam["domains"]
        ]
        observed_domains = [
            (domain.get("code"), domain.get("name"), domain.get("weight"))
            for domain in manifest_exam.get("domains", [])
        ]
        if observed_domains != expected_domains:
            raise SpineError(f"{exam_code} manifest domains diverge from canonical spine")
        official_sources = [
            source
            for source in manifest.get("sources", [])
            if source.get("source_type") == "official_objectives"
            and exam_code in source.get("exam_codes", [])
        ]
        if len(official_sources) != 1:
            raise SpineError(f"{exam_code} must have exactly one official objectives source")
        registry_source = registry_exam["official_source"]
        manifest_source = official_sources[0]
        if (
            manifest_source.get("source_url") != registry_source.get("url")
            or manifest_source.get("source_sha256") != registry_source.get("sha256")
        ):
            raise SpineError(f"{exam_code} official source diverges from canonical spine")
    return certification


def registry_summary(path=None):
    registry = load_registry(path)
    return {
        "schema_version": registry["schema_version"],
        "registry_version": registry["registry_version"],
        "last_reviewed": registry["last_reviewed"],
        "registry_sha256": registry["registry_sha256"],
        "authority_policy": registry["authority_policy"],
        "certifications": registry["certifications"],
        "counts": {
            "certifications": len(registry["certifications"]),
            "exam_sittings": sum(
                item["exam_sittings"] for item in registry["certifications"]
            ),
            "published_packs": sum(
                item["scope_status"] == "published_pack"
                for item in registry["certifications"]
            ),
            "domain_scaffolds": sum(
                item["scope_status"] == "domain_scaffold"
                for item in registry["certifications"]
            ),
        },
    }
