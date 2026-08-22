"""Evidence-separated learning analytics without a fabricated mastery score."""

from collections import Counter
from datetime import datetime, timedelta, timezone

from lib import study_clock
from lib.api_logic import ApiError, get_study_next, now_iso


def _bounded_days(value):
    try:
        days = int(value or 30)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "days must be an integer") from exc
    if not 7 <= days <= 90:
        raise ApiError(400, "days must be between 7 and 90")
    return days


def _date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return study_clock.local_date(parsed.isoformat())


def _count(conn, sql, params=()):
    return int(conn.execute(sql, params).fetchone()["n"] or 0)


def _score_summary(rows):
    scores = [float(row["score_pct"]) for row in rows if row["score_pct"] is not None]
    return {
        "submitted": len(rows),
        "latest_score_pct": scores[0] if scores else None,
        "best_score_pct": max(scores) if scores else None,
        "recent": [dict(row) for row in rows[:8]],
    }


def _action_href(action):
    if not action:
        return "/study"
    kind = action.get("type")
    if kind == "objective_retention":
        return f"/study/review/{action['objective_id']}"
    if kind == "diagnostic":
        return f"/study/check/{action['scope_id']}?mode={action.get('mode', 'diagnostic')}"
    if kind == "scope_detail":
        return f"/study/remediate/{action['scope_id']}"
    if kind == "objective_lesson":
        return f"/learn/{action['objective_id']}"
    return "/study"


def _next_action(conn):
    active_session = conn.execute(
        "SELECT task_title FROM guided_study_sessions WHERE status='active' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if active_session:
        return {"kind": "active_session", "title": "Continue today’s study session",
                "reason": active_session["task_title"], "href": "/session"}
    active_exam = conn.execute(
        "SELECT a.id, e.code FROM practice_exam_attempts a JOIN exams e ON e.id=a.exam_id "
        "WHERE a.state='in_progress' ORDER BY a.started_at DESC LIMIT 1"
    ).fetchone()
    if active_exam:
        return {
            "kind": "active_practice_exam",
            "title": f"Continue the {active_exam['code']} practice exam",
            "reason": "Finish the timed attempt already in progress before starting something new.",
            "href": f"/practice/{active_exam['id']}",
        }
    queue = get_study_next(conn, limit=1)
    if queue["primary"]:
        item = queue["primary"]
        return {"kind": item["kind"], "title": item["title"], "reason": item["reason"],
                "href": _action_href(item.get("action"))}
    active_lab = conn.execute(
        "SELECT title FROM hands_on_labs WHERE archived=0 AND status='in_progress' "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    if active_lab:
        return {"kind": "active_lab", "title": "Continue your hands-on lab",
                "reason": active_lab["title"], "href": "/labs"}
    return {"kind": "study", "title": "Choose the next study activity",
            "reason": "There is no overdue review or unfinished assessment.", "href": "/study"}


def get_analytics(conn, days=30):
    days = _bounded_days(days)
    today = study_clock.today()
    start = today - timedelta(days=days - 1)
    buckets = {
        (start + timedelta(days=i)).isoformat(): {
            "date": (start + timedelta(days=i)).isoformat(), "study_minutes": 0,
            "learning_events": 0, "assessments": 0, "retention_reviews": 0,
            "annotations": 0, "lab_completions": 0,
        } for i in range(days)
    }

    def add(table, timestamp, metric, value_sql="1", where=""):
        for row in conn.execute(
            f"SELECT {timestamp} AS occurred_at, {value_sql} AS value FROM {table} {where}"
        ).fetchall():
            day = _date(row["occurred_at"])
            key = day.isoformat() if day else ""
            if key in buckets:
                buckets[key][metric] += int(row["value"] or 0)

    add("study_sessions", "occurred_at", "study_minutes", "duration_minutes")
    add("learning_events", "occurred_at", "learning_events")
    add("diagnostic_attempts", "submitted_at", "assessments", where="WHERE state='submitted'")
    add("practice_exam_attempts", "submitted_at", "assessments", where="WHERE state='submitted'")
    add("objective_retention_reviews", "occurred_at", "retention_reviews")
    add("study_annotations", "created_at", "annotations", where="WHERE archived=0")
    add("hands_on_labs", "completed_at", "lab_completions",
        where="WHERE archived=0 AND status='completed'")

    diagnostic_rows = conn.execute(
        "SELECT a.id, e.code AS exam_code, s.name AS scope_name, a.mode, "
        "a.submitted_at AS occurred_at, a.raw_score_pct AS score_pct, a.passed "
        "FROM diagnostic_attempts a JOIN diagnostic_scopes s ON s.id=a.scope_id "
        "JOIN exams e ON e.id=s.exam_id WHERE a.state='submitted' "
        "ORDER BY a.submitted_at DESC"
    ).fetchall()
    exam_rows = conn.execute(
        "SELECT a.id, e.code AS exam_code, a.submitted_at AS occurred_at, "
        "a.raw_score_pct AS score_pct, a.readiness_band, a.timed_out "
        "FROM practice_exam_attempts a JOIN exams e ON e.id=a.exam_id "
        "WHERE a.state='submitted' ORDER BY a.submitted_at DESC"
    ).fetchall()
    latest_exam = exam_rows[0]["id"] if exam_rows else None
    exam_domains = []
    if latest_exam:
        exam_domains = [dict(row) for row in conn.execute(
            "SELECT d.code AS domain_code, d.name AS domain_name, COUNT(*) AS total, "
            "SUM(CASE WHEN r.is_correct=1 THEN 1 ELSE 0 END) AS correct "
            "FROM practice_exam_responses r LEFT JOIN domains d ON d.id=r.domain_id "
            "WHERE r.attempt_id=? GROUP BY r.domain_id, d.code, d.name ORDER BY d.code",
            (latest_exam,),
        ).fetchall()]
        for row in exam_domains:
            row["score_pct"] = round(row["correct"] / row["total"] * 100.0, 1)

    events = Counter({r["event_type"]: r["n"] for r in conn.execute(
        "SELECT event_type, COUNT(*) AS n FROM learning_events GROUP BY event_type"
    ).fetchall()})
    notes = Counter({r["kind"]: r["n"] for r in conn.execute(
        "SELECT kind, COUNT(*) AS n FROM study_annotations WHERE archived=0 GROUP BY kind"
    ).fetchall()})
    labs = Counter({r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM hands_on_labs WHERE archived=0 GROUP BY status"
    ).fetchall()})
    ratings = Counter({r["rating"]: r["n"] for r in conn.execute(
        "SELECT rating, COUNT(*) AS n FROM objective_retention_reviews GROUP BY rating"
    ).fetchall()})
    queue = get_study_next(conn, limit=24)
    now = now_iso()
    objectives_started = _count(
        conn, "SELECT COUNT(DISTINCT objective_id) AS n FROM learning_events"
    )
    unaided = _count(
        conn, "SELECT COUNT(*) AS n FROM hands_on_labs "
        "WHERE archived=0 AND status='completed' AND completion_level='unaided'"
    )
    return {
        "generated_at": now, "window_days": days,
        "current_state": {
            "open_gaps": queue["counts"]["open_gaps"],
            "retention_due": queue["counts"]["retention_due"] + queue["counts"]["objective_retention_due"],
            "lessons_started": objectives_started,
            "lessons_completed": _count(
                conn, "SELECT COUNT(DISTINCT objective_id) AS n FROM learning_events "
                "WHERE event_type='lesson_completed'"),
            "annotations": sum(notes.values()), "labs_planned": labs["planned"],
            "labs_in_progress": labs["in_progress"], "labs_completed": labs["completed"],
            "labs_unaided": unaided, "diagnostic_attempts": len(diagnostic_rows),
            "full_exam_attempts": len(exam_rows),
        },
        "assessment": {
            "diagnostic": _score_summary(diagnostic_rows),
            "full_exams": {
                **_score_summary(exam_rows), "latest_domain_breakdown": exam_domains,
                "mapping_note": "Full-exam domain results stay at their governed mapping level; Waypoint does not infer objective mastery from domain-mapped questions.",
            },
        },
        "learning": {
            "objectives_started": objectives_started, "objective_opened": events["objective_opened"],
            "readings_opened": events["reading_opened"], "lessons_completed": events["lesson_completed"],
            "recall_completed": events["recall_completed"], "coach_uses": events["coach_used"],
        },
        "retention": {
            "scheduled": _count(conn, "SELECT COUNT(*) AS n FROM objective_retention_state"),
            "due": _count(conn, "SELECT COUNT(*) AS n FROM objective_retention_state WHERE due_at <= ?", (now,)),
            "reviews": sum(ratings.values()),
            "ratings": {name: ratings[name] for name in ("again", "hard", "good", "easy")},
        },
        "notebook": {
            "total": sum(notes.values()), "highlights": notes["highlight"], "notes": notes["note"],
            "bookmarks": notes["bookmark"],
            "objectives_with_annotations": _count(
                conn, "SELECT COUNT(DISTINCT objective_id) AS n FROM study_annotations WHERE archived=0"),
        },
        "labs": {"total": sum(labs.values()), "planned": labs["planned"],
                 "in_progress": labs["in_progress"], "completed": labs["completed"], "unaided": unaided},
        "timeline": list(buckets.values()), "next_action": _next_action(conn),
        "evidence_note": "Each lane reports only the evidence it records. Activity is not mastery, notes are not recall, and practice scores are not official exam scores.",
        "no_composite_note": "Waypoint intentionally does not calculate one universal mastery or readiness score.",
    }
