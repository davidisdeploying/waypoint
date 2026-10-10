import tempfile
import unittest
from pathlib import Path

from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from lib import api_logic, daily_sessions, db, mastery
from lib.api_logic import ApiError
from tests.fixtures import build_all_sources


class TestObjectiveMasteryMap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        ingest_all(self.conn, build_all_sources(Path(self.tmp.name)))
        seed_plan(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _objectives(self):
        return self.conn.execute(
            "SELECT o.id, o.exam_id, o.code FROM objectives o "
            "ORDER BY o.id LIMIT 3"
        ).fetchall()

    def test_map_is_grouped_and_conservative_without_direct_evidence(self):
        result = mastery.get_mastery_map(self.conn)
        self.assertEqual(len(result["exams"]), 2)
        self.assertGreater(result["totals"]["objectives"], 0)
        self.assertEqual(
            result["totals"]["not_assessed"], result["totals"]["objectives"]
        )
        self.assertEqual(result["totals"]["objectives_with_direct_assessment"], 0)
        self.assertIn("not presented as exact objective mastery", result["evidence_note"])

    def test_objective_practice_sets_needs_work_and_strong_signal(self):
        first, second, _ = self._objectives()
        api_logic.create_attempt(
            self.conn, first["exam_id"], 1, 2, "2026-01-01T00:00:00Z",
            objective_id=first["id"],
        )
        api_logic.create_attempt(
            self.conn, second["exam_id"], 9, 10, "2026-01-01T00:00:00Z",
            objective_id=second["id"],
        )
        api_logic.create_attempt(
            self.conn, second["exam_id"], 10, 10, "2026-01-02T00:00:00Z",
            objective_id=second["id"],
        )
        result = mastery.get_mastery_map(self.conn)
        statuses = {
            objective["id"]: objective["status"]
            for exam in result["exams"]
            for domain in exam["domains"]
            for objective in domain["objectives"]
        }
        self.assertEqual(statuses[first["id"]], "needs_work")
        self.assertEqual(statuses[second["id"]], "strong_signal")

    def test_opened_cited_section_marks_objective_studied_not_mastered(self):
        link = self.conn.execute(
            "SELECT l.objective_id, s.stable_id FROM objective_chunk_links l "
            "JOIN sections s ON s.id = l.section_id ORDER BY l.id LIMIT 1"
        ).fetchone()
        primary = api_logic.get_study_next(self.conn, limit=1)["primary"]
        daily_sessions.start(self.conn, 25, primary)
        daily_sessions.log_event(
            self.conn,
            "reading_opened",
            "Objective source",
            event_key=f"section:{link['stable_id']}",
            metadata={"section_stable_id": link["stable_id"]},
        )
        detail = mastery.get_objective_mastery(self.conn, link["objective_id"])
        self.assertEqual(detail["status"], "studied")
        self.assertGreater(detail["evidence"]["cited_sections_opened"], 0)
        self.assertEqual(detail["evidence"]["objective_assessments"], 0)

    def test_exam_filter_and_unknown_exam(self):
        result = mastery.get_mastery_map(self.conn, exam="220-1201")
        self.assertEqual([exam["code"] for exam in result["exams"]], ["220-1201"])
        with self.assertRaises(ApiError):
            mastery.get_mastery_map(self.conn, exam="made-up")

    def test_objective_reading_uses_one_chapter_aligned_review_source(self):
        objective = self.conn.execute("SELECT id FROM objectives LIMIT 1").fetchone()
        detail = api_logic.get_objective(self.conn, objective["id"])
        self.assertEqual(len(detail["evidence"]), 1)
        self.assertEqual(detail["evidence"][0]["book_slug"], "fixture-review")
        self.assertTrue(detail["evidence"][0]["focused_excerpt"])
        self.assertNotIn("content", detail["evidence"][0])
