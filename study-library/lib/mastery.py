"""Conservative objective-level knowledge projections.

The practice bank is currently mapped at domain granularity. This module keeps
that domain signal visible without copying it onto individual objectives as if
it were exact evidence. Objective status changes only from objective-linked
practice, completed objective-linked tasks, or opened cited sections.
"""

import json

from lib import learning
from lib.api_logic import ApiError, now_iso


STATUS_ORDER = {
    "needs_work": 0,
    "not_assessed": 1,
    "studied": 2,
    "practiced": 3,
    "strong_signal": 4,
}


def _reading_counts(conn):
    opened_by_objective = {}
    unresolved_stable_ids = set()
    for table in ("guided_study_events", "learning_events"):
        rows = conn.execute(
            f"SELECT metadata_json FROM {table} WHERE event_type = 'reading_opened'"
        ).fetchall()
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            stable_id = metadata.get("section_stable_id")
            if isinstance(stable_id, str) and stable_id:
                objective_id = metadata.get("objective_id")
                if isinstance(objective_id, int):
                    opened_by_objective.setdefault(objective_id, set()).add(stable_id)
                else:
                    unresolved_stable_ids.add(stable_id)
    if not unresolved_stable_ids:
        return {
            objective_id: len(stable_ids)
            for objective_id, stable_ids in opened_by_objective.items()
        }
    placeholders = ",".join("?" * len(unresolved_stable_ids))
    for row in conn.execute(
        f"SELECT DISTINCT l.objective_id, s.stable_id "
        f"FROM objective_chunk_links l JOIN sections s ON s.id = l.section_id "
        f"WHERE s.stable_id IN ({placeholders})",
        sorted(unresolved_stable_ids),
    ).fetchall():
        opened_by_objective.setdefault(row["objective_id"], set()).add(
            row["stable_id"]
        )
    return {
        objective_id: len(stable_ids)
        for objective_id, stable_ids in opened_by_objective.items()
    }


def _objective_status(attempts, latest_pct, average_pct, study_events):
    if attempts:
        if latest_pct is not None and latest_pct < 70:
            return "needs_work"
        if attempts >= 2 and average_pct is not None and average_pct >= 85:
            return "strong_signal"
        return "practiced"
    if study_events:
        return "studied"
    return "not_assessed"


def _domain_signal(conn, domain_id):
    row = conn.execute(
        "SELECT s.id AS scope_id, s.name AS scope_name, "
        "COALESCE(m.status, 'unassessed') AS status, m.retention_due_at, "
        "a.raw_score_pct AS latest_raw_score_pct, "
        "a.effective_score_pct AS latest_effective_score_pct, "
        "a.submitted_at AS latest_attempt_at, "
        "(SELECT COUNT(*) FROM remediation_items ri "
        " WHERE ri.scope_id = s.id AND ri.status = 'open') AS open_gap_count "
        "FROM diagnostic_scopes s "
        "LEFT JOIN scope_mastery m ON m.scope_id = s.id "
        "LEFT JOIN diagnostic_attempts a ON a.id = m.last_attempt_id "
        "WHERE s.scope_type = 'domain' AND s.domain_id = ? "
        "ORDER BY s.id LIMIT 1",
        (domain_id,),
    ).fetchone()
    return dict(row) if row else {
        "scope_id": None,
        "scope_name": None,
        "status": "unassessed",
        "retention_due_at": None,
        "latest_raw_score_pct": None,
        "latest_effective_score_pct": None,
        "latest_attempt_at": None,
        "open_gap_count": 0,
    }


def _objective_rows(conn, exam):
    params = []
    where = ""
    if exam:
        where = "WHERE e.code = ?"
        params.append(exam)
    return conn.execute(
        "SELECT o.id, o.code, o.description, o.confidence, o.provenance, "
        "o.domain_id, e.id AS exam_id, e.code AS exam_code, e.name AS exam_name, "
        "e.sequence_order AS exam_order, d.code AS domain_code, d.name AS domain_name, "
        "COALESCE(("
        " SELECT od.primary_source_count + od.supplemental_source_count "
        " FROM objective_dossiers od "
        " JOIN certification_packs cp ON cp.id = od.pack_id "
        " WHERE od.objective_id = o.id AND cp.status = 'ready' "
        " ORDER BY cp.compiled_at DESC LIMIT 1"
        "), ("
        " SELECT COUNT(*) FROM objective_chunk_links l "
        " JOIN books b2 ON b2.id = l.book_id "
        " WHERE l.objective_id = o.id AND b2.slug LIKE '%review%'"
        ")) AS source_section_count, "
        "(SELECT COUNT(*) FROM plan_tasks t "
        " WHERE t.related_objective_id = o.id AND t.completed = 1) AS completed_task_count, "
        "(SELECT COUNT(*) FROM plan_tasks t "
        " JOIN objective_chunk_links l ON l.section_id = t.related_section_id "
        " WHERE l.objective_id = o.id AND t.completed = 1) AS completed_linked_task_count, "
        "(SELECT COUNT(*) FROM practice_attempts a "
        " WHERE a.objective_id = o.id AND a.held_out = 0) AS attempt_count, "
        "(SELECT ROUND(AVG(a.score * 100.0 / a.total), 1) FROM practice_attempts a "
        " WHERE a.objective_id = o.id AND a.held_out = 0) AS average_pct, "
        "(SELECT ROUND(a.score * 100.0 / a.total, 1) FROM practice_attempts a "
        " WHERE a.objective_id = o.id AND a.held_out = 0 "
        " ORDER BY a.occurred_at DESC, a.id DESC LIMIT 1) AS latest_pct, "
        "(SELECT a.occurred_at FROM practice_attempts a "
        " WHERE a.objective_id = o.id AND a.held_out = 0 "
        " ORDER BY a.occurred_at DESC, a.id DESC LIMIT 1) AS latest_assessment_at "
        "FROM objectives o JOIN exams e ON e.id = o.exam_id "
        "LEFT JOIN domains d ON d.id = o.domain_id "
        f"{where} "
        "ORDER BY e.sequence_order, CAST(d.code AS INTEGER), "
        "CAST(SUBSTR(o.code, INSTR(o.code, '.') + 1) AS INTEGER), o.code",
        params,
    ).fetchall()


def get_mastery_map(conn, exam=None):
    if exam and conn.execute(
        "SELECT id FROM exams WHERE code = ?", (exam,)
    ).fetchone() is None:
        raise ApiError(400, "unknown exam code")

    reading_counts = _reading_counts(conn)
    learning_counts = learning.counts_by_objective(conn)
    exams = []
    exam_lookup = {}
    domain_lookup = {}
    all_objectives = []

    for row in _objective_rows(conn, exam):
        data = dict(row)
        exam_entry = exam_lookup.get(data["exam_id"])
        if not exam_entry:
            exam_entry = {
                "id": data["exam_id"],
                "code": data["exam_code"],
                "name": data["exam_name"],
                "domains": [],
            }
            exam_lookup[data["exam_id"]] = exam_entry
            exams.append(exam_entry)

        domain_key = (data["exam_id"], data["domain_id"])
        domain_entry = domain_lookup.get(domain_key)
        if not domain_entry:
            domain_entry = {
                "id": data["domain_id"],
                "code": data["domain_code"],
                "name": data["domain_name"],
                "signal": _domain_signal(conn, data["domain_id"]),
                "summary": {},
                "objectives": [],
            }
            domain_lookup[domain_key] = domain_entry
            exam_entry["domains"].append(domain_entry)

        study_events = (
            data["completed_task_count"]
            + data["completed_linked_task_count"]
            + reading_counts.get(data["id"], 0)
            + learning_counts.get(data["id"], {}).get("lesson_completed", 0)
            + learning_counts.get(data["id"], {}).get("recall_completed", 0)
        )
        status = _objective_status(
            data["attempt_count"],
            data["latest_pct"],
            data["average_pct"],
            study_events,
        )
        objective = {
            "id": data["id"],
            "code": data["code"],
            "description": data["description"],
            "status": status,
            "status_rank": STATUS_ORDER[status],
            "mastery_score": data["average_pct"],
            "evidence": {
                "objective_assessments": data["attempt_count"],
                "latest_assessment_pct": data["latest_pct"],
                "average_assessment_pct": data["average_pct"],
                "latest_assessment_at": data["latest_assessment_at"],
                "completed_tasks": (
                    data["completed_task_count"]
                    + data["completed_linked_task_count"]
                ),
                "cited_sections_opened": reading_counts.get(data["id"], 0),
                "lessons_completed": learning_counts.get(data["id"], {}).get(
                    "lesson_completed", 0
                ),
                "recall_completed": learning_counts.get(data["id"], {}).get(
                    "recall_completed", 0
                ),
                "source_sections_available": data["source_section_count"],
            },
        }
        domain_entry["objectives"].append(objective)
        all_objectives.append(objective)

    for domain in domain_lookup.values():
        objectives = domain["objectives"]
        domain["summary"] = {
            "total": len(objectives),
            "strong_signal": sum(o["status"] == "strong_signal" for o in objectives),
            "practiced": sum(o["status"] == "practiced" for o in objectives),
            "studied": sum(o["status"] == "studied" for o in objectives),
            "needs_work": sum(o["status"] == "needs_work" for o in objectives),
            "not_assessed": sum(o["status"] == "not_assessed" for o in objectives),
        }

    totals = {
        "objectives": len(all_objectives),
        "strong_signal": sum(o["status"] == "strong_signal" for o in all_objectives),
        "practiced": sum(o["status"] == "practiced" for o in all_objectives),
        "studied": sum(o["status"] == "studied" for o in all_objectives),
        "needs_work": sum(o["status"] == "needs_work" for o in all_objectives),
        "not_assessed": sum(o["status"] == "not_assessed" for o in all_objectives),
        "objectives_with_direct_assessment": sum(
            o["evidence"]["objective_assessments"] > 0 for o in all_objectives
        ),
        "objectives_started": sum(
            (
                o["evidence"]["cited_sections_opened"]
                + o["evidence"]["lessons_completed"]
                + o["evidence"]["recall_completed"]
            ) > 0
            for o in all_objectives
        ),
        "lessons_completed": sum(
            o["evidence"]["lessons_completed"] > 0 for o in all_objectives
        ),
        "recall_completed": sum(
            o["evidence"]["recall_completed"] > 0 for o in all_objectives
        ),
    }
    totals["evidence_coverage_pct"] = (
        round(
            (
                totals["objectives"]
                - totals["not_assessed"]
            ) / totals["objectives"] * 100,
            1,
        )
        if totals["objectives"]
        else 0
    )
    return {
        "generated_at": now_iso(),
        "exam_filter": exam,
        "totals": totals,
        "exams": exams,
        "evidence_note": (
            "Objective status uses only objective-linked practice and study activity. "
            "Domain knowledge checks remain a separate domain signal and are not "
            "presented as exact objective mastery. Hands-on and PBQ ability are not inferred."
        ),
        "mapping_note": (
        "The imported practice bank is currently domain-mapped. Exact objective "
            "assessment coverage will grow as objective-linked checks are added. "
            "Reading links use the one chapter-aligned Review Guide citation for "
            "each objective; broader book links require further curation."
        ),
    }


def get_objective_mastery(conn, objective_id):
    row = conn.execute(
        "SELECT e.code AS exam_code FROM objectives o "
        "JOIN exams e ON e.id = o.exam_id WHERE o.id = ?",
        (objective_id,),
    ).fetchone()
    if not row:
        return None
    mastery_map = get_mastery_map(conn, exam=row["exam_code"])
    for exam in mastery_map["exams"]:
        for domain in exam["domains"]:
            for objective in domain["objectives"]:
                if objective["id"] == objective_id:
                    return {
                        **objective,
                        "domain_signal": domain["signal"],
                        "domain": {
                            "id": domain["id"],
                            "code": domain["code"],
                            "name": domain["name"],
                        },
                    }
    return None
