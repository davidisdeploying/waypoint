import tempfile
import unittest
from pathlib import Path

from lib import db, api_logic
from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from tests.fixtures import build_all_sources


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.sources = build_all_sources(Path(self.tmp.name))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _counts(self):
        tables = ["books", "sections", "objectives", "objective_chunk_links", "domains"]
        return {t: self.conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tables}

    def test_ingest_is_idempotent(self):
        ingest_all(self.conn, self.sources)
        first = self._counts()
        self.assertEqual(first["books"], 3)
        self.assertGreater(first["sections"], 0)
        self.assertGreater(first["objectives"], 0)

        ingest_all(self.conn, self.sources)
        second = self._counts()
        self.assertEqual(first, second, "re-ingesting unchanged sources must not duplicate rows")

    def test_certification_and_exam_spine_come_from_manifest(self):
        manifest = {
            "certification_code": "fixture-cert",
            "certification_name": "Fixture Certification",
            "exams": [
                {"code": "220-1201", "name": "Fixture Exam One"},
                {"code": "220-1202", "name": "Fixture Exam Two"},
            ],
        }
        ingest_all(self.conn, self.sources, manifest)
        cert = self.conn.execute(
            "SELECT code, name FROM certifications"
        ).fetchone()
        self.assertEqual(dict(cert), {
            "code": "fixture-cert",
            "name": "Fixture Certification",
        })
        exams = self.conn.execute(
            "SELECT code, name, sequence_order FROM exams ORDER BY sequence_order"
        ).fetchall()
        self.assertEqual(
            [dict(row) for row in exams],
            [
                {"code": "220-1201", "name": "Fixture Exam One", "sequence_order": 1},
                {"code": "220-1202", "name": "Fixture Exam Two", "sequence_order": 2},
            ],
        )

    def test_exam_and_domain_assignment(self):
        ingest_all(self.conn, self.sources)
        rows = self.conn.execute(
            "SELECT o.code, e.code AS exam_code, d.name AS domain_name FROM objectives o "
            "JOIN exams e ON e.id = o.exam_id LEFT JOIN domains d ON d.id = o.domain_id "
            "ORDER BY exam_code, o.code"
        ).fetchall()
        codes = {(r["exam_code"], r["code"]) for r in rows}
        self.assertIn(("220-1201", "1.1"), codes)
        self.assertIn(("220-1201", "2.1"), codes)  # from the guide book's inline 1201-2.1 marker
        self.assertIn(("220-1202", "1.1"), codes)
        domain_names = {r["domain_name"] for r in rows if r["domain_name"]}
        self.assertIn("Mobile Devices", domain_names)
        self.assertIn("Operating Systems", domain_names)

    def test_guide_and_review_link_to_same_objective_row(self):
        # 1201-1.1 appears in both the guide (inline) and review (bare + divider) fixtures;
        # both books' sections must link to the SAME objectives row, not duplicate it.
        ingest_all(self.conn, self.sources)
        row = self.conn.execute(
            "SELECT o.id FROM objectives o JOIN exams e ON e.id = o.exam_id "
            "WHERE e.code = '220-1201' AND o.code = '1.1'"
        ).fetchone()
        self.assertIsNotNone(row)
        book_slugs = {
            r["slug"] for r in self.conn.execute(
                "SELECT DISTINCT b.slug FROM objective_chunk_links l "
                "JOIN books b ON b.id = l.book_id WHERE l.objective_id = ?",
                (row["id"],),
            ).fetchall()
        }
        self.assertIn("fixture-guide", book_slugs)
        self.assertIn("fixture-review", book_slugs)

    def test_fts_search_returns_citations(self):
        ingest_all(self.conn, self.sources)
        results = api_logic.search_sections(self.conn, "networking")
        self.assertTrue(results)
        r = results[0]
        for field in ("stable_id", "title", "book_slug", "book_title", "snippet"):
            self.assertIn(field, r)
        self.assertTrue(r["stable_id"].startswith("fixture-"))

    def test_plan_seeding_idempotent(self):
        ingest_all(self.conn, self.sources)
        first = seed_plan(self.conn)
        second = seed_plan(self.conn)
        self.assertEqual(first["weeks"], second["weeks"])
        self.assertEqual(second["tasks"], 0, "re-seeding an already-seeded plan must not add duplicate tasks")
        total_tasks = self.conn.execute("SELECT COUNT(*) AS n FROM plan_tasks").fetchone()["n"]
        self.assertEqual(total_tasks, first["tasks"])


if __name__ == "__main__":
    unittest.main()
