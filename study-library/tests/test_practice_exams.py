import json
import tempfile
import unittest
from pathlib import Path

from ingest.ingest import ingest_all
from lib import api_logic, db, diagnostics, practice_exams
from lib.api_logic import ApiError
from tests.fixtures import build_all_sources


class TestPracticeExams(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        ingest_all(self.conn, build_all_sources(Path(self.tmp.name)))
        self.exam = self.conn.execute(
            "SELECT id, code FROM exams WHERE code='220-1201'"
        ).fetchone()
        self.old_pool = practice_exams.POOL_SIZE
        self.old_target = practice_exams.QUESTION_TARGET
        self.old_duration = practice_exams.DURATION_MINUTES
        practice_exams.POOL_SIZE = 10
        practice_exams.QUESTION_TARGET = 5
        practice_exams.DURATION_MINUTES = 15
        timestamp = "2026-01-01T00:00:00+00:00"
        for code, name in (
            ("1", "Mobile Devices"),
            ("2", "Networking"),
            ("3", "Hardware"),
            ("4", "Virtualization and Cloud Computing"),
            ("5", "Hardware and Network Troubleshooting"),
        ):
            self.conn.execute(
                "INSERT OR IGNORE INTO domains("
                "exam_id, code, name, provenance, confidence, created_at, updated_at"
                ") VALUES (?, ?, ?, 'fixture', 1.0, ?, ?)",
                (self.exam["id"], code, name, timestamp, timestamp),
            )
        domains = self.conn.execute(
            "SELECT id, code FROM domains WHERE exam_id=? ORDER BY code",
            (self.exam["id"],),
        ).fetchall()
        question_number = 1
        for domain in domains:
            for offset in range(5):
                self.conn.execute(
                    "INSERT INTO question_bank("
                    "stable_id, exam_id, domain_id, objective_id, mapping_granularity, "
                    "question_book_slug, question_number, answer_book_slug, prompt, "
                    "options_json, correct_answers_json, explanation, provenance, "
                    "content_hash, requires_figure, critical, active, created_at, updated_at"
                    ") VALUES (?, ?, ?, NULL, 'domain', 'practice', ?, 'practice', ?, "
                    "?, '[0]', ?, 'fixture', ?, 0, 0, 1, ?, ?)",
                    (
                        f"practice-{domain['code']}-{offset}",
                        self.exam["id"],
                        domain["id"],
                        question_number,
                        f"Domain {domain['code']} question {offset}?",
                        json.dumps(["Correct", "Wrong"]),
                        f"Explanation {domain['code']}-{offset}",
                        f"hash-{domain['code']}-{offset}",
                        timestamp,
                        timestamp,
                    ),
                )
                question_number += 1
        self.conn.commit()

    def tearDown(self):
        practice_exams.POOL_SIZE = self.old_pool
        practice_exams.QUESTION_TARGET = self.old_target
        practice_exams.DURATION_MINUTES = self.old_duration
        self.conn.close()
        self.tmp.cleanup()

    def test_pool_is_weighted_reserved_and_attempt_is_resumable(self):
        attempt = practice_exams.start_attempt(self.conn, self.exam["code"])
        self.assertEqual(len(attempt["responses"]), 5)
        self.assertTrue(attempt["answers_redacted"])
        self.assertNotIn("correct_answers", attempt["responses"][0])
        self.assertNotIn("explanation", attempt["responses"][0])
        reserved = {
            row["question_id"] for row in self.conn.execute(
                "SELECT question_id FROM practice_exam_question_pool"
            ).fetchall()
        }
        self.assertEqual(len(reserved), 10)
        question = attempt["responses"][0]
        saved = practice_exams.save_answer(
            self.conn, attempt["id"], question["question_id"], [0]
        )
        self.assertEqual(saved["answered_count"], 1)
        resumed = practice_exams.get_attempt(self.conn, attempt["id"])
        self.assertEqual(resumed["answered_count"], 1)
        self.assertEqual(resumed["responses"][0]["submitted_answer"], [0])
        scope = {"scope_type": "exam_composite", "exam_id": self.exam["id"]}
        where, params = diagnostics._scope_pool_where(scope)
        diagnostic_ids = {
            row["id"] for row in self.conn.execute(
                f"SELECT id FROM question_bank WHERE {where}", params
            ).fetchall()
        }
        self.assertFalse(reserved & diagnostic_ids)

    def test_submit_scores_unanswered_and_reports_only_domain_precision(self):
        attempt = practice_exams.start_attempt(self.conn, self.exam["code"])
        for response in attempt["responses"][:4]:
            practice_exams.save_answer(
                self.conn, attempt["id"], response["question_id"], [0]
            )
        result = practice_exams.submit_attempt(self.conn, attempt["id"])
        self.assertEqual(result["raw_score_pct"], 80.0)
        self.assertEqual(result["readiness_band"], "approaching")
        self.assertFalse(result["answers_redacted"])
        self.assertIn("correct_answers", result["responses"][0])
        self.assertTrue(result["breakdown"]["domains"])
        self.assertEqual(result["breakdown"]["objectives"], [])
        self.assertIn("domain-mapped", result["breakdown"]["mapping_note"])

    def test_one_active_attempt_and_export(self):
        attempt = practice_exams.start_attempt(self.conn, self.exam["code"])
        with self.assertRaises(ApiError):
            practice_exams.start_attempt(self.conn, self.exam["code"])
        snapshot = api_logic.export_snapshot(self.conn, "http://localhost")
        self.assertEqual(snapshot["practice_exam_attempts"][0]["id"], attempt["id"])
        abandoned = practice_exams.abandon_attempt(self.conn, attempt["id"])
        self.assertEqual(abandoned["state"], "abandoned")


if __name__ == "__main__":
    unittest.main()
