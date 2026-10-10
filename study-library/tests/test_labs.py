import tempfile
import unittest
from pathlib import Path

from ingest.ingest import ingest_all
from lib import api_logic, db, lab_catalog, labs
from lib.api_logic import ApiError
from tests.fixtures import build_all_sources


class TestHandsOnLabs(unittest.TestCase):
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

    def test_lab_lifecycle_preserves_honest_completion_evidence(self):
        lab = labs.create_lab(
            self.conn,
            self.objective_id,
            "Replace laptop RAM",
            "Install and verify a compatible SODIMM.",
            environment_text="Practice laptop and ESD strap",
            client_key="lab:ram:1",
        )
        self.assertEqual(lab["status"], "planned")
        started = labs.update_lab(
            self.conn, lab["id"], status="in_progress"
        )
        self.assertIsNotNone(started["started_at"])
        completed = labs.update_lab(
            self.conn,
            lab["id"],
            status="completed",
            evidence_text="System detected 16 GB and passed memory diagnostics.",
            reflection_text="I checked the keyed notch before seating the module.",
            completion_level="unaided",
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["completion_level"], "unaided")
        self.assertIsNotNone(completed["completed_at"])
        listing = labs.list_labs(self.conn)
        self.assertEqual(listing["summary"]["completed"], 1)
        self.assertEqual(listing["summary"]["unaided"], 1)
        self.assertIn("do not create assessment mastery", listing["evidence_note"])

    def test_completion_requires_results_reflection_and_level(self):
        lab = labs.create_lab(
            self.conn, self.objective_id, "Test", "Practice safely."
        )
        with self.assertRaises(ApiError):
            labs.update_lab(self.conn, lab["id"], status="completed")
        with self.assertRaises(ApiError):
            labs.update_lab(
                self.conn,
                lab["id"],
                status="completed",
                evidence_text="It worked.",
                reflection_text="I learned.",
                completion_level="expert",
            )

    def test_idempotent_create_archive_and_export(self):
        first = labs.create_lab(
            self.conn,
            self.objective_id,
            "Wi-Worker1 card",
            "Replace and verify the adapter.",
            client_key="lab:wifi:1",
        )
        second = labs.create_lab(
            self.conn,
            self.objective_id,
            "Ignored duplicate",
            "Ignored duplicate",
            client_key="lab:wifi:1",
        )
        self.assertEqual(first["id"], second["id"])
        snapshot = api_logic.export_snapshot(self.conn, "http://localhost")
        self.assertEqual(len(snapshot["hands_on_labs"]), 1)
        archived = labs.update_lab(self.conn, first["id"], archived=True)
        self.assertTrue(archived["archived"])
        self.assertEqual(labs.list_labs(self.conn)["labs"], [])

    def test_governed_template_launch_preserves_snapshot_and_history(self):
        catalog = lab_catalog.list_templates(self.conn)
        self.assertGreater(catalog["summary"]["available"], 0)
        template = catalog["templates"][0]
        launched = lab_catalog.launch_template(
            self.conn, template["slug"], client_key="catalog:test:1"
        )
        repeated = lab_catalog.launch_template(
            self.conn, template["slug"], client_key="catalog:test:1"
        )
        self.assertEqual(launched["id"], repeated["id"])
        self.assertEqual(launched["template_slug"], template["slug"])
        self.assertEqual(
            launched["template"]["steps"], template["steps"]
        )
        self.assertIn("Success checks:", launched["goal_text"])
        refreshed = lab_catalog.list_templates(self.conn)
        refreshed_template = next(
            item for item in refreshed["templates"]
            if item["slug"] == template["slug"]
        )
        self.assertEqual(refreshed_template["history"]["launched"], 1)
        snapshot = api_logic.export_snapshot(self.conn, "http://localhost")
        self.assertEqual(
            snapshot["hands_on_labs"][0]["catalog_version"],
            catalog["catalog_version"],
        )
        self.assertIn("lab_catalog", snapshot)


if __name__ == "__main__":
    unittest.main()
