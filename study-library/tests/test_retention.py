import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from lib import api_logic, db, learning, mastery, retention
from lib.api_logic import ApiError
from tests.fixtures import build_all_sources


class TestObjectiveRetention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        ingest_all(self.conn, build_all_sources(Path(self.tmp.name)))
        seed_plan(self.conn)
        self.objective = self.conn.execute(
            "SELECT id FROM objectives ORDER BY id LIMIT 1"
        ).fetchone()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _complete_lesson(self):
        return learning.record_event(
            self.conn,
            self.objective["id"],
            "lesson_completed",
            event_key=f"lesson:{self.objective['id']}",
        )

    def test_lesson_completion_schedules_first_review(self):
        self._complete_lesson()
        state = retention.get_objective_state(self.conn, self.objective["id"])
        self.assertEqual(state["stage"], 0)
        self.assertEqual(state["interval_days"], 1)
        self.assertEqual(state["review_count"], 0)
        self.assertFalse(state["due"])

    def test_review_reschedules_without_creating_mastery(self):
        self._complete_lesson()
        reviewed_at = datetime.now(timezone.utc).isoformat()
        state = retention.record_review(
            self.conn,
            self.objective["id"],
            "good",
            event_key="review:good:1",
            reviewed_at=reviewed_at,
        )
        self.assertEqual(state["stage"], 1)
        self.assertEqual(state["interval_days"], 3)
        self.assertEqual(state["review_count"], 1)
        repeated = retention.record_review(
            self.conn,
            self.objective["id"],
            "good",
            event_key="review:good:1",
            reviewed_at=reviewed_at,
        )
        self.assertEqual(repeated["review_count"], 1)
        evidence = mastery.get_objective_mastery(self.conn, self.objective["id"])
        self.assertEqual(evidence["status"], "studied")
        self.assertEqual(evidence["evidence"]["objective_assessments"], 0)

    def test_due_review_leads_study_queue_and_week_plan(self):
        self._complete_lesson()
        overdue = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.conn.execute(
            "UPDATE objective_retention_state SET due_at = ? WHERE objective_id = ?",
            (overdue, self.objective["id"]),
        )
        self.conn.commit()
        queue = api_logic.get_study_next(self.conn, limit=8)
        self.assertEqual(queue["primary"]["kind"], "objective_retention")
        self.assertEqual(queue["counts"]["objective_retention_due"], 1)
        plan = api_logic.get_adaptive_curriculum(
            self.conn, days=7, minutes_per_day=45
        )
        self.assertEqual(
            plan["schedule"][0]["items"][0]["kind"], "objective_retention"
        )
        self.assertEqual(plan["retention"]["due"], 1)

    def test_review_requires_completed_lesson(self):
        with self.assertRaises(ApiError):
            retention.record_review(
                self.conn, self.objective["id"], "good"
            )


if __name__ == "__main__":
    unittest.main()
