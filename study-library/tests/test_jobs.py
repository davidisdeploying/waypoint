import unittest

from lib import db, jobs


class TestLibraryJobs(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_enqueue_is_idempotent_and_claim_is_serial(self):
        payload = {
            "idempotency_key": "book-sha256-abc",
            "kind": "convert_index",
            "source_path": "/allowed/book.epub",
            "output_path": "/allowed/output",
            "book_slug": "network-plus-guide",
            "book_kind": "supplemental",
        }
        first = jobs.enqueue(self.conn, **payload)
        second = jobs.enqueue(self.conn, **payload)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "queued")

        claimed = jobs.claim_next(self.conn)
        self.assertEqual(claimed["id"], first["id"])
        self.assertEqual(claimed["status"], "converting")
        self.assertIsNone(jobs.claim_next(self.conn))

    def test_job_progress_and_result_are_observable(self):
        job = jobs.enqueue(
            self.conn,
            idempotency_key="book-sha256-def",
            kind="reindex",
            source_path="/allowed/book.epub",
            output_path="/allowed/output",
            book_slug="security-plus-guide",
            book_kind="guide",
        )
        jobs.claim_next(self.conn)
        jobs.transition(
            self.conn, job["id"], "indexing", "indexing", "Building FTS5."
        )
        finished = jobs.transition(
            self.conn,
            job["id"],
            "succeeded",
            "ready",
            "Ready.",
            result={"sections": 42},
        )
        self.assertEqual(finished["result"], {"sections": 42})
        self.assertIsNotNone(finished["finished_at"])
        self.assertEqual(jobs.list_recent(self.conn)[0]["phase"], "ready")


if __name__ == "__main__":
    unittest.main()
