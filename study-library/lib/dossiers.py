"""Deterministic, cited learning dossiers materialized from a compiled pack."""
import json
import re


DOSSIER_SCHEMA_VERSION = "1"
MAX_PRIMARY_EXCERPT_CHARS = 8000


def _focused_excerpt(content, objective_code):
    content = content or ""
    heading = re.search(
        rf"(?m)^##\s+{re.escape(objective_code)}\b.*$",
        content,
    )
    if not heading:
        return content.strip()[:MAX_PRIMARY_EXCERPT_CHARS]
    next_heading = re.search(
        r"(?m)^##\s+\d+\.\d+\b.*$",
        content[heading.end():],
    )
    end = (
        heading.end() + next_heading.start()
        if next_heading else len(content)
    )
    return content[heading.start():end].strip()[:MAX_PRIMARY_EXCERPT_CHARS]


def _instructional_citations(conn, pack_id, objective_id):
    rows = conn.execute(
        "SELECT s.id AS section_id, s.stable_id, s.title, s.position, "
        "s.word_count, s.content, b.slug AS book_slug, b.title AS book_title, "
        "l.snippet, sr.source_key, ps.use_role "
        "FROM objective_chunk_links l "
        "JOIN sections s ON s.id = l.section_id "
        "JOIN books b ON b.id = l.book_id "
        "JOIN source_registry sr ON sr.book_id = b.id "
        "JOIN certification_pack_sources ps "
        "  ON ps.source_id = sr.id AND ps.pack_id = ? "
        "WHERE l.objective_id = ? AND ps.disposition = 'active' "
        "AND ps.use_role IN ('primary_instruction','supplemental_instruction') "
        "ORDER BY CASE ps.use_role WHEN 'primary_instruction' THEN 0 ELSE 1 END, "
        "b.slug, s.position",
        (pack_id, objective_id),
    ).fetchall()
    citations = []
    for row in rows:
        item = dict(row)
        content = item.pop("content") or ""
        citations.append({
            **item,
            "selected_primary": False,
            "focused_excerpt": None,
        })
        citations[-1]["_content"] = content
    return citations


def compile_dossiers(conn, pack_id, timestamp):
    conn.execute("DELETE FROM objective_dossiers WHERE pack_id = ?", (pack_id,))
    objectives = conn.execute(
        "SELECT po.objective_id, po.official_source_id, po.primary_source_count, "
        "po.supplemental_source_count, po.assessment_source_count, "
        "o.code, o.description, o.provenance, e.code AS exam_code, "
        "e.name AS exam_name, d.id AS domain_id, d.code AS domain_code, "
        "d.name AS domain_name, sr.source_key AS official_source_key, "
        "sr.title AS official_source_title, sr.source_url AS official_source_url "
        "FROM certification_pack_objectives po "
        "JOIN objectives o ON o.id = po.objective_id "
        "JOIN exams e ON e.id = o.exam_id "
        "LEFT JOIN domains d ON d.id = o.domain_id "
        "JOIN source_registry sr ON sr.id = po.official_source_id "
        "WHERE po.pack_id = ? ORDER BY e.sequence_order, d.code, o.code",
        (pack_id,),
    ).fetchall()

    counts = {"complete": 0, "thin": 0, "conflicted": 0, "missing": 0}
    for row in objectives:
        objective = dict(row)
        citations = _instructional_citations(
            conn, pack_id, objective["objective_id"]
        )
        primary = [
            item for item in citations
            if item["use_role"] == "primary_instruction"
        ]
        supplemental = [
            item for item in citations
            if item["use_role"] == "supplemental_instruction"
        ]
        selected_primary = primary[0] if primary else None
        if selected_primary:
            selected_primary["selected_primary"] = True
            selected_primary["focused_excerpt"] = _focused_excerpt(
                selected_primary["_content"], objective["code"]
            )
        for item in citations:
            item.pop("_content", None)

        direct_questions = conn.execute(
            "SELECT COUNT(*) n FROM question_bank "
            "WHERE objective_id = ? AND active = 1",
            (objective["objective_id"],),
        ).fetchone()["n"]
        domain_questions = 0
        if objective["domain_id"]:
            domain_questions = conn.execute(
                "SELECT COUNT(*) n FROM question_bank "
                "WHERE exam_id = (SELECT exam_id FROM objectives WHERE id = ?) "
                "AND domain_id = ? AND active = 1",
                (objective["objective_id"], objective["domain_id"]),
            ).fetchone()["n"]
        conflicts = conn.execute(
            "SELECT COUNT(*) n FROM compiler_findings "
            "WHERE pack_id = ? AND category = 'conflict' "
            "AND (objective_code = ? OR objective_code IS NULL) "
            "AND (exam_code = ? OR exam_code IS NULL)",
            (pack_id, objective["code"], objective["exam_code"]),
        ).fetchone()["n"]

        has_primary = bool(primary)
        has_supplemental = bool(supplemental)
        has_assessment = objective["assessment_source_count"] > 0
        has_instruction = has_primary or has_supplemental
        score = (
            20
            + (50 if has_primary else 0)
            + (20 if has_supplemental else 0)
            + (10 if has_assessment else 0)
        )
        if conflicts:
            status = "conflicted"
        elif not has_instruction:
            status = "missing"
        elif not (has_primary and has_supplemental and has_assessment):
            status = "thin"
        else:
            status = "complete"
        counts[status] += 1

        gates = {
            "official_scope_pinned": True,
            "primary_instruction": has_primary,
            "supplemental_instruction": has_supplemental,
            "assessment_source": has_assessment,
            "conflict_free": conflicts == 0,
        }
        has_official_heading = objective["provenance"].endswith(
            ": canonical objective heading"
        )
        payload = {
            "schema_version": DOSSIER_SCHEMA_VERSION,
            "objective": {
                "id": objective["objective_id"],
                "exam_code": objective["exam_code"],
                "exam_name": objective["exam_name"],
                "code": objective["code"],
                "description": objective["description"],
                "description_provenance": objective["provenance"],
                "domain_code": objective["domain_code"],
                "domain_name": objective["domain_name"],
            },
            "official_scope": {
                "granularity": (
                    "objective_heading" if has_official_heading else "objective_code"
                ),
                "source_key": objective["official_source_key"],
                "title": objective["official_source_title"],
                "url": objective["official_source_url"],
                "note": (
                    "The displayed objective heading was deterministically "
                    "extracted from the pinned official vendor document."
                    if has_official_heading else
                    "The official source pins this objective code and exam "
                    "scope. The displayed description is not yet parsed from "
                    "the official vendor document."
                ),
            },
            "quality": {
                "status": status,
                "score": score,
                "gates": gates,
                "conflict_count": conflicts,
            },
            "instructional_citations": citations,
            "assessment": {
                "source_count": objective["assessment_source_count"],
                "direct_objective_question_count": direct_questions,
                "domain_question_count": domain_questions,
                "mapping_note": (
                    "Imported practice questions are currently mapped at "
                    "domain level unless explicitly curated to an objective."
                ),
            },
        }
        conn.execute(
            "INSERT INTO objective_dossiers("
            "pack_id, objective_id, official_source_id, status, quality_score, "
            "primary_section_id, primary_source_count, supplemental_source_count, "
            "assessment_source_count, direct_question_count, domain_question_count, "
            "dossier_json, compiled_at, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pack_id, objective["objective_id"], objective["official_source_id"],
                status, score,
                selected_primary["section_id"] if selected_primary else None,
                objective["primary_source_count"],
                objective["supplemental_source_count"],
                objective["assessment_source_count"],
                direct_questions, domain_questions,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                timestamp, timestamp, timestamp,
            ),
        )
    return {"total": len(objectives), **counts}


def get_dossier_summary(conn, certification_code="aplus"):
    pack = conn.execute(
        "SELECT p.id, p.pack_version, p.exam_version, p.status, p.compiler_version, "
        "c.code AS certification_code, c.name AS certification_name "
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
    status_counts = {
        row["status"]: row["n"]
        for row in conn.execute(
            "SELECT status, COUNT(*) n FROM objective_dossiers "
            "WHERE pack_id = ? GROUP BY status",
            (pack["id"],),
        )
    }
    result["counts"] = {
        key: status_counts.get(key, 0)
        for key in ("complete", "thin", "conflicted", "missing")
    }
    result["total"] = sum(result["counts"].values())
    result["objectives"] = [
        dict(row) for row in conn.execute(
            "SELECT od.objective_id, od.status, od.quality_score, "
            "od.primary_source_count, od.supplemental_source_count, "
            "od.assessment_source_count, od.direct_question_count, "
            "od.domain_question_count, o.code, o.description, "
            "e.code AS exam_code, d.code AS domain_code, d.name AS domain_name "
            "FROM objective_dossiers od "
            "JOIN objectives o ON o.id = od.objective_id "
            "JOIN exams e ON e.id = o.exam_id "
            "LEFT JOIN domains d ON d.id = o.domain_id "
            "WHERE od.pack_id = ? "
            "ORDER BY e.sequence_order, CAST(d.code AS INTEGER), o.code",
            (pack["id"],),
        )
    ]
    return result


def get_dossier(conn, objective_id, certification_code="aplus"):
    row = conn.execute(
        "SELECT od.*, p.pack_version, p.exam_version, c.code AS certification_code "
        "FROM objective_dossiers od "
        "JOIN certification_packs p ON p.id = od.pack_id "
        "JOIN certifications c ON c.id = p.certification_id "
        "WHERE od.objective_id = ? AND c.code = ? "
        "ORDER BY CASE p.status WHEN 'ready' THEN 0 ELSE 1 END, p.compiled_at DESC "
        "LIMIT 1",
        (objective_id, certification_code),
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["dossier"] = json.loads(result.pop("dossier_json"))
    return result
