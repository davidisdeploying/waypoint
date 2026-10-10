import tempfile
import unittest
from pathlib import Path

from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from lib import coach, db
from lib.api_logic import ApiError
from tests.fixtures import build_guide_source, build_review_source


class TestStudyCoach(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(str(Path(self.tmp.name) / "study.db"))
        db.init_db(self.conn)
        ingest_all(
            self.conn,
            [
                build_guide_source(Path(self.tmp.name)),
                build_review_source(Path(self.tmp.name)),
            ],
        )
        seed_plan(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_subscription_answer_is_grounded_and_question_bank_is_absent(self):
        captured = {}
        citation = coach.api_logic.search_sections(
            self.conn, "mobile devices", limit=1
        )[0]["stable_id"]

        def runner(prompt):
            captured["prompt"] = prompt
            return {
                "title": "Today",
                "summary": "Review the current topic.",
                "steps": ["Read the cited section.", "Explain it aloud."],
                "check_yourself": ["What is the main idea?"],
                "citations": [citation],
                "caveat": "This is study guidance, not proof of mastery.",
            }

        response = coach.ask(
            self.conn, {"mode": "today", "question": "mobile devices"}, runner=runner
        )
        self.assertEqual(response["provider_label"], "Claude Max subscription")
        self.assertFalse(response["privacy"]["tools_enabled"])
        self.assertFalse(response["privacy"]["practice_bank_included"])
        self.assertNotIn("correct_answers_json", captured["prompt"])
        self.assertNotIn("prompt_snapshot", captured["prompt"])
        self.assertNotIn('"explanation"', captured["prompt"])
        self.assertEqual(len(response["answer"]["citations"]), 1)

    def test_rejects_citation_not_present_in_packet(self):
        def runner(_prompt):
            return {
                "title": "Bad citation",
                "summary": "No.",
                "steps": [],
                "check_yourself": [],
                "citations": ["invented-section"],
                "caveat": "No.",
            }

        with self.assertRaises(ApiError) as ctx:
            coach.ask(self.conn, {"mode": "today"}, runner=runner)
        self.assertEqual(ctx.exception.status, 502)

    def test_question_is_required_and_bounded(self):
        with self.assertRaises(ApiError) as ctx:
            coach.ask(self.conn, {"mode": "ask"}, runner=lambda _: {})
        self.assertEqual(ctx.exception.status, 400)

    def test_natural_language_question_becomes_safe_fts_query(self):
        query = coach._safe_search_query(
            "What should I know about USB-C, USB 3.2, and CompTIA A+?"
        )
        self.assertEqual(query, '"usb-c" OR "usb" OR "3.2" OR "comptia"')
        self.assertNotIn("?", query)
        with self.assertRaises(ApiError) as ctx:
            coach.ask(
                self.conn,
                {"mode": "ask", "question": "x" * (coach.MAX_QUESTION_CHARS + 1)},
                runner=lambda _: {},
            )
        self.assertEqual(ctx.exception.status, 400)


if __name__ == "__main__":
    unittest.main()
