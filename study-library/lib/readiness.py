"""Explainable exam-readiness gates derived from separate evidence classes.

This module deliberately returns no composite score.  A learner is ready only when
every required gate has direct evidence; reading time and career history never stand in
for retained knowledge, hands-on reproduction, or timed exam performance.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from lib import certification_spines
from lib.api_logic import ApiError, now_iso


MASTERED_SCOPE_STATUSES = {"provisional_mastery", "mastered_after_remediation"}
PRACTICE_SCORE_THRESHOLD = 85.0
DOMAIN_FLOOR_THRESHOLD = 75.0
PRACTICE_EXAMS_REQUIRED = 2


def _current_exam_code(conn):
    row = conn.execute(
        "SELECT e.code FROM plan_weeks w JOIN exams e ON e.id=w.exam_id "
        "WHERE EXISTS (SELECT 1 FROM plan_tasks t WHERE t.week_id=w.id AND t.completed=0) "
        "ORDER BY w.week_number LIMIT 1"
    ).fetchone()
    if row:
        return row["code"]
    row = conn.execute("SELECT code FROM exams ORDER BY sequence_order, id LIMIT 1").fetchone()
    return row["code"] if row else None


def _gate(key, label, passed, observed, required, rationale, action):
    return {
        "key": key,
        "label": label,
        "passed": bool(passed),
        "observed": observed,
        "required": required,
        "rationale": rationale,
        "action": action,
    }


def _domain_floor(conn, attempt_id):
    rows = conn.execute(
        "SELECT r.domain_id, COUNT(*) AS total, "
        "SUM(CASE WHEN r.is_correct=1 THEN 1 ELSE 0 END) AS correct "
        "FROM practice_exam_responses r WHERE r.attempt_id=? "
        "GROUP BY r.domain_id",
        (attempt_id,),
    ).fetchall()
    scores = [
        round(row["correct"] / row["total"] * 100.0, 1)
        for row in rows if row["total"]
    ]
    return min(scores) if scores else None


def get_exam_readiness(conn, exam_code=None):
    exam_code = exam_code or _current_exam_code(conn)
    if not exam_code:
        return {
            "schema_version": 1,
            "generated_at": now_iso(),
            "exam": None,
            "status": "unavailable",
            "label": "not enough evidence yet",
            "ready_to_schedule": False,
            "gates": [],
            "passed_gate_count": 0,
            "total_gate_count": 0,
            "next_gate": None,
            "policy": {
                "composite_score": None,
                "career_history_grants_mastery": False,
                "reading_time_grants_mastery": False,
                "exam_booking_requires_all_gates": True,
            },
            "evidence_note": "Configure an exam before Waypoint can evaluate readiness evidence.",
        }
    exam = conn.execute(
        "SELECT e.id, e.code, e.name, e.certification_id, c.code AS certification_code, "
        "c.name AS certification_name FROM exams e "
        "JOIN certifications c ON c.id=e.certification_id WHERE e.code=?",
        (exam_code,),
    ).fetchone()
    if not exam:
        raise ApiError(404, "exam not found")
    exam = dict(exam)

    spine = certification_spines.certification_for_exam(exam_code)
    spine_exam = next(
        (item for item in spine["exams"] if item["code"] == exam_code),
        None,
    ) if spine else None
    source_status = (
        spine_exam["official_source"]["verification_status"]
        if spine_exam else "missing"
    )

    pack = conn.execute(
        "SELECT cp.id AS pack_id, cp.status AS pack_status, b.id AS build_id, "
        "b.status AS build_status, b.build_sha256 "
        "FROM certification_pack_active_builds active "
        "JOIN certification_pack_builds b ON b.id=active.build_id "
        "JOIN certification_packs cp ON cp.certification_id=b.certification_id "
        "AND cp.pack_version=b.pack_version "
        "WHERE active.certification_id=? ORDER BY cp.id DESC LIMIT 1",
        (exam["certification_id"],),
    ).fetchone()
    pack = dict(pack) if pack else None

    objectives = conn.execute(
        "SELECT COUNT(*) AS total FROM objectives WHERE exam_id=?",
        (exam["id"],),
    ).fetchone()["total"]
    complete_dossiers = 0
    if pack:
        complete_dossiers = conn.execute(
            "SELECT COUNT(*) AS total FROM objective_dossiers d "
            "JOIN objectives o ON o.id=d.objective_id "
            "WHERE d.pack_id=? AND o.exam_id=? AND d.status='complete'",
            (pack["pack_id"], exam["id"]),
        ).fetchone()["total"]

    learning = conn.execute(
        "SELECT COUNT(DISTINCT CASE WHEN event_type='lesson_completed' THEN objective_id END) "
        "AS lessons, COUNT(DISTINCT CASE WHEN event_type='recall_completed' THEN objective_id END) "
        "AS recalls FROM learning_events WHERE objective_id IN "
        "(SELECT id FROM objectives WHERE exam_id=?)",
        (exam["id"],),
    ).fetchone()
    retention = conn.execute(
        "SELECT COUNT(*) AS scheduled, "
        "SUM(CASE WHEN due_at<=? THEN 1 ELSE 0 END) AS due "
        "FROM objective_retention_state WHERE objective_id IN "
        "(SELECT id FROM objectives WHERE exam_id=?)",
        (datetime.now(timezone.utc).isoformat(), exam["id"]),
    ).fetchone()

    scopes = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN m.status IN ('provisional_mastery','mastered_after_remediation') "
        "THEN 1 ELSE 0 END) AS mastered "
        "FROM diagnostic_scopes s LEFT JOIN scope_mastery m ON m.scope_id=s.id "
        "WHERE s.exam_id=? AND s.scope_type='domain' AND s.enabled=1",
        (exam["id"],),
    ).fetchone()
    open_gaps = conn.execute(
        "SELECT COUNT(*) AS total FROM remediation_items r "
        "JOIN diagnostic_scopes s ON s.id=r.scope_id "
        "WHERE s.exam_id=? AND r.status='open'",
        (exam["id"],),
    ).fetchone()["total"]

    domain_total = conn.execute(
        "SELECT COUNT(*) AS total FROM domains WHERE exam_id=?", (exam["id"],)
    ).fetchone()["total"]
    lab = conn.execute(
        "SELECT COUNT(*) AS completed, "
        "SUM(CASE WHEN l.completion_level='unaided' THEN 1 ELSE 0 END) AS unaided, "
        "COUNT(DISTINCT CASE WHEN l.completion_level='unaided' THEN o.domain_id END) "
        "AS unaided_domains, "
        "COUNT(DISTINCT o.domain_id) AS domains_covered "
        "FROM hands_on_labs l JOIN objectives o ON o.id=l.objective_id "
        "WHERE o.exam_id=? AND l.status='completed' AND l.archived=0",
        (exam["id"],),
    ).fetchone()
    unaided_required = max(1, math.ceil(domain_total / 2)) if domain_total else 1

    practice_rows = conn.execute(
        "SELECT id, raw_score_pct, timed_out, reused_question_ids_json, submitted_at "
        "FROM practice_exam_attempts WHERE exam_id=? AND state='submitted' "
        "ORDER BY submitted_at DESC, id DESC LIMIT ?",
        (exam["id"], PRACTICE_EXAMS_REQUIRED),
    ).fetchall()
    practice = []
    for row in practice_rows:
        item = dict(row)
        try:
            reused_count = len(json.loads(item["reused_question_ids_json"] or "[]"))
        except (TypeError, json.JSONDecodeError):
            reused_count = -1
        item["reused_question_count"] = reused_count
        item["domain_floor_pct"] = _domain_floor(conn, item["id"])
        item.pop("reused_question_ids_json", None)
        practice.append(item)
    practice_passed = (
        len(practice) == PRACTICE_EXAMS_REQUIRED
        and all(
            item["raw_score_pct"] is not None
            and item["raw_score_pct"] >= PRACTICE_SCORE_THRESHOLD
            and not item["timed_out"]
            and item["reused_question_count"] == 0
            and item["domain_floor_pct"] is not None
            and item["domain_floor_pct"] >= DOMAIN_FLOOR_THRESHOLD
            for item in practice
        )
    )

    gates = [
        _gate(
            "official_scope",
            "Official objective source is hash-verified",
            source_status == "hash_verified",
            source_status,
            "hash_verified",
            "The exam scope must be pinned to a verified vendor document.",
            {"type": "operator_review", "href": "/library"},
        ),
        _gate(
            "published_pack",
            "Governed knowledge pack is published",
            bool(pack and pack["pack_status"] == "ready" and pack["build_status"] == "published"),
            pack["build_status"] if pack else "missing",
            "published",
            "A reviewed, immutable source pack must be active before readiness can be assessed.",
            {"type": "operator_review", "href": "/library"},
        ),
        _gate(
            "source_coverage",
            "Every official objective has complete source coverage",
            objectives > 0 and complete_dossiers == objectives,
            {"complete": complete_dossiers, "total": objectives},
            "all objectives complete",
            "Source completeness is a prerequisite, not learner mastery.",
            {"type": "operator_review", "href": "/library"},
        ),
        _gate(
            "lessons",
            "Every objective lesson is completed",
            objectives > 0 and learning["lessons"] == objectives,
            {"completed": learning["lessons"], "total": objectives},
            "all objectives",
            "Opening or reading material does not complete an objective lesson.",
            {"type": "learn", "href": "/learn"},
        ),
        _gate(
            "recall",
            "Every objective has an active-recall completion",
            objectives > 0 and learning["recalls"] == objectives,
            {"completed": learning["recalls"], "total": objectives},
            "all objectives",
            "Each objective must be retrieved from memory, not only recognized while reading.",
            {"type": "learn", "href": "/learn"},
        ),
        _gate(
            "domain_checks",
            "Every domain knowledge check is mastered",
            scopes["total"] > 0 and (scopes["mastered"] or 0) == scopes["total"],
            {"mastered": scopes["mastered"] or 0, "total": scopes["total"]},
            "all enabled domains",
            "Domain checks are assessment evidence but do not substitute for hands-on work.",
            {"type": "knowledge_check", "href": "/study"},
        ),
        _gate(
            "retention",
            "Every objective is scheduled and no review is overdue",
            objectives > 0 and retention["scheduled"] == objectives and (retention["due"] or 0) == 0,
            {"scheduled": retention["scheduled"], "total": objectives, "due": retention["due"] or 0},
            "all scheduled, zero due",
            "A lesson is not durable evidence until it participates in spaced review.",
            {"type": "retention", "href": "/learn"},
        ),
        _gate(
            "hands_on",
            "Hands-on work covers every domain",
            domain_total > 0
            and (lab["domains_covered"] or 0) == domain_total
            and (lab["unaided_domains"] or 0) >= unaided_required,
            {
                "completed": lab["completed"] or 0,
                "domains_covered": lab["domains_covered"] or 0,
                "domains_total": domain_total,
                "unaided": lab["unaided"] or 0,
                "unaided_domains": lab["unaided_domains"] or 0,
            },
            {"domains": domain_total, "unaided_labs": unaided_required},
            "At least one completed lab per domain and unaided reproduction across half the domains are required.",
            {"type": "lab", "href": "/labs"},
        ),
        _gate(
            "open_gaps",
            "No remediation gaps remain open",
            open_gaps == 0,
            open_gaps,
            0,
            "Known misses must be reviewed before an exam recommendation.",
            {"type": "remediation", "href": "/study"},
        ),
        _gate(
            "fresh_practice_exams",
            "Two fresh timed practice exams meet the readiness thresholds",
            practice_passed,
            practice,
            {
                "attempts": PRACTICE_EXAMS_REQUIRED,
                "minimum_score_pct": PRACTICE_SCORE_THRESHOLD,
                "minimum_domain_pct": DOMAIN_FLOOR_THRESHOLD,
                "timed_out": False,
                "reused_questions": 0,
            },
            "Both exams must be fresh, completed on time, at least 85% overall, and at least 75% in every domain.",
            {"type": "practice_exam", "href": "/practice"},
        ),
    ]

    first_blocker = next((gate for gate in gates if not gate["passed"]), None)
    if all(gate["passed"] for gate in gates):
        status = "ready_to_schedule"
        label = "Ready to schedule"
    elif not gates[1]["passed"] or not gates[2]["passed"]:
        status = "content_not_ready"
        label = "Knowledge pack not ready"
    else:
        status = "building_evidence"
        label = "Building readiness evidence"
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "exam": {
            "id": exam["id"],
            "code": exam["code"],
            "name": exam["name"],
            "certification_id": exam["certification_code"],
            "certification_name": exam["certification_name"],
        },
        "status": status,
        "label": label,
        "ready_to_schedule": status == "ready_to_schedule",
        "gates": gates,
        "passed_gate_count": sum(gate["passed"] for gate in gates),
        "total_gate_count": len(gates),
        "next_gate": first_blocker,
        "policy": {
            "composite_score": None,
            "career_history_grants_mastery": False,
            "reading_time_grants_mastery": False,
            "exam_booking_requires_all_gates": True,
        },
        "evidence_note": (
            "Readiness is an explainable Waypoint recommendation, not an official "
            "vendor score or pass guarantee. Every evidence class remains separate."
        ),
    }
