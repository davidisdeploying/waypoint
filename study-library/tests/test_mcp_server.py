import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from lib import db
from tests.fixtures import build_all_sources


class TestStudyCoachMcp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "mcp.db")
        conn = db.connect(self.db_path)
        db.init_db(conn)
        ingest_all(conn, build_all_sources(Path(self.tmp.name)))
        seed_plan(conn)
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, messages):
        env = dict(os.environ)
        env["STUDY_LIBRARY_DB"] = self.db_path
        proc = subprocess.run(
            [sys.executable, "mcp_server.py"],
            input="\n".join(json.dumps(m) for m in messages) + "\n",
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )
        self.assertEqual(proc.stderr, "")
        return [json.loads(line) for line in proc.stdout.splitlines()]

    def test_initialize_list_and_status_call(self):
        responses = self._run(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "study_status", "arguments": {}},
                },
            ]
        )
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
        tools = responses[1]["result"]["tools"]
        self.assertEqual(len(tools), 5)
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in tools))
        status = responses[2]["result"]["structuredContent"]
        self.assertEqual(status["progress"]["current_week"], 1)
        self.assertIn("study_next", status)

    def test_search_is_cited_bounded_and_excludes_practice(self):
        response = self._run(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "search_book_corpus",
                        "arguments": {"query": "devices", "exam": "220-1201", "limit": 3},
                    },
                }
            ]
        )[0]
        retrieval = response["result"]["structuredContent"]["retrieval"]
        self.assertTrue(retrieval["citations"])
        self.assertLessEqual(retrieval["citation_count"], 3)
        self.assertTrue(all("practice" not in c["book_slug"] for c in retrieval["citations"]))
        self.assertTrue(all(c["stable_id"] for c in retrieval["citations"]))

    def test_read_section_refuses_practice_bank(self):
        conn = db.connect(self.db_path)
        practice_id = conn.execute(
            "SELECT s.stable_id FROM sections s JOIN books b ON b.id=s.book_id "
            "WHERE b.slug LIKE '%practice%' LIMIT 1"
        ).fetchone()["stable_id"]
        conn.close()
        response = self._run(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "read_book_section",
                        "arguments": {"stable_id": practice_id},
                    },
                }
            ]
        )[0]
        self.assertTrue(response["result"]["isError"])
        self.assertIn("excluded", response["result"]["content"][0]["text"])

    def test_bad_arguments_return_tool_error_without_traceback(self):
        response = self._run(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_adaptive_curriculum",
                        "arguments": {"days": 99},
                    },
                }
            ]
        )[0]
        self.assertTrue(response["result"]["isError"])
        self.assertIn("between 1 and 14", response["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
