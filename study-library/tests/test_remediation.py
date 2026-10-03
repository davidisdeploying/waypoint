import tempfile
import unittest
from pathlib import Path

from lib import db
from lib import remediation
from ingest.ingest import ingest_all
from tests.fixtures import build_review_source, build_guide_source, build_practice_source


class TestRelevantReadings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        sources = [
            build_review_source(Path(self.tmp.name)),
            build_guide_source(Path(self.tmp.name)),
            build_practice_source(Path(self.tmp.name)),
        ]
        ingest_all(self.conn, sources)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_excludes_practice_book(self):
        domain = self.conn.execute(
            "SELECT id, exam_id FROM domains WHERE name = 'Mobile Devices' LIMIT 1"
        ).fetchone()
        readings = remediation.find_relevant_readings(
            self.conn, domain["exam_id"], domain["id"], "mobile devices hardware"
        )
        for r in readings:
            self.assertNotEqual(r["book_slug"], "aplus-practice-tests")

    def test_bounded_and_deduped(self):
        domain = self.conn.execute(
            "SELECT id, exam_id FROM domains WHERE name = 'Mobile Devices' LIMIT 1"
        ).fetchone()
        readings = remediation.find_relevant_readings(
            self.conn, domain["exam_id"], domain["id"], "mobile devices hardware", limit=3
        )
        self.assertLessEqual(len(readings), 3)
        hashes = [r["content_hash"] for r in readings]
        self.assertEqual(len(hashes), len(set(hashes)), "readings must be deduped by content hash")
        for r in readings:
            for field in ("book_slug", "book_title", "section_stable_id", "section_title",
                          "snippet", "content_hash", "retrieval_basis"):
                self.assertIn(field, r)

    def test_no_terms_returns_empty(self):
        readings = remediation.find_relevant_readings(self.conn, 1, 1, "a an the of is")
        self.assertEqual(readings, [])

    def test_priority_phrase_stops_before_loose_fallback(self):
        domain = self.conn.execute(
            "SELECT id, exam_id FROM domains WHERE name = 'Mobile Devices' LIMIT 1"
        ).fetchone()
        relevant = self.conn.execute(
            "SELECT s.id FROM sections s JOIN books b ON b.id=s.book_id "
            "WHERE b.slug='fixture-review' AND s.title LIKE '%Mobile Devices%'"
        ).fetchone()
        irrelevant = self.conn.execute(
            "SELECT s.id FROM sections s JOIN books b ON b.id=s.book_id "
            "WHERE b.slug='fixture-guide' AND s.title LIKE '%Networking%'"
        ).fetchone()
        self.conn.execute(
            "UPDATE sections SET content = content || "
            "' A port replicator connects peripheral devices without the laptop present. ' "
            "WHERE id = ?",
            (relevant["id"],),
        )
        self.conn.execute(
            "UPDATE sections SET content = content || "
            "' Laptop ports and devices are mentioned loosely here. ' WHERE id = ?",
            (irrelevant["id"],),
        )
        self.conn.commit()

        readings = remediation.find_relevant_readings(
            self.conn,
            domain["exam_id"],
            domain["id"],
            "A laptop needs ports for devices and connectivity.",
            priority_text="Port replicator",
        )

        self.assertGreaterEqual(len(readings), 1)
        self.assertTrue(all("answer-focused local-window" in r["retrieval_basis"] for r in readings))
        self.assertTrue(all("Networking" not in r["section_title"] for r in readings))

    def test_recall_prompt_and_lab_scaffold_are_labeled_and_deterministic(self):
        prompt = remediation.build_recall_prompt("What connector is X?", ["USB-C", "USB-A"], [0])
        self.assertIn("USB-C", prompt)
        self.assertIn("Active recall", prompt)
        scaffold = remediation.build_lab_scaffold("Mobile Devices")
        self.assertIn("Scaffold", scaffold)
        self.assertIn("not an official lab", scaffold)
        # deterministic: same inputs -> same output, no randomness/LLM involved
        self.assertEqual(scaffold, remediation.build_lab_scaffold("Mobile Devices"))

    def test_scope_restriction_returns_each_section_once(self):
        """Regression: scope restriction is a semi-join, not a fan-out join.

        Restricting by domain/exam used to JOIN through objective_chunk_links,
        which repeats a section once per linked objective, and lean on SELECT
        DISTINCT to collapse the duplicates -- comparing whole section bodies to
        do it. If the semi-join is ever turned back into a join without
        DISTINCT, sections with several linked objectives silently repeat and
        crowd real results out of the LIMIT.
        """
        domain = self.conn.execute(
            "SELECT id, exam_id FROM domains WHERE name = 'Mobile Devices' LIMIT 1"
        ).fetchone()
        multi_linked = self.conn.execute(
            "SELECT ocl.section_id, COUNT(*) AS links FROM objective_chunk_links ocl "
            "JOIN objectives ob ON ob.id = ocl.objective_id WHERE ob.domain_id = ? "
            "GROUP BY ocl.section_id ORDER BY links DESC LIMIT 1",
            (domain["id"],),
        ).fetchone()
        self.assertIsNotNone(multi_linked, "fixture should link objectives to sections")

        fts_query = remediation._fts_query(["mobile", "devices", "hardware", "laptop"])
        for label, domain_id, exam_id in (
            ("domain-linked", domain["id"], None),
            ("exam-constrained", None, domain["exam_id"]),
            ("corpus fallback", None, None),
        ):
            rows = remediation._fts_search(self.conn, fts_query, domain_id, exam_id, 40)
            ids = [row["stable_id"] for row in rows]
            self.assertEqual(
                len(ids), len(set(ids)), "%s scope returned a section more than once" % label
            )

    def test_can_qualify_only_rejects_sections_precise_matching_would_reject(self):
        """The pre-filter must never reject a section that would have been kept.

        _can_qualify skips the expensive window scan for sections that cannot
        clear _precise_candidates' bar. A window is a slice of the section, so
        it can never hold more distinct terms than the whole section does --
        but if that bound is ever loosened, real readings disappear silently
        rather than failing loudly.
        """
        priority = ["replicator"]
        context = ["laptop", "ports", "devices"]

        # Section containing everything: must survive the gate.
        rich = "a port replicator connects laptop ports and devices at the desk"
        self.assertTrue(remediation._can_qualify(rich, priority, context))

        # Missing the single priority term: unreachable bar, safe to skip.
        no_priority = "laptop ports and devices are discussed at length here"
        self.assertFalse(remediation._can_qualify(no_priority, priority, context))

        # Priority term present but only one context term: needs two.
        thin_context = "a port replicator sits on the desk"
        self.assertFalse(remediation._can_qualify(thin_context, priority, context))

        # With no priority terms at all the bar is four context terms.
        four = ["laptop", "ports", "devices", "desk"]
        self.assertTrue(
            remediation._can_qualify("laptop ports devices desk", [], four)
        )
        self.assertFalse(
            remediation._can_qualify("laptop ports devices", [], four)
        )

    def test_repeated_lookups_reuse_compiled_term_patterns(self):
        """Term patterns are compiled once and cached, not rebuilt per call."""
        first = remediation._term_pattern("replicator")
        second = remediation._term_pattern("replicator")
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
