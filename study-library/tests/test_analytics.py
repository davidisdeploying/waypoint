import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ingest.ingest import ingest_all
from lib import analytics, api_logic, db, labs, learning
from tests.fixtures import build_all_sources


class TestAnalytics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        ingest_all(self.conn, build_all_sources(Path(self.tmp.name)))
        self.objective_id = self.conn.execute(
            "SELECT id FROM objectives ORDER BY id LIMIT 1"
        ).fetchone()["id"]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_evidence_lanes_stay_separate(self):
        learning.record_event(
            self.conn, self.objective_id, "lesson_completed",
            event_key="analytics:lesson",
        )
        lab = labs.create_lab(
            self.conn, self.objective_id, "Cable a switch", "Verify link state."
        )
        labs.update_lab(
            self.conn, lab["id"], status="completed",
            evidence_text="Both ports negotiated successfully.",
            reflection_text="I verified speed and duplex before testing traffic.",
            completion_level="unaided",
        )
        self.conn.execute(
            "INSERT INTO study_sessions(occurred_at, duration_minutes, notes, created_at) "
            "VALUES (datetime('now'), 25, 'analytics fixture', datetime('now'))"
        )
        self.conn.commit()

        result = analytics.get_analytics(self.conn, days=30)
        self.assertEqual(result["learning"]["lessons_completed"], 1)
        self.assertEqual(result["labs"]["completed"], 1)
        self.assertEqual(result["labs"]["unaided"], 1)
        self.assertEqual(sum(day["study_minutes"] for day in result["timeline"]), 25)
        self.assertEqual(len(result["timeline"]), 30)
        self.assertNotIn("score", result)
        self.assertIn("does not calculate one universal", result["no_composite_note"])

    def test_export_includes_derived_analytics(self):
        snapshot = api_logic.export_snapshot(self.conn, "http://localhost")
        self.assertIn("analytics", snapshot)
        self.assertIn("next_action", snapshot["analytics"])

    def test_evening_central_activity_is_binned_on_the_local_date(self):
        stamp = "2026-08-15T00:30:00+00:00"
        self.conn.execute(
            "INSERT INTO study_sessions(occurred_at, duration_minutes, notes, created_at) "
            "VALUES (?, 25, 'evening fixture', ?)", (stamp, stamp)
        )
        self.conn.commit()
        with patch("lib.analytics.study_clock.today", return_value=date(2026, 8, 14)):
            result = analytics.get_analytics(self.conn, days=7)
        by_date = {row["date"]: row for row in result["timeline"]}
        self.assertEqual(by_date["2026-08-14"]["study_minutes"], 25)


if __name__ == "__main__":
    unittest.main()
