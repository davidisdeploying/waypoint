"""Timed, resumable practice exams with a protected held-out question pool."""

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.api_logic import ApiError, now_iso
from lib import question_figures


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = REPO_ROOT / "sources" / "certifications"
POOL_SIZE = 180
QUESTION_TARGET = 90
DURATION_MINUTES = 90


def _json_list(raw):
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _exam_manifest(exam_code):
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        for exam in payload.get("exams", []):
            if exam.get("code") == exam_code:
                return payload.get("pack_version", path.stem), exam
    raise ApiError(400, "exam has no governed domain-weight manifest")


def _allocation(domains, target):
    raw = [(item, target * item["weight"] / 100.0) for item in domains]
    counts = {item["code"]: int(value) for item, value in raw}
    remaining = target - sum(counts.values())
    ranked = sorted(raw, key=lambda pair: (pair[1] % 1, pair[0]["code"]), reverse=True)
    for item, _ in ranked[:remaining]:
        counts[item["code"]] += 1
    return counts


def reserve_pool(conn, exam_id):
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM practice_exam_question_pool WHERE exam_id = ?",
        (exam_id,),
    ).fetchone()["n"]
    if existing:
        return existing
    exam_row = conn.execute(
        "SELECT code FROM exams WHERE id = ?", (exam_id,)
    ).fetchone()
    if not exam_row:
        raise ApiError(404, "exam not found")
    pool_version, manifest_exam = _exam_manifest(exam_row["code"])
    allocation = _allocation(manifest_exam["domains"], POOL_SIZE)
    timestamp = now_iso()
    selected = []
    for domain in manifest_exam["domains"]:
        rows = conn.execute(
            "SELECT q.id, q.stable_id FROM question_bank q "
            "JOIN domains d ON d.id = q.domain_id "
            "WHERE q.exam_id = ? AND d.code = ? AND q.active = 1 "
            "AND (q.requires_figure = 0 OR q.figure_member IS NOT NULL) "
            "AND q.id NOT IN (SELECT question_id FROM diagnostic_responses) "
            "ORDER BY q.stable_id",
            (exam_id, domain["code"]),
        ).fetchall()
        ranked = sorted(
            rows,
            key=lambda row: hashlib.sha256(
                f"{pool_version}:{row['stable_id']}".encode()
            ).hexdigest(),
        )
        needed = allocation[domain["code"]]
        if len(ranked) < needed:
            raise ApiError(
                409,
                f"insufficient unseen held-out questions for domain {domain['code']}",
            )
        selected.extend(row["id"] for row in ranked[:needed])
    for question_id in selected:
        conn.execute(
            "INSERT OR IGNORE INTO practice_exam_question_pool("
            "question_id, exam_id, pool_version, reserved_at"
            ") VALUES (?, ?, ?, ?)",
            (question_id, exam_id, pool_version, timestamp),
        )
    conn.commit()
    return len(selected)


def overview(conn):
    exams = conn.execute(
        "SELECT e.id, e.code, e.name, "
        "(SELECT COUNT(*) FROM question_bank q WHERE q.exam_id=e.id AND q.active=1) AS available_questions, "
        "(SELECT COUNT(*) FROM practice_exam_question_pool p WHERE p.exam_id=e.id) AS reserved_questions "
        "FROM exams e ORDER BY e.sequence_order, e.id"
    ).fetchall()
    output = []
    for row in exams:
        item = dict(row)
        active = conn.execute(
            "SELECT id, started_at, expires_at FROM practice_exam_attempts "
            "WHERE exam_id=? AND state='in_progress' ORDER BY started_at DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        recent = conn.execute(
            "SELECT id, state, started_at, submitted_at, raw_score_pct, "
            "readiness_band, timed_out FROM practice_exam_attempts "
            "WHERE exam_id=? ORDER BY started_at DESC LIMIT 5",
            (row["id"],),
        ).fetchall()
        item["in_progress"] = dict(active) if active else None
        item["recent_attempts"] = [dict(entry) for entry in recent]
        output.append(item)
    return {
        "exams": output,
        "question_target": QUESTION_TARGET,
        "duration_minutes": DURATION_MINUTES,
        "evidence_note": (
            "Scores are Waypoint practice-readiness signals, not official "
            "CompTIA scaled scores or pass guarantees."
        ),
        "pool_note": (
            "Practice-exam questions are reserved from knowledge checks and "
            "excluded from lesson and Study Coach retrieval."
        ),
    }


def _seen_ids(conn, exam_id):
    return {
        row["question_id"] for row in conn.execute(
            "SELECT DISTINCT r.question_id FROM practice_exam_responses r "
            "JOIN practice_exam_attempts a ON a.id=r.attempt_id "
            "WHERE a.exam_id=? AND a.state='submitted'",
            (exam_id,),
        ).fetchall()
    }


def start_attempt(conn, exam_code):
    exam = conn.execute(
        "SELECT id, code, name FROM exams WHERE code=?", (exam_code,)
    ).fetchone()
    if not exam:
        raise ApiError(404, "exam not found")
    active = conn.execute(
        "SELECT id FROM practice_exam_attempts "
        "WHERE exam_id=? AND state='in_progress' ORDER BY started_at DESC LIMIT 1",
        (exam["id"],),
    ).fetchone()
    if active:
        raise ApiError(409, "an in-progress practice exam already exists")
    reserve_pool(conn, exam["id"])
    pool = [
        dict(row) for row in conn.execute(
            "SELECT p.question_id, d.code AS domain_code "
            "FROM practice_exam_question_pool p "
            "JOIN question_bank q ON q.id=p.question_id "
            "JOIN domains d ON d.id=q.domain_id "
            "WHERE p.exam_id=? ORDER BY p.question_id",
            (exam["id"],),
        ).fetchall()
    ]
    seen = _seen_ids(conn, exam["id"])
    _, manifest_exam = _exam_manifest(exam["code"])
    attempt_allocation = _allocation(manifest_exam["domains"], QUESTION_TARGET)
    chosen = []
    reused = []
    for domain in manifest_exam["domains"]:
        domain_ids = [
            item["question_id"] for item in pool
            if item["domain_code"] == domain["code"]
        ]
        unseen = [qid for qid in domain_ids if qid not in seen]
        seen_domain = [qid for qid in domain_ids if qid in seen]
        random.shuffle(unseen)
        random.shuffle(seen_domain)
        needed = attempt_allocation[domain["code"]]
        domain_chosen = unseen[:needed]
        domain_reused = seen_domain[: max(0, needed - len(domain_chosen))]
        chosen.extend(domain_chosen + domain_reused)
        reused.extend(domain_reused)
    if len(chosen) != QUESTION_TARGET:
        raise ApiError(409, "held-out pool cannot supply a complete practice exam")
    questions = {
        row["id"]: row for row in conn.execute(
            f"SELECT * FROM question_bank WHERE id IN ({','.join('?' * len(chosen))})",
            chosen,
        ).fetchall()
    }
    started = datetime.now(timezone.utc)
    timestamp = started.isoformat()
    expires = (started + timedelta(minutes=DURATION_MINUTES)).isoformat()
    disclosure = (
        f"{len(reused)} of {QUESTION_TARGET} questions were reused from a prior "
        "submitted practice exam."
        if reused else
        f"{QUESTION_TARGET} unseen questions selected from the protected held-out pool."
    )
    cursor = conn.execute(
        "INSERT INTO practice_exam_attempts("
        "exam_id, state, question_target, duration_minutes, started_at, expires_at, "
        "question_ids_json, reused_question_ids_json, selection_disclosure, "
        "created_at, updated_at"
        ") VALUES (?, 'in_progress', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            exam["id"], QUESTION_TARGET, DURATION_MINUTES, timestamp, expires,
            json.dumps(chosen), json.dumps(reused), disclosure, timestamp, timestamp,
        ),
    )
    attempt_id = cursor.lastrowid
    for position, question_id in enumerate(chosen):
        question = questions[question_id]
        conn.execute(
            "INSERT INTO practice_exam_responses("
            "attempt_id, question_id, position, domain_id, objective_id, "
            "mapping_granularity, prompt_snapshot, options_snapshot_json, "
            "correct_answers_snapshot_json, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                attempt_id, question_id, position, question["domain_id"],
                question["objective_id"], question["mapping_granularity"],
                question["prompt"], question["options_json"],
                question["correct_answers_json"], timestamp, timestamp,
            ),
        )
    conn.commit()
    return get_attempt(conn, attempt_id)


def _remaining_seconds(expires_at):
    expires = datetime.fromisoformat(expires_at)
    return max(0, int((expires - datetime.now(timezone.utc)).total_seconds()))


def get_attempt(conn, attempt_id):
    row = conn.execute(
        "SELECT a.*, e.code AS exam_code, e.name AS exam_name "
        "FROM practice_exam_attempts a JOIN exams e ON e.id=a.exam_id "
        "WHERE a.id=?",
        (attempt_id,),
    ).fetchone()
    if not row:
        raise ApiError(404, "practice exam not found")
    attempt = dict(row)
    submitted = attempt["state"] == "submitted"
    responses = []
    for response in conn.execute(
        "SELECT r.*, d.code AS domain_code, d.name AS domain_name, "
        "o.code AS objective_code, q.explanation, q.figure_member, "
        "qsec.stable_id AS figure_section "
        "FROM practice_exam_responses r "
        "LEFT JOIN domains d ON d.id=r.domain_id "
        "LEFT JOIN objectives o ON o.id=r.objective_id "
        "LEFT JOIN question_bank q ON q.id=r.question_id "
        "LEFT JOIN sections qsec ON qsec.id=q.question_section_id "
        "WHERE r.attempt_id=? ORDER BY r.position",
        (attempt_id,),
    ).fetchall():
        item = dict(response)
        item["options"] = _json_list(item.pop("options_snapshot_json"))
        item["figure"] = question_figures.figure_payload(
            item.pop("figure_section", None), item.pop("figure_member", None)
        )
        correct = _json_list(item.pop("correct_answers_snapshot_json"))
        item["submitted_answer"] = (
            _json_list(item.pop("submitted_answer_json"))
            if item["submitted_answer_json"] is not None else []
        )
        item.pop("submitted_answer_json", None)
        explanation = item.pop("explanation", "")
        if submitted:
            item["correct_answers"] = correct
            item["explanation"] = explanation
        else:
            item.pop("is_correct", None)
        responses.append(item)
    attempt["responses"] = responses
    attempt["answers_redacted"] = not submitted
    attempt["answered_count"] = sum(bool(item["submitted_answer"]) for item in responses)
    attempt["remaining_seconds"] = (
        0 if submitted else _remaining_seconds(attempt["expires_at"])
    )
    if submitted:
        attempt["breakdown"] = _breakdown(conn, attempt_id)
    return attempt


def save_answer(conn, attempt_id, question_id, selected):
    attempt = conn.execute(
        "SELECT state FROM practice_exam_attempts WHERE id=?", (attempt_id,)
    ).fetchone()
    if not attempt:
        raise ApiError(404, "practice exam not found")
    if attempt["state"] != "in_progress":
        raise ApiError(409, "practice exam is no longer in progress")
    response = conn.execute(
        "SELECT id, options_snapshot_json FROM practice_exam_responses "
        "WHERE attempt_id=? AND question_id=?",
        (attempt_id, question_id),
    ).fetchone()
    if not response:
        raise ApiError(400, "question is not part of this practice exam")
    options = _json_list(response["options_snapshot_json"])
    if not isinstance(selected, list):
        raise ApiError(400, "selected must be a list")
    if len(set(selected)) != len(selected) or any(
        not isinstance(index, int) or isinstance(index, bool)
        or index < 0 or index >= len(options) for index in selected
    ):
        raise ApiError(400, "selected option indexes are invalid")
    timestamp = now_iso()
    conn.execute(
        "UPDATE practice_exam_responses SET submitted_answer_json=?, updated_at=? "
        "WHERE id=?",
        (json.dumps(sorted(selected)) if selected else None, timestamp, response["id"]),
    )
    conn.execute(
        "UPDATE practice_exam_attempts SET updated_at=? WHERE id=?",
        (timestamp, attempt_id),
    )
    conn.commit()
    answered_count = conn.execute(
        "SELECT COUNT(*) AS n FROM practice_exam_responses "
        "WHERE attempt_id=? AND submitted_answer_json IS NOT NULL",
        (attempt_id,),
    ).fetchone()["n"]
    return {
        "id": attempt_id,
        "question_id": question_id,
        "selected": sorted(selected),
        "answered_count": answered_count,
    }


def submit_attempt(conn, attempt_id):
    attempt = conn.execute(
        "SELECT * FROM practice_exam_attempts WHERE id=?", (attempt_id,)
    ).fetchone()
    if not attempt:
        raise ApiError(404, "practice exam not found")
    if attempt["state"] != "in_progress":
        raise ApiError(409, "practice exam has already ended")
    responses = conn.execute(
        "SELECT id, submitted_answer_json, correct_answers_snapshot_json "
        "FROM practice_exam_responses WHERE attempt_id=?",
        (attempt_id,),
    ).fetchall()
    timestamp = now_iso()
    correct_count = 0
    for response in responses:
        selected = set(_json_list(response["submitted_answer_json"]))
        correct = set(_json_list(response["correct_answers_snapshot_json"]))
        is_correct = bool(selected) and selected == correct
        correct_count += 1 if is_correct else 0
        conn.execute(
            "UPDATE practice_exam_responses SET is_correct=?, updated_at=? WHERE id=?",
            (1 if is_correct else 0, timestamp, response["id"]),
        )
    score = round(correct_count / len(responses) * 100.0, 1)
    band = (
        "strong_signal" if score >= 85
        else "approaching" if score >= 75
        else "review_needed"
    )
    timed_out = _remaining_seconds(attempt["expires_at"]) == 0
    conn.execute(
        "UPDATE practice_exam_attempts SET state='submitted', submitted_at=?, "
        "raw_score_pct=?, readiness_band=?, timed_out=?, updated_at=? WHERE id=?",
        (timestamp, score, band, 1 if timed_out else 0, timestamp, attempt_id),
    )
    conn.commit()
    return get_attempt(conn, attempt_id)


def abandon_attempt(conn, attempt_id):
    row = conn.execute(
        "SELECT state FROM practice_exam_attempts WHERE id=?", (attempt_id,)
    ).fetchone()
    if not row:
        raise ApiError(404, "practice exam not found")
    if row["state"] != "in_progress":
        raise ApiError(409, "only an in-progress practice exam can be abandoned")
    conn.execute(
        "UPDATE practice_exam_attempts SET state='abandoned', updated_at=? WHERE id=?",
        (now_iso(), attempt_id),
    )
    conn.commit()
    return {"id": attempt_id, "state": "abandoned"}


def _breakdown(conn, attempt_id):
    domains = [
        dict(row) for row in conn.execute(
            "SELECT d.code AS domain_code, d.name AS domain_name, "
            "COUNT(*) AS total, SUM(CASE WHEN r.is_correct=1 THEN 1 ELSE 0 END) AS correct "
            "FROM practice_exam_responses r LEFT JOIN domains d ON d.id=r.domain_id "
            "WHERE r.attempt_id=? GROUP BY r.domain_id, d.code, d.name "
            "ORDER BY d.code",
            (attempt_id,),
        ).fetchall()
    ]
    for domain in domains:
        domain["score_pct"] = round(domain["correct"] / domain["total"] * 100.0, 1)
    objectives = [
        dict(row) for row in conn.execute(
            "SELECT o.code AS objective_code, COUNT(*) AS total, "
            "SUM(CASE WHEN r.is_correct=1 THEN 1 ELSE 0 END) AS correct "
            "FROM practice_exam_responses r JOIN objectives o ON o.id=r.objective_id "
            "WHERE r.attempt_id=? AND r.mapping_granularity='objective' "
            "GROUP BY r.objective_id, o.code ORDER BY o.code",
            (attempt_id,),
        ).fetchall()
    ]
    for objective in objectives:
        objective["score_pct"] = round(
            objective["correct"] / objective["total"] * 100.0, 1
        )
    return {
        "domains": domains,
        "objectives": objectives,
        "mapping_note": (
            "Current imported questions are domain-mapped. Objective breakdowns "
            "appear only for explicitly objective-mapped questions."
        ),
    }


def export_attempts(conn, limit=20):
    ids = [
        row["id"] for row in conn.execute(
            "SELECT id FROM practice_exam_attempts ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]
    return [get_attempt(conn, attempt_id) for attempt_id in ids]
