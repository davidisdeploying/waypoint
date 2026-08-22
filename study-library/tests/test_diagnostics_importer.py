import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

from lib import db
from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from ingest.diagnostics_importer import (
    _parse_questions, _parse_answers, import_questions, seed_diagnostic_scopes,
)
from tests.fixtures import build_review_source, build_diagnostics_practice_source

Row = namedtuple("Row", ["id"])  # minimal stand-in for the section_row origin


def _paras(text):
    """(fake_row, paragraph_text) tuples mimicking _split_paragraphs_with_origin,
    for testing the parser functions directly without a real DB/ingest."""
    import re
    row = Row(id=1)
    return [(row, p.strip()) for p in re.split(r"\n\s*\n", text) if p.strip()]


class TestParseQuestions(unittest.TestCase):
    def test_fixed_four_option_structure(self):
        text = (
            "1. First stem?\n\n1. opt a\n\n2. opt b\n\n3. opt c\n\n4. opt d\n\n"
            "2. Second stem?\n\n1. opt e\n\n2. opt f\n\n3. opt g\n\n4. opt h\n"
        )
        questions = _parse_questions(_paras(text))
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[1]["options"], ["opt a", "opt b", "opt c", "opt d"])
        self.assertEqual(questions[2]["stem"], "Second stem?")

    def test_embedded_numbered_list_in_prose_does_not_confuse_stems(self):
        # A stem/option pair followed by prose that happens to contain a small
        # numbered list must not be mistaken for the next question.
        text = (
            "1. Stem one?\n\n1. a\n\n2. b\n\n3. c\n\n4. d\n\n"
            "2. Stem two, with steps: 1. step one 2. step two in one paragraph?\n\n"
            "1. e\n\n2. f\n\n3. g\n\n4. h\n"
        )
        questions = _parse_questions(_paras(text))
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[2]["options"], ["e", "f", "g", "h"])


class TestParseAnswers(unittest.TestCase):
    def test_single_and_multi_letter_answers(self):
        text = "1. B. Explanation one.\n\n2. A, C. Explanation two spans a comma list.\n"
        answers, skips = _parse_answers(_paras(text), total_questions=2)
        self.assertEqual(answers[1]["letters"], ["B"])
        self.assertEqual(answers[2]["letters"], ["A", "C"])
        self.assertEqual(skips, {})

    def test_no_letter_answer_is_skipped_not_fatal(self):
        text = (
            "1. B. Explanation one.\n\n"
            "2. This one has no letter grade at all, it just describes a figure.\n\n"
            "3. C. Explanation three.\n"
        )
        answers, skips = _parse_answers(_paras(text), total_questions=3)
        self.assertEqual(set(answers), {1, 3})
        self.assertEqual(skips, {2: "unparseable_answer_no_letter"})

    def test_embedded_short_list_does_not_shift_alignment(self):
        # A short embedded numbered list inside an earlier explanation (e.g. a
        # how-to) must not be mistaken for a later question's answer.
        text = (
            "1. B. Do these steps:\n\n1. Enable it.\n\n2. Pair it.\n\n"
            "2. C. Second real answer.\n"
        )
        answers, skips = _parse_answers(_paras(text), total_questions=2)
        self.assertEqual(answers[1]["letters"], ["B"])
        self.assertEqual(answers[2]["letters"], ["C"])

    def test_missing_answer_paragraph_reported(self):
        text = "1. B. Only one answer present.\n"
        answers, skips = _parse_answers(_paras(text), total_questions=3)
        self.assertEqual(set(answers), {1})
        self.assertEqual(skips[2], "missing_answer_paragraph")
        self.assertEqual(skips[3], "missing_answer_paragraph")


class TestImportQuestionsFixture(unittest.TestCase):
    """Runs the importer against a real ingested fixture book (through the
    normal ingest pipeline), not synthetic paragraph tuples."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        review_src = build_review_source(Path(self.tmp.name))
        diag_src = build_diagnostics_practice_source(Path(self.tmp.name))
        ingest_all(self.conn, [review_src, diag_src])
        seed_plan(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_import_counts_and_skip_reasons(self):
        stats = import_questions(self.conn)
        # 4 fixture questions: Q1 valid, Q2 valid multi-select, Q3 valid-but-figure,
        # Q4 unparseable (no letter grade).
        self.assertEqual(stats["imported"], 2)
        self.assertEqual(stats["requires_figure"], 1)
        self.assertEqual(stats["skip_reasons"].get("unparseable_answer_no_letter"), 1)

        rows = {
            r["question_number"]: dict(r)
            for r in self.conn.execute("SELECT * FROM question_bank ORDER BY question_number")
        }
        self.assertEqual(set(rows), {1, 2, 3})  # Q4 excluded entirely (no letter)
        self.assertEqual(rows[1]["active"], 1)
        self.assertEqual(rows[3]["requires_figure"], 1)
        self.assertEqual(rows[3]["active"], 0, "figure-dependent questions must not be active")
        self.assertEqual(rows[1]["objective_id"], None)
        self.assertEqual(rows[1]["mapping_granularity"], "domain")

        import json
        self.assertEqual(json.loads(rows[1]["correct_answers_json"]), [1])  # B -> index 1
        self.assertEqual(json.loads(rows[2]["correct_answers_json"]), [0, 2])  # A, C

    def test_import_is_idempotent(self):
        first = import_questions(self.conn)
        count1 = self.conn.execute("SELECT COUNT(*) AS n FROM question_bank").fetchone()["n"]
        second = import_questions(self.conn)
        count2 = self.conn.execute("SELECT COUNT(*) AS n FROM question_bank").fetchone()["n"]
        self.assertEqual(count1, count2)
        self.assertEqual(first["imported"], second["imported"])

    def test_scope_seeding_creates_domain_scope_and_disables_when_too_few_questions(self):
        import_questions(self.conn)
        stats = seed_diagnostic_scopes(self.conn)
        self.assertGreaterEqual(stats["domain_scopes"], 1)
        scope = self.conn.execute(
            "SELECT * FROM diagnostic_scopes WHERE slug = 'aplus-week1-domain-1'"
        ).fetchone()
        self.assertIsNotNone(scope)
        # Only 2 active questions exist in this tiny fixture (< min_valid_questions=10).
        self.assertEqual(scope["enabled"], 0)

        mastery = self.conn.execute(
            "SELECT * FROM scope_mastery WHERE scope_id = ?", (scope["id"],)
        ).fetchone()
        self.assertIsNotNone(mastery)
        self.assertEqual(mastery["status"], "unassessed")

    def test_reingest_does_not_alter_existing_attempts_or_mastery(self):
        import_questions(self.conn)
        seed_diagnostic_scopes(self.conn)
        scope = self.conn.execute("SELECT id FROM diagnostic_scopes LIMIT 1").fetchone()
        ts = "2026-01-01T00:00:00+00:00"
        self.conn.execute(
            "UPDATE scope_mastery SET status = 'provisional_mastery', updated_at = ? WHERE scope_id = ?",
            (ts, scope["id"]),
        )
        self.conn.commit()

        import_questions(self.conn)  # re-ingest
        seed_diagnostic_scopes(self.conn)  # re-seed (idempotent upsert)

        mastery = self.conn.execute(
            "SELECT status FROM scope_mastery WHERE scope_id = ?", (scope["id"],)
        ).fetchone()
        self.assertEqual(mastery["status"], "provisional_mastery", "re-ingest must not reset user mastery state")


if __name__ == "__main__":
    unittest.main()
