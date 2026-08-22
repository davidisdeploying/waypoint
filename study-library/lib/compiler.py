"""Deterministic certification-pack compiler.

The compiler never asks an AI model to decide truth.  A versioned manifest
declares the official exam spine and pinned source hashes.  The build then
admits, quarantines, or excludes each local source and produces a coverage
report that runtime retrieval can enforce.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ingest.adapters import ADAPTER_CONTRACT_VERSION, parser_adapter_names
from lib import certification_spines, dossiers

COMPILER_VERSION = "5"
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parent.parent
    / "sources"
    / "certifications"
    / "aplus-v15.json"
)


class CompilerError(ValueError):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_manifest(path=None):
    manifest_path = Path(path or DEFAULT_MANIFEST)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "certification_code", "certification_name", "pack_version",
        "exam_version", "policy_version", "exams", "sources",
    }
    missing = required - set(payload)
    if missing:
        raise CompilerError(f"manifest missing fields: {sorted(missing)}")
    exam_codes = [exam["code"] for exam in payload["exams"]]
    if len(exam_codes) != len(set(exam_codes)):
        raise CompilerError("manifest contains duplicate exam codes")
    for exam in payload["exams"]:
        codes = exam.get("objective_codes") or []
        if not codes or len(codes) != len(set(codes)):
            raise CompilerError(
                f"{exam['code']} must contain unique objective codes"
            )
        if sum(d["weight"] for d in exam.get("domains", [])) != 100:
            raise CompilerError(f"{exam['code']} domain weights must total 100")
        objectives_file = exam.get("objectives_file")
        if objectives_file:
            objectives_path = (manifest_path.parent / objectives_file).resolve()
            if manifest_path.parent.resolve() not in objectives_path.parents:
                raise CompilerError(
                    f"{exam['code']} objectives_file escapes the manifest directory"
                )
            try:
                exam["objectives"] = json.loads(
                    objectives_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise CompilerError(
                    f"{exam['code']} official objectives file is unreadable: {exc}"
                ) from exc
            observed_objectives_sha256 = _canonical_hash(exam["objectives"])
            if observed_objectives_sha256 != exam.get("objectives_sha256"):
                raise CompilerError(
                    f"{exam['code']} official objectives JSON hash mismatch"
                )
        official_objectives = exam.get("objectives")
        if official_objectives is not None:
            official_codes = [item.get("code") for item in official_objectives]
            if (
                official_codes != codes
                or any(not item.get("description", "").strip() for item in official_objectives)
            ):
                raise CompilerError(
                    f"{exam['code']} official objective descriptions must exactly "
                    "match objective_codes in order"
                )
    source_keys = [source["source_key"] for source in payload["sources"]]
    if len(source_keys) != len(set(source_keys)):
        raise CompilerError("manifest contains duplicate source keys")
    official_hosts = set(payload.get("official_hosts", []))
    for source in payload["sources"]:
        ingest = source.get("ingest")
        if bool(source.get("book_slug")) != bool(ingest):
            raise CompilerError(
                f"{source['source_key']} must declare both book_slug and ingest, or neither"
            )
        if ingest and (
            not ingest.get("dir")
            or ingest.get("kind") not in {"guide", "review", "practice"}
        ):
            raise CompilerError(
                f"{source['source_key']} has an invalid ingest declaration"
            )
        if ingest and ingest.get("parser") not in parser_adapter_names():
            raise CompilerError(
                f"{source['source_key']} declares unknown parser adapter "
                f"'{ingest.get('parser')}'"
            )
        if source["source_type"] in {"official_objectives", "official_vendor"}:
            if not official_hosts:
                raise CompilerError("official sources require official_hosts")
    try:
        certification_spines.validate_pack_manifest(payload)
    except certification_spines.SpineError as exc:
        raise CompilerError(str(exc)) from exc
    return payload


def _canonical_hash(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _upsert_source(conn, cert_id, source, active_exam_codes, timestamp):
    book = None
    status = "active"
    reason = "Pinned official source metadata and SHA-256 are present."
    if source.get("book_slug"):
        book = conn.execute(
            "SELECT id, source_epub_sha256 FROM books WHERE slug = ?",
            (source["book_slug"],),
        ).fetchone()
        if not book:
            status = "unavailable"
            reason = f"Book '{source['book_slug']}' has not been ingested."
        elif book["source_epub_sha256"] != source["source_sha256"]:
            status = "quarantined"
            reason = (
                "Ingested EPUB hash does not match the certification manifest."
            )
        elif set(source["exam_codes"]) - active_exam_codes:
            status = "quarantined"
            reason = "Source names an exam outside this certification pack."
        else:
            reason = "Book hash and declared exam versions match this pack."
    elif (
        not source.get("source_url")
        or len(source.get("source_sha256", "")) != 64
        or not source.get("verified_at")
    ):
        status = "unavailable"
        reason = "Official source lacks a URL, pinned SHA-256, or verification date."

    conn.execute(
        "INSERT INTO source_registry("
        "certification_id, book_id, source_key, title, publisher, source_type, "
        "authority_tier, version_label, exam_codes_json, source_url, source_sha256, "
        "status, status_reason, metadata_json, verified_at, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(source_key) DO UPDATE SET "
        "certification_id=excluded.certification_id, book_id=excluded.book_id, "
        "title=excluded.title, publisher=excluded.publisher, "
        "source_type=excluded.source_type, authority_tier=excluded.authority_tier, "
        "version_label=excluded.version_label, exam_codes_json=excluded.exam_codes_json, "
        "source_url=excluded.source_url, source_sha256=excluded.source_sha256, "
        "status=excluded.status, status_reason=excluded.status_reason, "
        "metadata_json=excluded.metadata_json, "
        "verified_at=CASE "
        "WHEN excluded.verified_at IS NULL "
        "OR source_registry.verified_at > excluded.verified_at "
        "THEN source_registry.verified_at ELSE excluded.verified_at END, "
        "updated_at=excluded.updated_at",
        (
            cert_id,
            book["id"] if book else None,
            source["source_key"],
            source["title"],
            source["publisher"],
            source["source_type"],
            source["authority_tier"],
            source["version_label"],
            json.dumps(source["exam_codes"], separators=(",", ":")),
            source.get("source_url"),
            source["source_sha256"],
            status,
            reason,
            json.dumps(
                {
                    "book_slug": source.get("book_slug"),
                    "ingest": source.get("ingest"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            source.get("verified_at"),
            timestamp,
            timestamp,
        ),
    )
    row = conn.execute(
        "SELECT * FROM source_registry WHERE source_key = ?",
        (source["source_key"],),
    ).fetchone()
    return dict(row), source["use_role"], bool(source.get("required"))


def compile_pack(conn, manifest_path=None, commit=True):
    manifest = load_manifest(manifest_path)
    timestamp = now_iso()
    cert = conn.execute(
        "SELECT id, name FROM certifications WHERE code = ?",
        (manifest["certification_code"],),
    ).fetchone()
    if not cert:
        raise CompilerError(
            f"certification '{manifest['certification_code']}' is not ingested"
        )
    cert_id = cert["id"]
    active_exam_codes = {exam["code"] for exam in manifest["exams"]}
    db_exams = {
        row["code"]: dict(row)
        for row in conn.execute(
            "SELECT id, code, name FROM exams WHERE certification_id = ?",
            (cert_id,),
        )
    }

    source_rows = []
    for source in manifest["sources"]:
        source_rows.append(
            (*_upsert_source(conn, cert_id, source, active_exam_codes, timestamp), source)
        )

    source_set_sha256 = _canonical_hash([
        {
            "key": row["source_key"],
            "sha256": row["source_sha256"],
            "status": row["status"],
            "role": role,
            "parser": (
                source.get("ingest", {}).get("parser")
                if source.get("book_slug") else None
            ),
            "parser_contract": (
                ADAPTER_CONTRACT_VERSION if source.get("book_slug") else None
            ),
        }
        for row, role, _required, source in source_rows
    ] + [
        {
            "exam": exam["code"],
            "official_objectives_sha256": exam.get("objectives_sha256"),
        }
        for exam in manifest["exams"]
    ])
    conn.execute(
        "INSERT INTO certification_packs("
        "certification_id, pack_version, exam_version, status, compiler_version, "
        "policy_version, source_set_sha256, report_json, compiled_at, created_at, updated_at"
        ") VALUES (?, ?, ?, 'blocked', ?, ?, ?, '{}', ?, ?, ?) "
        "ON CONFLICT(certification_id, pack_version) DO UPDATE SET "
        "exam_version=excluded.exam_version, status='blocked', "
        "compiler_version=excluded.compiler_version, policy_version=excluded.policy_version, "
        "source_set_sha256=excluded.source_set_sha256, report_json='{}', "
        "compiled_at=excluded.compiled_at, updated_at=excluded.updated_at",
        (
            cert_id, manifest["pack_version"], manifest["exam_version"],
            COMPILER_VERSION, manifest["policy_version"], source_set_sha256,
            timestamp, timestamp, timestamp,
        ),
    )
    pack_id = conn.execute(
        "SELECT id FROM certification_packs "
        "WHERE certification_id = ? AND pack_version = ?",
        (cert_id, manifest["pack_version"]),
    ).fetchone()["id"]
    conn.execute("DELETE FROM compiler_findings WHERE pack_id = ?", (pack_id,))
    conn.execute(
        "DELETE FROM certification_pack_objectives WHERE pack_id = ?", (pack_id,)
    )
    conn.execute(
        "DELETE FROM certification_pack_sources WHERE pack_id = ?", (pack_id,)
    )

    findings = []

    def finding(key, category, severity, message, exam=None, objective=None, details=None):
        findings.append({
            "key": key, "category": category, "severity": severity,
            "message": message, "exam": exam, "objective": objective,
            "details": details or {},
        })

    for row, role, required, _source in source_rows:
        disposition = "active" if row["status"] == "active" else "quarantined"
        conn.execute(
            "INSERT INTO certification_pack_sources("
            "pack_id, source_id, disposition, use_role, required, reason"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (pack_id, row["id"], disposition, role, int(required), row["status_reason"]),
        )
        if required and disposition != "active":
            finding(
                f"required-source:{row['source_key']}", "integrity", "blocking",
                f"Required source is {row['status']}: {row['title']}",
                details={"reason": row["status_reason"]},
            )

    official_by_exam = {}
    for row, role, _required, source in source_rows:
        if role == "authoritative_scope" and row["status"] == "active":
            for exam_code in source["exam_codes"]:
                official_by_exam[exam_code] = row

    covered_count = 0
    objective_count = 0
    for exam_manifest in manifest["exams"]:
        exam_code = exam_manifest["code"]
        exam = db_exams.get(exam_code)
        if not exam:
            finding(
                f"missing-exam:{exam_code}", "version", "blocking",
                f"Active exam {exam_code} is missing from the ingested database.",
                exam=exam_code,
            )
            continue
        official = official_by_exam.get(exam_code)
        if not official:
            finding(
                f"missing-official:{exam_code}", "integrity", "blocking",
                f"No verified official objectives source is active for {exam_code}.",
                exam=exam_code,
            )
            continue

        for domain in exam_manifest["domains"]:
            conn.execute(
                "UPDATE domains SET name = ?, provenance = ?, confidence = 1.0, "
                "updated_at = ? WHERE exam_id = ? AND code = ?",
                (
                    domain["name"],
                    f"{official['source_key']}: official CompTIA exam objectives",
                    timestamp,
                    exam["id"],
                    domain["code"],
                ),
            )

        expected_codes = set(exam_manifest["objective_codes"])
        actual = {
            row["code"]: dict(row)
            for row in conn.execute(
                "SELECT id, code FROM objectives WHERE exam_id = ?", (exam["id"],)
            )
        }
        official_descriptions = {
            item["code"]: item["description"].strip()
            for item in exam_manifest.get("objectives", [])
        }
        for code, description in official_descriptions.items():
            if code in actual:
                conn.execute(
                    "UPDATE objectives SET description = ?, provenance = ?, "
                    "confidence = 1.0, updated_at = ? WHERE id = ?",
                    (
                        description,
                        f"{official['source_key']}: canonical objective heading",
                        timestamp,
                        actual[code]["id"],
                    ),
                )
        for code in sorted(expected_codes - set(actual)):
            finding(
                f"missing-objective:{exam_code}:{code}", "coverage", "blocking",
                f"Official objective {exam_code} {code} is missing from the database.",
                exam=exam_code, objective=code,
            )
        for code in sorted(set(actual) - expected_codes):
            finding(
                f"unexpected-objective:{exam_code}:{code}", "version", "warning",
                f"Objective {exam_code} {code} is not in the pinned official spine.",
                exam=exam_code, objective=code,
            )

        for code in sorted(expected_codes & set(actual)):
            objective_count += 1
            objective = actual[code]
            counts = {
                "primary_instruction": 0,
                "supplemental_instruction": 0,
                "assessment_only": 0,
            }
            rows = conn.execute(
                "SELECT DISTINCT ps.use_role, sr.id "
                "FROM objective_chunk_links l "
                "JOIN source_registry sr ON sr.book_id = l.book_id "
                "JOIN certification_pack_sources ps "
                "  ON ps.source_id = sr.id AND ps.pack_id = ? "
                "WHERE l.objective_id = ? AND ps.disposition = 'active'",
                (pack_id, objective["id"]),
            ).fetchall()
            for linked in rows:
                if linked["use_role"] in counts:
                    counts[linked["use_role"]] += 1
            if counts["primary_instruction"]:
                coverage_status = "covered"
                covered_count += 1
            elif counts["supplemental_instruction"]:
                coverage_status = "supplemental_only"
                covered_count += 1
                finding(
                    f"supplemental-only:{exam_code}:{code}", "coverage", "warning",
                    f"{exam_code} {code} has supplemental material but no primary lesson.",
                    exam=exam_code, objective=code,
                )
            else:
                coverage_status = "missing"
                finding(
                    f"teaching-gap:{exam_code}:{code}", "coverage", "blocking",
                    f"{exam_code} {code} has no active instructional source.",
                    exam=exam_code, objective=code,
                )
            conn.execute(
                "INSERT INTO certification_pack_objectives("
                "pack_id, objective_id, official_source_id, coverage_status, "
                "primary_source_count, supplemental_source_count, assessment_source_count"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    pack_id, objective["id"], official["id"], coverage_status,
                    counts["primary_instruction"],
                    counts["supplemental_instruction"],
                    counts["assessment_only"],
                ),
            )

    for item in findings:
        conn.execute(
            "INSERT INTO compiler_findings("
            "pack_id, finding_key, category, severity, exam_code, objective_code, "
            "message, details_json, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pack_id, item["key"], item["category"], item["severity"],
                item["exam"], item["objective"], item["message"],
                json.dumps(item["details"], sort_keys=True), timestamp,
            ),
        )

    dossier_counts = dossiers.compile_dossiers(conn, pack_id, timestamp)
    blocking = sum(item["severity"] == "blocking" for item in findings)
    warning = sum(item["severity"] == "warning" for item in findings)
    active_sources = sum(row["status"] == "active" for row, *_ in source_rows)
    quarantined = sum(row["status"] != "active" for row, *_ in source_rows)
    official_count = sum(
        row["status"] == "active" and row["source_type"] == "official_objectives"
        for row, *_ in source_rows
    )
    status = "ready" if blocking == 0 else "blocked"
    report = {
        "certification_code": manifest["certification_code"],
        "pack_version": manifest["pack_version"],
        "exam_version": manifest["exam_version"],
        "status": status,
        "exam_codes": sorted(active_exam_codes),
        "official_sources": official_count,
        "active_sources": active_sources,
        "quarantined_sources": quarantined,
        "objectives": objective_count,
        "covered_objectives": covered_count,
        "coverage_percent": round(
            covered_count * 100 / objective_count, 1
        ) if objective_count else 0.0,
        "blocking_findings": blocking,
        "warnings": warning,
        "official_objective_text_count": sum(
            len(exam.get("objectives", [])) for exam in manifest["exams"]
        ),
        "dossiers": dossier_counts,
        "runtime_policy": {
            "open_web": "disabled",
            "assessment_sources_for_teaching": "excluded",
            "ai_authority": "none",
            "retrieval_requires_active_pack_source": True,
        },
    }
    conn.execute(
        "UPDATE certification_packs SET status=?, official_count=?, "
        "active_source_count=?, quarantined_count=?, objective_count=?, "
        "covered_count=?, conflict_count=?, report_json=?, updated_at=? WHERE id=?",
        (
            status, official_count, active_sources, quarantined, objective_count,
            covered_count,
            sum(item["category"] == "conflict" for item in findings),
            json.dumps(report, sort_keys=True, separators=(",", ":")),
            timestamp, pack_id,
        ),
    )
    if commit:
        conn.commit()
    return report


def _pack_snapshot(conn, certification_code):
    """Return a canonical, timestamp-free snapshot of the compiled pack."""
    pack = get_pack_report(conn, certification_code)
    if not pack:
        return None
    objectives = [
        dict(row) for row in conn.execute(
            "SELECT e.code AS exam_code, o.code, o.description, o.provenance, "
            "po.coverage_status, po.primary_source_count, "
            "po.supplemental_source_count, po.assessment_source_count, "
            "od.status AS dossier_status, od.quality_score "
            "FROM certification_pack_objectives po "
            "JOIN certification_packs p ON p.id = po.pack_id "
            "JOIN objectives o ON o.id = po.objective_id "
            "JOIN exams e ON e.id = o.exam_id "
            "LEFT JOIN objective_dossiers od "
            "  ON od.pack_id = po.pack_id AND od.objective_id = po.objective_id "
            "WHERE p.id = ? ORDER BY e.sequence_order, o.code",
            (pack["id"],),
        )
    ]
    sources = [
        {
            "source_key": source["source_key"],
            "source_sha256": source["source_sha256"],
            "status": source["status"],
            "disposition": source["disposition"],
            "use_role": source["use_role"],
            "required": source["required"],
            "exam_codes": source["exam_codes"],
        }
        for source in pack["sources"]
    ]
    report = {
        key: value for key, value in pack["report"].items()
        if key not in {"compiled_at", "published_at"}
    }
    return {
        "certification_code": certification_code,
        "pack_version": pack["pack_version"],
        "exam_version": pack["exam_version"],
        "compiler_version": pack["compiler_version"],
        "policy_version": pack["policy_version"],
        "source_set_sha256": pack["source_set_sha256"],
        "status": pack["status"],
        "report": report,
        "sources": sources,
        "objectives": objectives,
    }


def _snapshot_diff(previous, candidate):
    if previous is None:
        changes = [
            {"kind": "source_added", "key": item["source_key"]}
            for item in candidate["sources"]
        ] + [
            {
                "kind": "objective_added",
                "key": f"{item['exam_code']} {item['code']}",
            }
            for item in candidate["objectives"]
        ]
        return {
            "baseline": "none",
            "changed": True,
            "summary": {
                "sources_added": len(candidate["sources"]),
                "sources_removed": 0,
                "sources_changed": 0,
                "objectives_added": len(candidate["objectives"]),
                "objectives_removed": 0,
                "objectives_changed": 0,
                "official_descriptions_changed": 0,
            },
            "changes": changes,
        }
    changes = []
    previous_sources = {item["source_key"]: item for item in previous["sources"]}
    candidate_sources = {item["source_key"]: item for item in candidate["sources"]}
    previous_objectives = {
        (item["exam_code"], item["code"]): item for item in previous["objectives"]
    }
    candidate_objectives = {
        (item["exam_code"], item["code"]): item for item in candidate["objectives"]
    }
    source_added = sorted(set(candidate_sources) - set(previous_sources))
    source_removed = sorted(set(previous_sources) - set(candidate_sources))
    source_changed = sorted(
        key for key in set(previous_sources) & set(candidate_sources)
        if previous_sources[key] != candidate_sources[key]
    )
    objective_added = sorted(set(candidate_objectives) - set(previous_objectives))
    objective_removed = sorted(set(previous_objectives) - set(candidate_objectives))
    objective_changed = sorted(
        key for key in set(previous_objectives) & set(candidate_objectives)
        if previous_objectives[key] != candidate_objectives[key]
    )
    official_description_changes = [
        key for key in objective_changed
        if previous_objectives[key]["description"]
        != candidate_objectives[key]["description"]
    ]
    scalar_fields = (
        "pack_version", "exam_version", "compiler_version",
        "policy_version", "source_set_sha256", "status",
    )
    for field in scalar_fields:
        if previous[field] != candidate[field]:
            changes.append({
                "kind": "pack",
                "key": field,
                "before": previous[field],
                "after": candidate[field],
            })
    for key in source_added:
        changes.append({"kind": "source_added", "key": key})
    for key in source_removed:
        changes.append({"kind": "source_removed", "key": key})
    for key in source_changed:
        changes.append({"kind": "source_changed", "key": key})
    for exam_code, code in objective_added:
        changes.append({"kind": "objective_added", "key": f"{exam_code} {code}"})
    for exam_code, code in objective_removed:
        changes.append({"kind": "objective_removed", "key": f"{exam_code} {code}"})
    for exam_code, code in official_description_changes:
        changes.append({
            "kind": "official_description_changed",
            "key": f"{exam_code} {code}",
            "before": previous_objectives[(exam_code, code)]["description"],
            "after": candidate_objectives[(exam_code, code)]["description"],
        })
    non_description_changed = set(objective_changed) - set(official_description_changes)
    for exam_code, code in sorted(non_description_changed):
        changes.append({"kind": "objective_changed", "key": f"{exam_code} {code}"})
    summary = {
        "sources_added": len(source_added),
        "sources_removed": len(source_removed),
        "sources_changed": len(source_changed),
        "objectives_added": len(objective_added),
        "objectives_removed": len(objective_removed),
        "objectives_changed": len(objective_changed),
        "official_descriptions_changed": len(official_description_changes),
    }
    return {
        "baseline": "published",
        "changed": bool(changes),
        "summary": summary,
        "changes": changes,
    }


def preview_pack(conn, manifest_path=None):
    """Compile inside a savepoint and persist only an immutable review build."""
    manifest = load_manifest(manifest_path)
    certification_code = manifest["certification_code"]
    baseline = _pack_snapshot(conn, certification_code)
    conn.execute("SAVEPOINT certification_pack_preview")
    try:
        report = compile_pack(conn, manifest_path, commit=False)
        candidate = _pack_snapshot(conn, certification_code)
        build_sha256 = _canonical_hash(candidate)
        diff = _snapshot_diff(baseline, candidate)
    finally:
        conn.execute("ROLLBACK TO certification_pack_preview")
        conn.execute("RELEASE certification_pack_preview")
    cert_id = conn.execute(
        "SELECT id FROM certifications WHERE code = ?", (certification_code,)
    ).fetchone()["id"]
    status = "preview" if report["status"] == "ready" else "blocked"
    timestamp = now_iso()
    conn.execute(
        "INSERT INTO certification_pack_builds("
        "certification_id, pack_version, exam_version, compiler_version, "
        "policy_version, source_set_sha256, build_sha256, status, report_json, "
        "snapshot_json, diff_json, compiled_at, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(certification_id, build_sha256) DO NOTHING",
        (
            cert_id, manifest["pack_version"], manifest["exam_version"],
            COMPILER_VERSION, manifest["policy_version"],
            candidate["source_set_sha256"], build_sha256, status,
            json.dumps(report, sort_keys=True, separators=(",", ":")),
            json.dumps(candidate, sort_keys=True, separators=(",", ":")),
            json.dumps(diff, sort_keys=True, separators=(",", ":")),
            timestamp, timestamp,
        ),
    )
    conn.commit()
    build = conn.execute(
        "SELECT * FROM certification_pack_builds "
        "WHERE certification_id = ? AND build_sha256 = ?",
        (cert_id, build_sha256),
    ).fetchone()
    return _build_payload(build)


def publish_pack(conn, build_id, manifest_path=None):
    """Promote a reviewed preview only when a fresh compile is byte-identical."""
    build = conn.execute(
        "SELECT b.*, c.code AS certification_code "
        "FROM certification_pack_builds b "
        "JOIN certifications c ON c.id = b.certification_id WHERE b.id = ?",
        (build_id,),
    ).fetchone()
    if not build:
        raise CompilerError(f"pack build {build_id} does not exist")
    if build["status"] != "preview":
        raise CompilerError(f"pack build {build_id} is not publishable")
    manifest = load_manifest(manifest_path)
    if manifest["certification_code"] != build["certification_code"]:
        raise CompilerError("pack build and manifest certification do not match")
    conn.execute("SAVEPOINT certification_pack_publish")
    try:
        compile_pack(conn, manifest_path, commit=False)
        candidate = _pack_snapshot(conn, build["certification_code"])
        observed = _canonical_hash(candidate)
        if observed != build["build_sha256"]:
            raise CompilerError(
                "pack inputs changed after preview; create and review a new preview"
            )
        timestamp = now_iso()
        conn.execute(
            "UPDATE certification_pack_builds SET status = 'superseded' "
            "WHERE certification_id = ? AND status = 'published'",
            (build["certification_id"],),
        )
        conn.execute(
            "UPDATE certification_pack_builds SET status = 'published', "
            "published_at = ? WHERE id = ?",
            (timestamp, build_id),
        )
        conn.execute(
            "INSERT INTO certification_pack_active_builds("
            "certification_id, build_id, promoted_at"
            ") VALUES (?, ?, ?) ON CONFLICT(certification_id) DO UPDATE SET "
            "build_id = excluded.build_id, promoted_at = excluded.promoted_at",
            (build["certification_id"], build_id, timestamp),
        )
        conn.execute("RELEASE certification_pack_publish")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO certification_pack_publish")
        conn.execute("RELEASE certification_pack_publish")
        conn.rollback()
        raise
    return get_pack_build_state(conn, build["certification_code"])


def _build_payload(row):
    if not row:
        return None
    payload = dict(row)
    payload["report"] = json.loads(payload.pop("report_json"))
    payload["diff"] = json.loads(payload.pop("diff_json"))
    payload.pop("snapshot_json")
    return payload


def get_pack_build_state(conn, certification_code="aplus"):
    certification = conn.execute(
        "SELECT id, code, name FROM certifications WHERE code = ?",
        (certification_code,),
    ).fetchone()
    if not certification:
        return None
    active = conn.execute(
        "SELECT b.* FROM certification_pack_active_builds a "
        "JOIN certification_pack_builds b ON b.id = a.build_id "
        "WHERE a.certification_id = ?",
        (certification["id"],),
    ).fetchone()
    latest = conn.execute(
        "SELECT * FROM certification_pack_builds WHERE certification_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (certification["id"],),
    ).fetchone()
    return {
        "certification_code": certification["code"],
        "certification_name": certification["name"],
        "active": _build_payload(active),
        "latest": _build_payload(latest),
        "has_pending_preview": bool(latest and latest["status"] == "preview"),
    }


def get_pack_report(conn, certification_code="aplus"):
    pack = conn.execute(
        "SELECT p.*, c.code AS certification_code, c.name AS certification_name "
        "FROM certification_packs p "
        "JOIN certifications c ON c.id = p.certification_id "
        "WHERE c.code = ? "
        "ORDER BY CASE p.status WHEN 'ready' THEN 0 ELSE 1 END, p.compiled_at DESC "
        "LIMIT 1",
        (certification_code,),
    ).fetchone()
    if not pack:
        return None
    result = dict(pack)
    result["report"] = json.loads(result.pop("report_json"))
    sources = conn.execute(
        "SELECT sr.source_key, sr.title, sr.publisher, sr.source_type, "
        "sr.authority_tier, sr.version_label, sr.exam_codes_json, sr.source_url, "
        "sr.source_sha256, sr.status, sr.status_reason, sr.verified_at, "
        "verification.status AS refresh_status, "
        "verification.observed_sha256, verification.checked_at AS last_checked_at, "
        "verification.final_url AS last_checked_url, "
        "verification.error AS refresh_error, "
        "ps.disposition, ps.use_role, ps.required "
        "FROM certification_pack_sources ps "
        "JOIN source_registry sr ON sr.id = ps.source_id "
        "LEFT JOIN source_verification_runs verification ON verification.id = ("
        "  SELECT svr.id FROM source_verification_runs svr "
        "  WHERE svr.source_id = sr.id ORDER BY svr.checked_at DESC, svr.id DESC LIMIT 1"
        ") "
        "WHERE ps.pack_id = ? "
        "ORDER BY sr.authority_tier, sr.publisher, sr.title",
        (result["id"],),
    ).fetchall()
    result["sources"] = []
    for source in sources:
        item = dict(source)
        item["exam_codes"] = json.loads(item.pop("exam_codes_json"))
        item["required"] = bool(item["required"])
        result["sources"].append(item)
    result["findings"] = [
        dict(row) for row in conn.execute(
            "SELECT category, severity, exam_code, objective_code, message "
            "FROM compiler_findings WHERE pack_id = ? "
            "ORDER BY CASE severity WHEN 'blocking' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, id",
            (result["id"],),
        )
    ]
    result["coverage_by_exam"] = [
        dict(row) for row in conn.execute(
            "SELECT e.code AS exam_code, COUNT(*) AS objective_count, "
            "SUM(CASE WHEN po.coverage_status != 'missing' THEN 1 ELSE 0 END) AS covered_count, "
            "SUM(CASE WHEN po.coverage_status = 'missing' THEN 1 ELSE 0 END) AS missing_count, "
            "SUM(CASE WHEN po.coverage_status = 'supplemental_only' THEN 1 ELSE 0 END) AS supplemental_only_count "
            "FROM certification_pack_objectives po "
            "JOIN objectives o ON o.id = po.objective_id "
            "JOIN exams e ON e.id = o.exam_id "
            "WHERE po.pack_id = ? GROUP BY e.id ORDER BY e.sequence_order",
            (result["id"],),
        )
    ]
    return result
