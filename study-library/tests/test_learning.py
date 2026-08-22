import tempfile
import unittest
from pathlib import Path

from ingest.ingest import ingest_all
from lib import api_logic, db, learning, mastery
from lib.api_logic import ApiError
from tests.fixtures import build_all_sources


class TestCertificationLearning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        ingest_all(self.conn, build_all_sources(Path(self.tmp.name)))
        self.objective = self.conn.execute(
            "SELECT id FROM objectives ORDER BY id LIMIT 1"
        ).fetchone()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_lesson_activity_is_idempotent_and_not_mastery(self):
        first = learning.record_event(
            self.conn,
            self.objective["id"],
            "lesson_completed",
            event_key=f"objective:{self.objective['id']}:lesson-completed",
        )
        second = learning.record_event(
            self.conn,
            self.objective["id"],
            "lesson_completed",
            event_key=f"objective:{self.objective['id']}:lesson-completed",
        )
        self.assertTrue(first["lesson_completed"])
        self.assertEqual(second["counts"]["lesson_completed"], 1)

        status = mastery.get_objective_mastery(
            self.conn, self.objective["id"]
        )
        self.assertEqual(status["status"], "studied")
        self.assertEqual(status["evidence"]["lessons_completed"], 1)
        self.assertEqual(status["evidence"]["objective_assessments"], 0)

    def test_reading_and_recall_are_recorded_separately(self):
        detail = api_logic.get_objective(self.conn, self.objective["id"])
        source = detail["evidence"][0]
        learning.record_event(
            self.conn,
            self.objective["id"],
            "reading_opened",
            event_key=f"objective:{self.objective['id']}:section:{source['stable_id']}",
            metadata={"section_stable_id": source["stable_id"]},
        )
        state = learning.record_event(
            self.conn,
            self.objective["id"],
            "recall_completed",
            event_key=f"objective:{self.objective['id']}:recall-completed",
        )
        self.assertEqual(state["counts"]["reading_opened"], 1)
        self.assertTrue(state["recall_completed"])
        mastery_state = mastery.get_objective_mastery(
            self.conn, self.objective["id"]
        )
        self.assertEqual(mastery_state["evidence"]["cited_sections_opened"], 1)
        self.assertEqual(mastery_state["evidence"]["recall_completed"], 1)

    def test_navigation_stays_on_certification_spine(self):
        detail = api_logic.get_objective(self.conn, self.objective["id"])
        self.assertIsNone(detail["navigation"]["previous"])
        self.assertIsNotNone(detail["navigation"]["next"])

    def test_invalid_learning_event_is_rejected(self):
        with self.assertRaises(ApiError):
            learning.record_event(
                self.conn, self.objective["id"], "mastered"
            )


if __name__ == "__main__":
    unittest.main()
