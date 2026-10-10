import tempfile
import unittest
from pathlib import Path

from ingest.ingest import ingest_all
from lib import annotations, api_logic, db
from lib.api_logic import ApiError
from tests.fixtures import build_all_sources


class TestStudyAnnotations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        ingest_all(self.conn, build_all_sources(Path(self.tmp.name)))
        self.objective = self.conn.execute(
            "SELECT id FROM objectives ORDER BY id LIMIT 1"
        ).fetchone()
        self.source = api_logic.get_objective(
            self.conn, self.objective["id"]
        )["evidence"][0]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_highlight_is_source_bound_and_idempotent(self):
        created = annotations.create_annotation(
            self.conn,
            self.objective["id"],
            "highlight",
            section_stable_id=self.source["stable_id"],
            quote_text="mobile device",
            prefix_text="a",
            suffix_text="lesson",
            note_text="Remember this distinction.",
            content_sha256=self.source["content_sha256"],
            anchor_start=4,
            anchor_end=17,
            client_key="highlight:1",
        )
        repeated = annotations.create_annotation(
            self.conn,
            self.objective["id"],
            "highlight",
            section_stable_id=self.source["stable_id"],
            quote_text="mobile device",
            content_sha256=self.source["content_sha256"],
            client_key="highlight:1",
        )
        self.assertEqual(created["id"], repeated["id"])
        self.assertEqual(created["anchor_status"], "exact")
        self.assertEqual(
            annotations.list_annotations(self.conn, self.objective["id"])[0]["note_text"],
            "Remember this distinction.",
        )

    def test_note_and_recoverable_archive(self):
        note = annotations.create_annotation(
            self.conn,
            self.objective["id"],
            "note",
            note_text="My own explanation.",
        )
        updated = annotations.update_annotation(
            self.conn, note["id"], note_text="A clearer explanation."
        )
        self.assertEqual(updated["note_text"], "A clearer explanation.")
        archived = annotations.update_annotation(
            self.conn, note["id"], archived=True
        )
        self.assertTrue(archived["archived"])
        self.assertEqual(
            annotations.list_annotations(self.conn, self.objective["id"]), []
        )
        self.assertEqual(
            len(annotations.list_annotations(
                self.conn, self.objective["id"], include_archived=True
            )),
            1,
        )

    def test_stale_or_unrelated_source_is_rejected(self):
        with self.assertRaises(ApiError):
            annotations.create_annotation(
                self.conn,
                self.objective["id"],
                "highlight",
                section_stable_id=self.source["stable_id"],
                quote_text="mobile",
                content_sha256="0" * 64,
            )
        with self.assertRaises(ApiError):
            annotations.create_annotation(
                self.conn,
                self.objective["id"],
                "note",
                note_text="",
            )

    def test_export_contains_private_annotations(self):
        annotations.create_annotation(
            self.conn,
            self.objective["id"],
            "bookmark",
            section_stable_id=self.source["stable_id"],
            content_sha256=self.source["content_sha256"],
        )
        snapshot = api_logic.export_snapshot(self.conn, "http://localhost")
        self.assertEqual(len(snapshot["annotations"]), 1)
        self.assertEqual(snapshot["annotations"][0]["kind"], "bookmark")


if __name__ == "__main__":
    unittest.main()
