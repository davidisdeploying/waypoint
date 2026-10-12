import sqlite3
import unittest

from lib import db, learning_requests


class LearningRequestsTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript((db.SCHEMA_V19_PATH).read_text(encoding="utf-8"))

    def tearDown(self):
        self.conn.close()

    def test_import_is_idempotent_and_planning_only(self):
        payload = {
            "schema_version": 1,
            "source": "prospect_job_listing_audit",
            "source_audit_id": 42,
            "source_listing_id": 9,
            "role": "Infrastructure Technician",
            "company": "Example",
            "career_claims_hash": "a" * 64,
            "proposals": [{
                "skill": "Linux",
                "priority": "medium",
                "technology": "Linux administration",
                "evidence_building_method": "Build a troubleshooting lab.",
                "certification_id": "linuxplus",
                "certification_label": "CompTIA Linux+",
                "waypoint_scope_status": "missing",
                "source_requirement_ids": ["abc123"],
            }],
        }
        first = learning_requests.create_many(self.conn, payload)
        second = learning_requests.create_many(self.conn, payload)
        self.assertEqual(len(first["learning_requests"]), 1)
        self.assertEqual(len(second["learning_requests"]), 1)
        self.assertEqual(first["evidence_boundary"], "planning_only_no_progress_or_mastery")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM learning_requests").fetchone()[0], 1)
        for forbidden in ("learning_events", "objective_mastery", "study_sessions"):
            self.assertIsNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = ?", (forbidden,)).fetchone())


if __name__ == "__main__":
    unittest.main()
