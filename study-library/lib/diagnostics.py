"""Adaptive knowledge-check assessment engine: scope listing, attempt
start/submit/results, and gap-driven remediation bookkeeping.

Scoring rules (see BUILD spec):
  - raw pass threshold: scope.raw_pass_threshold_pct (default 85%)
  - confidence-adjusted credit: correct+high=1.0, correct+medium=0.9,
    correct+low=0.7, incorrect=0 regardless of confidence
  - effective pass threshold: scope.effective_pass_threshold_pct (default 80%)
  - any incorrectly-answered `critical` question fails the attempt outright
  - pass -> provisional_mastery (diagnostic) / mastered_after_remediation
    (retest) / mastery preserved + retention refreshed (retention)
  - fail (any mode) -> needs_remediation, retention_due_at cleared
  - remediation items are created ONLY for incorrect responses or
    correct-but-low-confidence responses; never for correct+high/medium
"""
import json
import random
from datetime import datetime, timedelta, timezone

from lib.api_logic import ApiError
from lib import remediation
from lib import question_figures

CONFIDENCE_CREDIT = {"high": 1.0, "medium": 0.9, "low": 0.7}
VALID_CONFIDENCE = set(CONFIDENCE_CREDIT.keys())
VALID_MODES = {"diagnostic", "retest", "retention"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _row(r):
    return dict(r) if r is not None else None


def _rows(rs):
    return [dict(r) for r in rs]


def _safe_json_list(raw, default=None):
    if default is None:
        default = []
    if not raw:
        return default
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return val
    except Exception:
        pass
    return default


def _map_indexes_to_text(options, indexes):
    if not isinstance(options, list) or not isinstance(indexes, list):
        return []
    result = []
    for idx in indexes:
        if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(options):
            result.append(options[idx])
        else:
            result.append(f"[Invalid index: {idx}]")
    return result



# --- Scopes --------------------------------------------------------------

def list_scopes(conn):
    rows = conn.execute(
        "SELECT s.id, s.slug, s.name, s.scope_type, s.plan_week_id, s.exam_id, s.domain_id, "
        "s.question_target, s.min_valid_questions, s.enabled, s.retention_interval_days, "
        "e.code AS exam_code, d.name AS domain_name, w.week_number, "
        "m.status AS mastery_status, m.retention_due_at, "
        "(SELECT COUNT(*) FROM remediation_items ri WHERE ri.scope_id = s.id AND ri.status = 'open') AS open_gap_count "
        "FROM diagnostic_scopes s "
        "JOIN exams e ON e.id = s.exam_id "
        "LEFT JOIN domains d ON d.id = s.domain_id "
        "LEFT JOIN plan_weeks w ON w.id = s.plan_week_id "
        "LEFT JOIN scope_mastery m ON m.scope_id = s.id "
        "ORDER BY w.week_number, s.id"
    ).fetchall()
    return _rows(rows)


def _get_scope_row(conn, scope_id):
    row = conn.execute("SELECT * FROM diagnostic_scopes WHERE id = ?", (scope_id,)).fetchone()
    if not row:
        raise ApiError(404, "scope not found")
    return row


def _scope_pool_where(scope):
    if scope["scope_type"] == "domain":
        return (
            "exam_id = ? AND domain_id = ? AND active = 1 "
            "AND id NOT IN (SELECT question_id FROM practice_exam_question_pool)",
            (scope["exam_id"], scope["domain_id"]),
        )
    return (
        "exam_id = ? AND active = 1 "
        "AND id NOT IN (SELECT question_id FROM practice_exam_question_pool)",
        (scope["exam_id"],),
    )


def _retest_available(conn, scope_id):
    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM remediation_items WHERE scope_id = ? AND status = 'open'",
        (scope_id,),
    ).fetchone()["n"]
    return open_count == 0


def get_scope(conn, scope_id):
    scope = _get_scope_row(conn, scope_id)
    mastery = conn.execute(
        "SELECT status, retention_due_at, last_attempt_id, best_attempt_id, updated_at "
        "FROM scope_mastery WHERE scope_id = ?", (scope_id,),
    ).fetchone()
    where, params = _scope_pool_where(scope)
    available = conn.execute(f"SELECT COUNT(*) AS n FROM question_bank WHERE {where}", params).fetchone()["n"]
    open_gaps = conn.execute(
        "SELECT ri.id, ri.gap_reason, ri.status, ri.recall_prompt, ri.lab_scaffold, "
        "r.question_id, r.prompt_snapshot "
        "FROM remediation_items ri JOIN diagnostic_responses r ON r.id = ri.response_id "
        "WHERE ri.scope_id = ? ORDER BY ri.created_at DESC",
        (scope_id,),
    ).fetchall()
    recent_attempts = conn.execute(
        "SELECT id, mode, state, started_at, submitted_at, raw_score_pct, effective_score_pct, passed, bucket_result "
        "FROM diagnostic_attempts WHERE scope_id = ? ORDER BY started_at DESC LIMIT 10",
        (scope_id,),
    ).fetchall()
    return {
        **_row(scope),
        "mastery": _row(mastery),
        "available_question_count": available,
        "insufficient_questions": available < scope["min_valid_questions"],
        "remediation_items": _rows(open_gaps),
        "retest_available": _retest_available(conn, scope_id),
        "recent_attempts": _rows(recent_attempts),
    }


# --- Attempt start ---------------------------------------------------------

def _previously_seen_question_ids(conn, scope_id):
    rows = conn.execute(
        "SELECT DISTINCT r.question_id FROM diagnostic_responses r "
        "JOIN diagnostic_attempts a ON a.id = r.attempt_id "
        "WHERE a.scope_id = ? AND a.state = 'submitted'",
        (scope_id,),
    ).fetchall()
    return {r["question_id"] for r in rows}


def start_attempt(conn, scope_id, mode):
    if mode not in VALID_MODES:
        raise ApiError(400, f"mode must be one of {sorted(VALID_MODES)}")
    scope = _get_scope_row(conn, scope_id)
    if not scope["enabled"]:
        raise ApiError(400, "scope is disabled (too few valid questions)")

    existing_inprogress = conn.execute(
        "SELECT id FROM diagnostic_attempts WHERE scope_id = ? AND state = 'in_progress' "
        "ORDER BY started_at DESC LIMIT 1",
        (scope_id,),
    ).fetchone()
    if existing_inprogress:
        raise ApiError(409, "an in-progress attempt already exists for this scope")

    if mode == "retest" and not _retest_available(conn, scope_id):
        raise ApiError(
            409,
            "retest is not available until all open remediation items for this scope are "
            "reviewed; pass override=true explicitly if you want to retest anyway",
        )

    where, params = _scope_pool_where(scope)
    pool = conn.execute(f"SELECT id FROM question_bank WHERE {where}", params).fetchall()
    pool_ids = [r["id"] for r in pool]
    if len(pool_ids) < scope["min_valid_questions"]:
        raise ApiError(400, "scope has fewer than the minimum valid questions available")

    seen = _previously_seen_question_ids(conn, scope_id)
    unseen_ids = [q for q in pool_ids if q not in seen]
    seen_ids_avail = [q for q in pool_ids if q in seen]
    random.shuffle(unseen_ids)
    random.shuffle(seen_ids_avail)

    target = min(scope["question_target"], len(pool_ids))
    chosen = unseen_ids[:target]
    reused = []
    if len(chosen) < target:
        needed = target - len(chosen)
        reused = seen_ids_avail[:needed]
        chosen = chosen + reused

    if reused:
        disclosure = (
            f"Pool exhausted for unseen questions: {len(reused)} of {len(chosen)} questions "
            f"in this attempt were seen in a prior attempt for this scope (reuse disclosed)."
        )
    elif len(chosen) < scope["question_target"]:
        disclosure = (
            f"Only {len(chosen)} question(s) were available for this scope "
            f"(target is {scope['question_target']}); all available were used."
        )
    else:
        disclosure = f"{len(chosen)} questions sampled without repeats from the available pool."

    questions = conn.execute(
        f"SELECT * FROM question_bank WHERE id IN ({','.join('?' * len(chosen))})", chosen,
    ).fetchall()
    q_by_id = {q["id"]: q for q in questions}

    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO diagnostic_attempts(scope_id, mode, state, started_at, question_ids_json, "
        "reused_question_ids_json, selection_disclosure, created_at, updated_at) "
        "VALUES (?, ?, 'in_progress', ?, ?, ?, ?, ?, ?)",
        (scope_id, mode, ts, json.dumps(chosen), json.dumps(reused), disclosure, ts, ts),
    )
    attempt_id = cur.lastrowid
    for position, qid in enumerate(chosen):
        q = q_by_id[qid]
        conn.execute(
            "INSERT INTO diagnostic_responses(attempt_id, question_id, position, prompt_snapshot, "
            "options_snapshot_json, correct_answers_snapshot_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (attempt_id, qid, position, q["prompt"], q["options_json"], q["correct_answers_json"], ts, ts),
        )
    conn.commit()
    return get_attempt(conn, attempt_id)


# --- Attempt read (with redaction) ----------------------------------------


def get_attempt(conn, attempt_id):
    attempt = conn.execute("SELECT * FROM diagnostic_attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt:
        raise ApiError(404, "attempt not found")
    attempt = dict(attempt)
    responses = conn.execute(
        "SELECT r.id, r.question_id, r.position, r.prompt_snapshot, r.options_snapshot_json, "
        "r.correct_answers_snapshot_json, r.submitted_answer_json, r.confidence, r.is_correct, r.effective_score, "
        "qb.explanation, qb.figure_member, qsec.stable_id AS figure_section "
        "FROM diagnostic_responses r "
        "LEFT JOIN question_bank qb ON qb.id = r.question_id "
        "LEFT JOIN sections qsec ON qsec.id = qb.question_section_id "
        "WHERE r.attempt_id = ? ORDER BY r.position",
        (attempt_id,),
    ).fetchall()
    redact = attempt["state"] != "submitted"
    out_responses = []
    for r in responses:
        d = dict(r)
        d["options"] = _safe_json_list(d.pop("options_snapshot_json"))
        d["figure"] = question_figures.figure_payload(d.pop("figure_section", None), d.pop("figure_member", None))
        correct = _safe_json_list(d.pop("correct_answers_snapshot_json"))
        submitted_raw = d.pop("submitted_answer_json")
        d["submitted_answer"] = _safe_json_list(submitted_raw, default=None) if submitted_raw is not None else None
        qb_explanation = d.pop("explanation", None)
        if redact:
            d["is_correct"] = None
            d["effective_score"] = None
        else:
            d["correct_answers"] = correct
            d["submitted_answer_text"] = _map_indexes_to_text(d["options"], d["submitted_answer"] or [])
            d["correct_answer_text"] = _map_indexes_to_text(d["options"], correct)
            d["explanation"] = qb_explanation or ""
            d["practice_book_explanation"] = qb_explanation or ""
        out_responses.append(d)
    attempt["responses"] = out_responses
    attempt["answers_redacted"] = redact
    return attempt


# --- Submission ------------------------------------------------------------

def _validate_submission_shape(responses, option_counts_by_qid):
    expected_question_ids = list(option_counts_by_qid.keys())
    if not isinstance(responses, list) or len(responses) != len(expected_question_ids):
        raise ApiError(400, "responses must cover exactly every question in the attempt, once each")
    by_qid = {}
    for entry in responses:
        if not isinstance(entry, dict):
            raise ApiError(400, "each response must be an object")
        qid = entry.get("question_id")
        if qid not in option_counts_by_qid:
            raise ApiError(400, f"unknown question_id {qid} for this attempt")
        if qid in by_qid:
            raise ApiError(400, f"duplicate response for question_id {qid}")
        num_options = option_counts_by_qid[qid]
        selected = entry.get("selected")
        if not isinstance(selected, list) or not selected or len(selected) > num_options:
            raise ApiError(400, "selected must be a non-empty list of option indexes")
        if any((not isinstance(i, int)) or i < 0 or i >= num_options for i in selected):
            raise ApiError(400, "selected option indexes out of range")
        if len(set(selected)) != len(selected):
            raise ApiError(400, "selected must not contain duplicate indexes")
        confidence = entry.get("confidence")
        if confidence not in VALID_CONFIDENCE:
            raise ApiError(400, f"confidence must be one of {sorted(VALID_CONFIDENCE)}")
        by_qid[qid] = {"selected": selected, "confidence": confidence}
    if set(by_qid) != set(expected_question_ids):
        raise ApiError(400, "responses must cover exactly every question in the attempt")
    return by_qid


def submit_attempt(conn, attempt_id, responses):
    attempt = conn.execute("SELECT * FROM diagnostic_attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt:
        raise ApiError(404, "attempt not found")
    if attempt["state"] != "in_progress":
        raise ApiError(409, "attempt has already been submitted (one submission only)")

    resp_rows = conn.execute(
        "SELECT id, question_id, correct_answers_snapshot_json, options_snapshot_json FROM diagnostic_responses "
        "WHERE attempt_id = ? ORDER BY position", (attempt_id,),
    ).fetchall()
    option_counts_by_qid = {r["question_id"]: len(json.loads(r["options_snapshot_json"])) for r in resp_rows}
    by_qid = _validate_submission_shape(responses, option_counts_by_qid)

    scope = _get_scope_row(conn, attempt["scope_id"])
    ts = now_iso()

    try:
        total = len(resp_rows)
        raw_correct = 0
        effective_sum = 0.0
        critical_failed = False
        graded = []  # (response_row, question, selected, confidence, is_correct, effective)

        qids = list(option_counts_by_qid.keys())
        question_rows = {
            q["id"]: q for q in conn.execute(
                f"SELECT * FROM question_bank WHERE id IN ({','.join('?' * total)})",
                qids,
            ).fetchall()
        }

        for r in resp_rows:
            ans = by_qid[r["question_id"]]
            correct_set = set(json.loads(r["correct_answers_snapshot_json"]))
            is_correct = set(ans["selected"]) == correct_set
            if is_correct:
                raw_correct += 1
                effective = CONFIDENCE_CREDIT[ans["confidence"]]
            else:
                effective = 0.0
            effective_sum += effective
            q = question_rows[r["question_id"]]
            if q["critical"] and not is_correct:
                critical_failed = True
            graded.append((r, q, ans, is_correct, effective))

        raw_pct = round(raw_correct / total * 100.0, 1)
        effective_pct = round(effective_sum / total * 100.0, 1)
        passed = (
            raw_pct >= scope["raw_pass_threshold_pct"]
            and effective_pct >= scope["effective_pass_threshold_pct"]
            and not critical_failed
        )

        for r, q, ans, is_correct, effective in graded:
            conn.execute(
                "UPDATE diagnostic_responses SET submitted_answer_json = ?, confidence = ?, "
                "is_correct = ?, effective_score = ?, updated_at = ? WHERE id = ?",
                (json.dumps(sorted(ans["selected"])), ans["confidence"], 1 if is_correct else 0,
                 effective, ts, r["id"]),
            )

        mode = attempt["mode"]
        if passed:
            bucket = {"diagnostic": "provisional_mastery", "retest": "mastered_after_remediation",
                      "retention": None}[mode]
        else:
            bucket = "needs_remediation"

        conn.execute(
            "UPDATE diagnostic_attempts SET state = 'submitted', submitted_at = ?, raw_score_pct = ?, "
            "effective_score_pct = ?, passed = ?, bucket_result = ?, updated_at = ? WHERE id = ?",
            (ts, raw_pct, effective_pct, 1 if passed else 0, bucket, ts, attempt_id),
        )

        _update_scope_mastery(conn, scope, attempt_id, mode, passed, ts)

        if not passed:
            _create_remediation_for_gaps(conn, attempt_id, scope, graded, ts)
        elif mode in ("diagnostic", "retest") and scope["plan_week_id"]:
            _exempt_remaining_week_tasks(conn, scope, attempt_id, ts)

        conn.commit()
    except ApiError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise

    return get_attempt_results(conn, attempt_id)


def _update_scope_mastery(conn, scope, attempt_id, mode, passed, ts):
    row = conn.execute("SELECT * FROM scope_mastery WHERE scope_id = ?", (scope["id"],)).fetchone()
    if passed:
        if mode == "retention":
            status = row["status"] if row and row["status"] != "unassessed" else "provisional_mastery"
        else:
            status = "provisional_mastery" if mode == "diagnostic" else "mastered_after_remediation"
        due = (datetime.now(timezone.utc) + timedelta(days=scope["retention_interval_days"])).isoformat()
    else:
        status = "needs_remediation"
        due = None
    conn.execute(
        "INSERT INTO scope_mastery(scope_id, status, last_attempt_id, best_attempt_id, retention_due_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(scope_id) DO UPDATE SET status = excluded.status, last_attempt_id = excluded.last_attempt_id, "
        "  best_attempt_id = CASE WHEN excluded.status IN ('provisional_mastery','mastered_after_remediation') "
        "    THEN excluded.last_attempt_id ELSE scope_mastery.best_attempt_id END, "
        "  retention_due_at = excluded.retention_due_at, updated_at = excluded.updated_at",
        (scope["id"], status, attempt_id, attempt_id if passed else None, due, ts),
    )


def _create_remediation_for_gaps(conn, attempt_id, scope, graded, ts):
    domain_name = None
    if scope["domain_id"]:
        d = conn.execute("SELECT name FROM domains WHERE id = ?", (scope["domain_id"],)).fetchone()
        domain_name = d["name"] if d else "this domain"
    else:
        domain_name = "this exam"

    for r, q, ans, is_correct, effective in graded:
        gap_reason = None
        if not is_correct:
            gap_reason = "incorrect"
        elif ans["confidence"] == "low":
            gap_reason = "correct_low_confidence"
        if not gap_reason:
            continue

        options = json.loads(q["options_json"])
        correct_indexes = json.loads(q["correct_answers_json"])
        recall_prompt = remediation.build_recall_prompt(q["prompt"], options, correct_indexes)
        lab_scaffold = remediation.build_lab_scaffold(domain_name)

        conn.execute(
            "INSERT INTO remediation_items(attempt_id, response_id, scope_id, gap_reason, status, "
            "recall_prompt, lab_scaffold, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?) "
            "ON CONFLICT(response_id) DO UPDATE SET gap_reason = excluded.gap_reason, "
            "  status = 'open', recall_prompt = excluded.recall_prompt, lab_scaffold = excluded.lab_scaffold, "
            "  reviewed_at = NULL, updated_at = excluded.updated_at",
            (attempt_id, r["id"], scope["id"], gap_reason, recall_prompt, lab_scaffold, ts, ts),
        )
        item_id = conn.execute(
            "SELECT id FROM remediation_items WHERE response_id = ?", (r["id"],)
        ).fetchone()["id"]

        conn.execute("DELETE FROM remediation_readings WHERE remediation_item_id = ?", (item_id,))
        correct_text = "; ".join(
            options[i] for i in correct_indexes if 0 <= i < len(options)
        )
        query_text = q["explanation"] + " " + q["prompt"]
        readings = remediation.find_relevant_readings(
            conn,
            scope["exam_id"],
            scope["domain_id"],
            query_text,
            priority_text=correct_text,
        )
        for rank, reading in enumerate(readings, start=1):
            conn.execute(
                "INSERT INTO remediation_readings(remediation_item_id, rank, book_slug, book_title, "
                "section_stable_id, section_title, snippet, content_hash, retrieval_basis, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, rank, reading["book_slug"], reading["book_title"], reading["section_stable_id"],
                 reading["section_title"], reading["snippet"], reading["content_hash"],
                 reading["retrieval_basis"], ts),
            )


def _exempt_remaining_week_tasks(conn, scope, attempt_id, ts):
    tasks = conn.execute(
        "SELECT id FROM plan_tasks WHERE week_id = ? AND completed = 0", (scope["plan_week_id"],),
    ).fetchall()
    for t in tasks:
        conn.execute(
            "INSERT INTO plan_task_exemptions(plan_task_id, scope_id, attempt_id, exempted_at, reason) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(plan_task_id) DO UPDATE SET scope_id = excluded.scope_id, "
            "  attempt_id = excluded.attempt_id, exempted_at = excluded.exempted_at, reason = excluded.reason",
            (t["id"], scope["id"], attempt_id, ts,
             f"exempted by passing diagnostic scope '{scope['slug']}' (attempt {attempt_id}); "
             f"task was not actually completed"),
        )


def get_attempt_results(conn, attempt_id):
    attempt = get_attempt(conn, attempt_id)
    if attempt["state"] == "in_progress":
        raise ApiError(409, "attempt has not been submitted yet")
    gaps = conn.execute(
        "SELECT ri.id AS remediation_id, ri.gap_reason, ri.status, ri.recall_prompt, ri.lab_scaffold, "
        "r.question_id, r.prompt_snapshot, r.submitted_answer_json, r.correct_answers_snapshot_json, "
        "r.options_snapshot_json, qb.explanation, qb.figure_member, qsec.stable_id AS figure_section "
        "FROM remediation_items ri "
        "JOIN diagnostic_responses r ON r.id = ri.response_id "
        "LEFT JOIN question_bank qb ON qb.id = r.question_id "
        "LEFT JOIN sections qsec ON qsec.id = qb.question_section_id "
        "WHERE ri.attempt_id = ? ORDER BY ri.id", (attempt_id,),
    ).fetchall()
    gap_list = []
    for g in gaps:
        d = dict(g)
        d["options"] = _safe_json_list(d.pop("options_snapshot_json"))
        d["figure"] = question_figures.figure_payload(d.pop("figure_section", None), d.pop("figure_member", None))
        d["correct_answers"] = _safe_json_list(d.pop("correct_answers_snapshot_json"))
        d["submitted_answer"] = _safe_json_list(d.pop("submitted_answer_json") or "[]")
        d["submitted_answer_text"] = _map_indexes_to_text(d["options"], d["submitted_answer"])
        d["correct_answer_text"] = _map_indexes_to_text(d["options"], d["correct_answers"])
        qb_explanation = d.get("explanation") or ""
        d["explanation"] = qb_explanation
        d["practice_book_explanation"] = qb_explanation
        readings = conn.execute(
            "SELECT rank, book_slug, book_title, section_stable_id, section_title, snippet, "
            "content_hash, retrieval_basis FROM remediation_readings WHERE remediation_item_id = ? ORDER BY rank",
            (d["remediation_id"],),
        ).fetchall()
        d["readings"] = _rows(readings)
        gap_list.append(d)
    attempt["gaps"] = gap_list
    attempt["reused_question_ids"] = _safe_json_list(attempt.get("reused_question_ids_json") or "[]")
    return attempt


# --- Remediation review -----------------------------------------------------

def mark_reviewed(conn, remediation_item_id):
    row = conn.execute("SELECT id FROM remediation_items WHERE id = ?", (remediation_item_id,)).fetchone()
    if not row:
        raise ApiError(404, "remediation item not found")
    ts = now_iso()
    conn.execute(
        "UPDATE remediation_items SET status = 'reviewed', reviewed_at = ?, updated_at = ? WHERE id = ?",
        (ts, ts, remediation_item_id),
    )
    conn.commit()
    return _row(conn.execute("SELECT * FROM remediation_items WHERE id = ?", (remediation_item_id,)).fetchone())


def abandon_attempt(conn, attempt_id):
    attempt = conn.execute(
        "SELECT * FROM diagnostic_attempts WHERE id = ?", (attempt_id,)
    ).fetchone()
    if not attempt:
        raise ApiError(404, "attempt not found")
    if attempt["state"] == "submitted":
        raise ApiError(409, "a submitted attempt cannot be abandoned")
    if attempt["state"] == "abandoned":
        return get_attempt(conn, attempt_id)
    ts = now_iso()
    conn.execute(
        "UPDATE diagnostic_attempts SET state = 'abandoned', updated_at = ? WHERE id = ?",
        (ts, attempt_id),
    )
    conn.commit()
    return get_attempt(conn, attempt_id)


def refresh_remediation_readings(conn, attempt_id=None, open_only=True):
    """Rebuild stored citations with the current deterministic retriever."""
    where = []
    params = []
    if attempt_id is not None:
        where.append("ri.attempt_id = ?")
        params.append(attempt_id)
    if open_only:
        where.append("ri.status = 'open'")
    predicate = " WHERE " + " AND ".join(where) if where else ""
    rows = conn.execute(
        "SELECT ri.id AS remediation_id, s.exam_id, s.domain_id, "
        "r.prompt_snapshot, r.options_snapshot_json, "
        "r.correct_answers_snapshot_json, COALESCE(q.explanation, '') AS explanation "
        "FROM remediation_items ri "
        "JOIN diagnostic_scopes s ON s.id = ri.scope_id "
        "JOIN diagnostic_responses r ON r.id = ri.response_id "
        "LEFT JOIN question_bank q ON q.id = r.question_id"
        + predicate + " ORDER BY ri.id",
        params,
    ).fetchall()
    ts = now_iso()
    reading_count = 0
    for row in rows:
        options = _safe_json_list(row["options_snapshot_json"])
        correct_indexes = _safe_json_list(row["correct_answers_snapshot_json"])
        correct_text = "; ".join(
            options[i] for i in correct_indexes if 0 <= i < len(options)
        )
        readings = remediation.find_relevant_readings(
            conn,
            row["exam_id"],
            row["domain_id"],
            row["explanation"] + " " + row["prompt_snapshot"],
            priority_text=correct_text,
        )
        conn.execute(
            "DELETE FROM remediation_readings WHERE remediation_item_id = ?",
            (row["remediation_id"],),
        )
        for rank, reading in enumerate(readings, start=1):
            conn.execute(
                "INSERT INTO remediation_readings(remediation_item_id, rank, book_slug, "
                "book_title, section_stable_id, section_title, snippet, content_hash, "
                "retrieval_basis, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["remediation_id"],
                    rank,
                    reading["book_slug"],
                    reading["book_title"],
                    reading["section_stable_id"],
                    reading["section_title"],
                    reading["snippet"],
                    reading["content_hash"],
                    reading["retrieval_basis"],
                    ts,
                ),
            )
            reading_count += 1
    conn.commit()
    return {"items_refreshed": len(rows), "readings_created": reading_count}
