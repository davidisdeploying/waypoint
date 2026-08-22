"""Deterministic importer for the CompTIA A+ practice-test question bank.

Parses the already-ingested `aplus-practice-tests` book sections (no direct
filesystem re-read; the section rows written by ingest.ingest_book are the
source of truth here) into `question_bank` rows, and seeds one
`diagnostic_scopes` row per domain-focused curriculum week (plus one
exam-wide composite scope per review/checkpoint week).

Parsing invariants below were verified empirically against the full corpus
(see the recon that produced this module) before being hard-coded:

  - Question chapters are titled "Chapter N" or "Chapter N (Part X of Y)"
    (no colon). Explanation chapters are titled "Chapter N: <Domain Name>"
    (colon-separated), optionally with the same "(Part X of Y)" suffix.
  - Every question in every chapter has EXACTLY 4 numbered options (1-4,
    resetting per question) -- validated with zero structural anomalies
    across all 1,379 questions in chapters 1-9. This is what makes stem vs.
    option classification unambiguous without any punctuation heuristic.
  - Explanation entries are "N. <LETTER(, LETTER)*>. <prose>" where N is the
    1-based question number *within that chapter* and LETTER in A-D maps to
    a 0-based option index (A=0 .. D=3). A handful of entries (figure-
    dependent "what's shown here" questions) have no letter grade at all --
    those are excluded (unparseable_answer_no_letter).
  - Answer paragraphs are matched by scanning forward for the next expected
    sequential number rather than a fixed per-paragraph offset, so short
    embedded numbered lists inside an explanation's prose (e.g. a numbered
    how-to list) can never be mistaken for a later question's answer: their
    numbers are always smaller than the number currently expected.

This module owns no filesystem paths; it reads the `sections` rows the
regular ingest already wrote for slug 'aplus-practice-tests'.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from lib import question_figures

PRACTICE_BOOK_SLUG = "aplus-practice-tests"
OPTIONS_PER_QUESTION = 4

# Chapter number (question portion, 1-9) -> (exam_code, domain_code).
CHAPTER_EXAM_DOMAIN = {
    1: ("220-1201", "1"),
    2: ("220-1201", "2"),
    3: ("220-1201", "3"),
    4: ("220-1201", "4"),
    5: ("220-1201", "5"),
    6: ("220-1202", "1"),
    7: ("220-1202", "2"),
    8: ("220-1202", "3"),
    9: ("220-1202", "4"),
}

QUESTION_TITLE_RE = re.compile(r"^Chapter\s+(\d+)\s*(?:\(Part\s+(\d+)\s+of\s+(\d+)\))?$")
EXPLANATION_TITLE_RE = re.compile(r"^Chapter\s+(\d+):\s*(.+?)\s*(?:\(Part\s+(\d+)\s+of\s+(\d+)\))?$")
STEM_RE = re.compile(r"^(\d+)\.\s+(.*)$", re.DOTALL)
ANSWER_LETTER_RE = re.compile(r"^\d+\.\s+([A-D](?:,\s*[A-D])*)\.\s+(.*)$", re.DOTALL)

# Figure detection is structural, not lexical: see lib/question_figures. The
# prose check survives only to catch a question that promises a picture we
# could not resolve, which stays deactivated because it cannot be answered.


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_paragraphs_with_origin(section_rows):
    """section_rows: ordered list of sqlite3.Row (id, position, content).
    Returns a flat list of (section_row, paragraph_text) preserving order."""
    out = []
    for row in section_rows:
        for para in re.split(r"\n\s*\n", row["content"]):
            para = para.strip()
            if para:
                out.append((row, para))
    return out


def _load_chapter_groups(conn, book_id, title_re, chapter_range):
    """Group sections whose title matches title_re by chapter number, sorted
    by (part, position). Returns {chapter_num: [row, ...]}."""
    rows = conn.execute(
        "SELECT id, position, part, part_count, title, content, source_item FROM sections "
        "WHERE book_id = ? ORDER BY position",
        (book_id,),
    ).fetchall()
    groups = {}
    for row in rows:
        m = title_re.match(row["title"].strip())
        if not m:
            continue
        num = int(m.group(1))
        if num not in chapter_range:
            continue
        groups.setdefault(num, []).append(row)
    for num in groups:
        groups[num].sort(key=lambda r: r["position"])
    return groups


def _parse_questions(paras_with_origin):
    """Returns {qnum: {"stem": str, "options": [str,...], "section_row": Row}}.

    Structural invariant (validated corpus-wide): every question has exactly
    OPTIONS_PER_QUESTION options, so a lockstep scan (expect stem N, then N's
    OPTIONS_PER_QUESTION options) fully disambiguates stems from options
    without any text/punctuation heuristic.
    """
    questions = {}
    expect_stem = 1
    awaiting = 0
    opt_next = 1
    current = None
    for row, para in paras_with_origin:
        m = STEM_RE.match(para)
        if not m:
            continue
        n = int(m.group(1))
        text = m.group(2)
        if awaiting == 0:
            if n == expect_stem:
                current = {"stem": text, "options": [], "section_row": row}
                questions[n] = current
                expect_stem += 1
                awaiting = OPTIONS_PER_QUESTION
                opt_next = 1
        else:
            if n == opt_next:
                current["options"].append(text)
                opt_next += 1
                awaiting -= 1
    return questions


def _parse_answers(paras_with_origin, total_questions):
    """Returns {qnum: {"letters": [...], "explanation": str, "section_row": Row}}
    for successfully-paired answers, plus a separate {qnum: reason} skip map.

    Two-pass by design (not a sequential/lockstep scan): a short numbered list
    embedded in one explanation's prose (e.g. a how-to step list) can carry
    the same number as a LATER question's genuinely-unparseable (no letter
    grade) answer. Since embedded lists never carry a letter grade, indexing
    every letter-graded paragraph by its own number -- independent of scan
    position -- can't be confused by such a list, whereas a lockstep "expect
    N next" scan can be fooled into consuming the wrong paragraph for N.
    """
    letter_matches = {}
    any_numbered = set()
    for row, para in paras_with_origin:
        m = STEM_RE.match(para)
        if not m:
            continue
        n = int(m.group(1))
        if n < 1 or n > total_questions:
            continue
        any_numbered.add(n)
        if n in letter_matches:
            continue  # keep the first-in-document occurrence
        lm = ANSWER_LETTER_RE.match(para)
        if lm:
            letters = [l.strip() for l in lm.group(1).split(",")]
            letter_matches[n] = {
                "letters": letters,
                "explanation": lm.group(2).strip(),
                "section_row": row,
            }

    answers = {}
    skips = {}
    for n in range(1, total_questions + 1):
        if n in letter_matches:
            answers[n] = letter_matches[n]
        elif n in any_numbered:
            skips[n] = "unparseable_answer_no_letter"
        else:
            skips[n] = "missing_answer_paragraph"
    return answers, skips


def _upsert_question(conn, exam_id, domain_id, chapter, qnum, stem, options, letters,
                      explanation, q_section_id, a_section_id, requires_figure,
                      figure_member=None):
    correct_indexes = sorted(ord(l) - ord("A") for l in letters)
    options_json = json.dumps(options)
    correct_json = json.dumps(correct_indexes)
    content_hash = sha256_text(stem + "|" + options_json + "|" + correct_json + "|" + explanation)
    stable_id = f"{PRACTICE_BOOK_SLUG}:ch{chapter}:q{qnum:04d}"
    provenance = (
        f"{PRACTICE_BOOK_SLUG} chapter {chapter} Q{qnum}: domain-level evidence via "
        f"chapter-to-domain heuristic mapping, not verified against CompTIA's official "
        f"objectives document; question and answer paired by sequential position "
        f"within the chapter, not exact-objective aligned."
    )
    ts = now_iso()
    # A figure-dependent question is answerable exactly when its figure can be
    # rendered; one whose prose promises a picture we cannot resolve stays out.
    active = 1 if (not requires_figure or figure_member) else 0
    conn.execute(
        "INSERT INTO question_bank(stable_id, exam_id, domain_id, objective_id, mapping_granularity, "
        "question_book_slug, question_section_id, question_number, answer_book_slug, answer_section_id, "
        "prompt, options_json, correct_answers_json, explanation, provenance, content_hash, "
        "requires_figure, figure_member, critical, active, created_at, updated_at) "
        "VALUES (?, ?, ?, NULL, 'domain', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?) "
        "ON CONFLICT(stable_id) DO UPDATE SET "
        "  exam_id=excluded.exam_id, domain_id=excluded.domain_id, question_section_id=excluded.question_section_id, "
        "  answer_section_id=excluded.answer_section_id, prompt=excluded.prompt, options_json=excluded.options_json, "
        "  correct_answers_json=excluded.correct_answers_json, explanation=excluded.explanation, "
        "  provenance=excluded.provenance, content_hash=excluded.content_hash, "
        "  requires_figure=excluded.requires_figure, figure_member=excluded.figure_member, "
        "  active=excluded.active, updated_at=excluded.updated_at",
        (
            stable_id, exam_id, domain_id, PRACTICE_BOOK_SLUG, q_section_id, qnum,
            PRACTICE_BOOK_SLUG, a_section_id, stem, options_json, correct_json, explanation,
            provenance, content_hash, 1 if requires_figure else 0, figure_member, active, ts, ts,
        ),
    )


def import_questions(conn):
    """Idempotent import. Returns a stats dict with counts and skip reasons."""
    book = conn.execute("SELECT id FROM books WHERE slug = ?", (PRACTICE_BOOK_SLUG,)).fetchone()
    if not book:
        raise RuntimeError(f"book '{PRACTICE_BOOK_SLUG}' must be ingested before diagnostics import")
    book_id = book["id"]

    q_groups = _load_chapter_groups(conn, book_id, QUESTION_TITLE_RE, CHAPTER_EXAM_DOMAIN.keys())
    e_groups = _load_chapter_groups(conn, book_id, EXPLANATION_TITLE_RE, CHAPTER_EXAM_DOMAIN.keys())

    figures = question_figures.figure_map(conn, PRACTICE_BOOK_SLUG)

    stats = {
        "imported": 0,
        "requires_figure": 0,
        "figures_attached": 0,
        "figure_claimed_unresolved": 0,
        "skipped": 0,
        "skip_reasons": {},
    }

    for chapter, (exam_code, domain_code) in CHAPTER_EXAM_DOMAIN.items():
        exam_row = conn.execute("SELECT id FROM exams WHERE code = ?", (exam_code,)).fetchone()
        domain_row = conn.execute(
            "SELECT id FROM domains WHERE exam_id = ? AND code = ?",
            (exam_row["id"] if exam_row else None, domain_code),
        ).fetchone()
        if not exam_row or not domain_row:
            stats["skip_reasons"].setdefault("missing_exam_or_domain_seed", 0)
            stats["skip_reasons"]["missing_exam_or_domain_seed"] += 1
            continue
        exam_id = exam_row["id"]
        domain_id = domain_row["id"]

        q_paras = _split_paragraphs_with_origin(q_groups.get(chapter, []))
        e_paras = _split_paragraphs_with_origin(e_groups.get(chapter, []))
        questions = _parse_questions(q_paras)
        total = len(questions)
        answers, answer_skips = _parse_answers(e_paras, total)

        for qnum in range(1, total + 1):
            reason = None
            q = questions.get(qnum)
            if q is None:
                reason = "missing_question_paragraph"
            elif qnum in answer_skips:
                reason = answer_skips[qnum]
            if reason:
                stats["skipped"] += 1
                stats["skip_reasons"][reason] = stats["skip_reasons"].get(reason, 0) + 1
                continue

            a = answers[qnum]
            letters = a["letters"]
            options = q["options"]
            if any((ord(l) - ord("A")) >= len(options) for l in letters):
                stats["skipped"] += 1
                stats["skip_reasons"]["answer_index_out_of_range"] = (
                    stats["skip_reasons"].get("answer_index_out_of_range", 0) + 1
                )
                continue

            figure_member = figures.get((q["section_row"]["source_item"], qnum))
            requires_figure = bool(figure_member) or question_figures.claims_figure(q["stem"], options)
            _upsert_question(
                conn, exam_id, domain_id, chapter, qnum, q["stem"], options, letters,
                a["explanation"], q["section_row"]["id"], a["section_row"]["id"], requires_figure,
                figure_member,
            )
            if requires_figure:
                stats["requires_figure"] += 1
            if figure_member:
                stats["figures_attached"] += 1
                stats["imported"] += 1
            elif requires_figure:
                stats["figure_claimed_unresolved"] += 1
                stats["skipped"] += 1
                stats["skip_reasons"]["requires_figure"] = stats["skip_reasons"].get("requires_figure", 0) + 1
            else:
                stats["imported"] += 1

    conn.commit()
    return stats


# --- Diagnostic scope seeding -------------------------------------------

WEEK_DOMAIN_RE = re.compile(r"Domain\s+(\d+):")
REVIEW_WEEK_RE = re.compile(r"review & practice checkpoint")


MIN_VALID_QUESTIONS = 10


def _upsert_scope(conn, slug, name, scope_type, plan_week_id, exam_id, domain_id,
                   provenance, coverage_metadata, available_questions):
    ts = now_iso()
    enabled = 1 if available_questions >= MIN_VALID_QUESTIONS else 0
    conn.execute(
        "INSERT INTO diagnostic_scopes(slug, name, scope_type, plan_week_id, exam_id, domain_id, "
        "question_target, min_valid_questions, raw_pass_threshold_pct, effective_pass_threshold_pct, "
        "retention_interval_days, provenance, enabled, coverage_metadata_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 20, ?, 85.0, 80.0, 14, ?, ?, ?, ?, ?) "
        "ON CONFLICT(slug) DO UPDATE SET "
        "  name=excluded.name, plan_week_id=excluded.plan_week_id, exam_id=excluded.exam_id, "
        "  domain_id=excluded.domain_id, provenance=excluded.provenance, enabled=excluded.enabled, "
        "  coverage_metadata_json=excluded.coverage_metadata_json, updated_at=excluded.updated_at",
        (slug, name, scope_type, plan_week_id, exam_id, domain_id, MIN_VALID_QUESTIONS, provenance,
         enabled, json.dumps(coverage_metadata), ts, ts),
    )
    row = conn.execute("SELECT id FROM diagnostic_scopes WHERE slug = ?", (slug,)).fetchone()
    scope_id = row["id"]
    exists = conn.execute("SELECT 1 FROM scope_mastery WHERE scope_id = ?", (scope_id,)).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO scope_mastery(scope_id, status, updated_at) VALUES (?, 'unassessed', ?)",
            (scope_id, ts),
        )
    return scope_id


def _domain_question_counts(conn, exam_id):
    rows = conn.execute(
        "SELECT domain_id, COUNT(*) AS n FROM question_bank "
        "WHERE exam_id = ? AND active = 1 GROUP BY domain_id",
        (exam_id,),
    ).fetchall()
    return {r["domain_id"]: r["n"] for r in rows}


def seed_diagnostic_scopes(conn):
    """One scope per domain-focused plan week; one exam-wide composite scope
    per review/checkpoint week. Idempotent (upsert by deterministic slug)."""
    weeks = conn.execute(
        "SELECT w.id, w.week_number, w.exam_id, w.focus, e.code AS exam_code, e.name AS exam_name "
        "FROM plan_weeks w JOIN exams e ON e.id = w.exam_id ORDER BY w.week_number"
    ).fetchall()
    stats = {"domain_scopes": 0, "composite_scopes": 0}
    for w in weeks:
        focus = w["focus"] or ""
        if REVIEW_WEEK_RE.search(focus):
            counts = _domain_question_counts(conn, w["exam_id"])
            if not counts:
                continue
            slug = f"aplus-week{w['week_number']}-composite"
            coverage = {
                "kind": "exam_composite",
                "per_domain_active_question_counts": {str(k): v for k, v in counts.items()},
                "disclosure": (
                    "Composite scope pools active questions across all domains of this exam; "
                    "each question retains its own source domain in question_bank."
                ),
            }
            _upsert_scope(
                conn, slug, f"Week {w['week_number']} composite check: {w['exam_name']}",
                "exam_composite", w["id"], w["exam_id"], None,
                f"seeded from review/checkpoint week '{focus}'; pools all domains of {w['exam_code']}",
                coverage, sum(counts.values()),
            )
            stats["composite_scopes"] += 1
            continue

        m = WEEK_DOMAIN_RE.search(focus)
        if not m:
            continue
        domain_code = m.group(1)
        domain_row = conn.execute(
            "SELECT id, name FROM domains WHERE exam_id = ? AND code = ?",
            (w["exam_id"], domain_code),
        ).fetchone()
        if not domain_row:
            continue
        slug = f"aplus-week{w['week_number']}-domain-{domain_code}"
        n_active = conn.execute(
            "SELECT COUNT(*) AS n FROM question_bank WHERE exam_id = ? AND domain_id = ? AND active = 1",
            (w["exam_id"], domain_row["id"]),
        ).fetchone()["n"]
        coverage = {"kind": "domain", "active_question_count": n_active}
        _upsert_scope(
            conn, slug, f"Week {w['week_number']} knowledge check: {domain_row['name']}",
            "domain", w["id"], w["exam_id"], domain_row["id"],
            f"seeded from domain-focused week '{focus}'; domain-level evidence only, "
            f"objective_id is NULL on all linked questions",
            coverage, n_active,
        )
        stats["domain_scopes"] += 1
    conn.commit()
    return stats
