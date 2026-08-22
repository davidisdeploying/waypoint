"""Seed the default 12-week A+ study plan scaffold (6 weeks Core 1, 6 Core 2).

This is a practical scaffold, not a claim of guaranteed exam readiness or an
official CompTIA curriculum. Domain groupings come from the review-guide
chapter structure ingested by ingest.py. Seeding is idempotent: re-running
upserts the plan/week/task rows by their natural keys and does not duplicate
task rows on a re-run of an already-seeded plan.
"""
from datetime import datetime, timezone

PLAN_SLUG = "aplus-12-week"
PLAN_NAME = "A+ 12-Week Study Plan (Core 1 then Core 2)"
PLAN_DESCRIPTION = (
    "A practical relative-week scaffold covering both A+ exams, Core 1 first "
    "then Core 2. Weeks are relative (Week 1, Week 2, ...), not tied to a "
    "committed calendar date. This is a study aid, not a guarantee of readiness."
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _get_exam_id(conn, code):
    row = conn.execute("SELECT id FROM exams WHERE code = ?", (code,)).fetchone()
    return row["id"] if row else None


def _get_domains_for_exam(conn, exam_id):
    rows = conn.execute(
        "SELECT id, code, name FROM domains WHERE exam_id = ? ORDER BY CAST(code AS INTEGER)",
        (exam_id,),
    ).fetchall()
    return rows


def _find_reading_section(conn, exam_code, domain_name):
    """Best-effort pointer into the ingested corpus for a week's reading task."""
    row = conn.execute(
        "SELECT s.id, s.stable_id, s.title, b.slug as book_slug FROM sections s "
        "JOIN books b ON b.id = s.book_id "
        "WHERE b.slug = 'aplus-review-guide' AND s.title LIKE ? "
        "ORDER BY s.position LIMIT 1",
        (f"%{domain_name}%",),
    ).fetchone()
    return row


def _upsert_week(conn, plan_id, week_number, exam_id, title, focus, goals):
    ts = now_iso()
    conn.execute(
        "INSERT INTO plan_weeks(plan_id, week_number, exam_id, title, focus, goals_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(plan_id, week_number) DO UPDATE SET "
        "  exam_id=excluded.exam_id, title=excluded.title, focus=excluded.focus, "
        "  goals_json=excluded.goals_json, updated_at=excluded.updated_at",
        (plan_id, week_number, exam_id, title, focus, goals, ts, ts),
    )
    return conn.execute(
        "SELECT id FROM plan_weeks WHERE plan_id = ? AND week_number = ?", (plan_id, week_number)
    ).fetchone()["id"]


def _seed_week_tasks(conn, week_id, exam_code, exam_label, focus_label, reading_section_id):
    """Idempotent: only inserts the default task set if the week has none yet,
    so a user's manually-added tasks or edits survive a re-ingest."""
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM plan_tasks WHERE week_id = ?", (week_id,)
    ).fetchone()["n"]
    if existing:
        return 0
    ts = now_iso()
    tasks = [
        (
            "reading", f"Read & search: {focus_label}",
            f"Read the {focus_label} material and use Search (filtered to {exam_label}) "
            f"to cross-reference it across the three ingested books.",
            reading_section_id, None,
        ),
        (
            "lab", f"Hands-on: {focus_label}",
            f"Do a hands-on task related to {focus_label} (e.g. inspect/configure the "
            f"relevant hardware or settings on a real or virtual machine). Scaffold only — "
            f"fill in a concrete lab once you scope one.",
            None, None,
        ),
        (
            "recall", f"Active recall: {focus_label}",
            f"Without notes, write out the key objective-level facts for {focus_label} "
            f"from memory, then check them against the Objectives view.",
            None, None,
        ),
        (
            "practice", f"Practice checkpoint: {focus_label}",
            f"Log a practice attempt for {exam_label} covering {focus_label} in the "
            f"Practice view once you've done one.",
            None, None,
        ),
    ]
    for i, (ttype, title, desc, section_id, objective_id) in enumerate(tasks):
        conn.execute(
            "INSERT INTO plan_tasks(week_id, position, type, title, description, "
            "related_section_id, related_objective_id, completed, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (week_id, i, ttype, title, desc, section_id, objective_id, ts, ts),
        )
    return len(tasks)


def seed_plan(conn):
    ts = now_iso()
    cert_row = conn.execute("SELECT id FROM certifications WHERE code = 'aplus'").fetchone()
    if not cert_row:
        raise RuntimeError("certifications must be seeded before the study plan")
    cert_id = cert_row["id"]

    conn.execute(
        "INSERT INTO study_plans(certification_id, slug, name, description, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(slug) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "updated_at=excluded.updated_at",
        (cert_id, PLAN_SLUG, PLAN_NAME, PLAN_DESCRIPTION, ts, ts),
    )
    plan_id = conn.execute("SELECT id FROM study_plans WHERE slug = ?", (PLAN_SLUG,)).fetchone()["id"]

    core1_id = _get_exam_id(conn, "220-1201")
    core2_id = _get_exam_id(conn, "220-1202")

    week_number = 1
    tasks_created = 0
    weeks_created = 0
    for exam_id, exam_code, exam_label, base_week in (
        (core1_id, "220-1201", "Core 1 (220-1201)", 0),
        (core2_id, "220-1202", "Core 2 (220-1202)", 6),
    ):
        if not exam_id:
            continue
        domains = list(_get_domains_for_exam(conn, exam_id))
        review_week_num = base_week + 6
        slots = review_week_num - 1 - base_week  # weeks available before the review week
        seen_domain_ids = set()
        for slot in range(slots):
            if not domains:
                break
            dom = domains[min(slot * len(domains) // slots, len(domains) - 1)]
            wn = base_week + slot + 1
            repeat = dom["id"] in seen_domain_ids
            seen_domain_ids.add(dom["id"])
            focus_label = f"Domain {dom['code']}: {dom['name']}"
            if repeat:
                focus_label += " (continued)"
            goals = (
                f'["Understand the core concepts of {dom["name"]}",'
                f'"Identify {exam_label} objectives under domain {dom["code"]}",'
                f'"Complete the week\'s reading, lab, recall, and practice tasks"]'
            )
            week_id = _upsert_week(
                conn, plan_id, wn, exam_id,
                f"Week {wn}: {focus_label}", focus_label, goals,
            )
            weeks_created += 1
            section = _find_reading_section(conn, exam_code, dom["name"])
            tasks_created += _seed_week_tasks(
                conn, week_id, exam_code, exam_label, focus_label,
                section["id"] if section else None,
            )
        # Final review/checkpoint week for this exam.
        wn = review_week_num
        focus_label = f"{exam_label} review & practice checkpoint"
        goals = (
            f'["Revisit weak objectives from earlier weeks",'
            f'"Take a full-length {exam_label} practice set",'
            f'"Review the Objectives coverage matrix for gaps"]'
        )
        week_id = _upsert_week(
            conn, plan_id, wn, exam_id, f"Week {wn}: {focus_label}", focus_label, goals,
        )
        weeks_created += 1
        tasks_created += _seed_week_tasks(conn, week_id, exam_code, exam_label, focus_label, None)

    conn.commit()
    return {"plan_id": plan_id, "weeks": weeks_created, "tasks": tasks_created}
