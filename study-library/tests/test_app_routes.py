"""Live-server smoke checks: CSRF/same-origin enforcement on every diagnostics
mutation route, and answer redaction over real HTTP (not just direct calls
into lib.diagnostics)."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import app as app_module
from lib import coach
from lib import db
from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from ingest.diagnostics_importer import import_questions, seed_diagnostic_scopes
from tests.fixtures import build_review_source, build_diagnostics_practice_source


class TestAppRoutesCsrf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = str(Path(cls.tmp.name) / "test.db")
        conn = db.connect(cls.db_path)
        db.init_db(conn)
        review_src = build_review_source(Path(cls.tmp.name))
        diag_src = build_diagnostics_practice_source(Path(cls.tmp.name))
        ingest_all(conn, [review_src, diag_src])
        seed_plan(conn)
        import_questions(conn)
        seed_diagnostic_scopes(conn)
        scope = conn.execute(
            "SELECT id, exam_id, domain_id FROM diagnostic_scopes WHERE slug = 'aplus-week1-domain-1'"
        ).fetchone()
        ts = "2026-01-01T00:00:00+00:00"
        for i in range(20):
            conn.execute(
                "INSERT INTO question_bank(stable_id, exam_id, domain_id, objective_id, mapping_granularity, "
                "question_book_slug, question_section_id, question_number, answer_book_slug, answer_section_id, "
                "prompt, options_json, correct_answers_json, explanation, provenance, content_hash, "
                "requires_figure, critical, active, created_at, updated_at) "
                "VALUES (?, ?, ?, NULL, 'domain', 'aplus-practice-tests', NULL, ?, 'aplus-practice-tests', NULL, "
                "?, ?, '[0]', 'exp', 'prov', ?, 0, 0, 1, ?, ?)",
                (f"route-test-{i}", scope["exam_id"], scope["domain_id"], 7000 + i,
                 f"Q{i}?", json.dumps(["a", "b", "c", "d"]), f"hash-{i}", ts, ts),
            )
        conn.execute(
            "UPDATE diagnostic_scopes SET enabled = 1, question_target = 5, min_valid_questions = 2 WHERE id = ?",
            (scope["id"],),
        )
        conn.commit()
        cls.scope_id = scope["id"]
        conn.close()

        import os
        os.environ["STUDY_LIBRARY_DB"] = cls.db_path
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app_module.Handler)
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def _get(self, path, headers=None):
        request = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(request) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def _post(self, path, payload, csrf=None, origin=None, extra_headers=None):
        headers = {"Content-Type": "application/json"}
        if csrf is not None:
            headers["X-Csrf-Token"] = csrf
        if origin is not None:
            headers["Origin"] = origin
        headers.update(extra_headers or {})
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode(), method="POST", headers=headers,
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_scope_start_rejected_without_csrf(self):
        status, body = self._post(f"/api/diagnostics/scopes/{self.scope_id}/start", {"mode": "diagnostic"})
        self.assertEqual(status, 403)

    def test_scope_start_rejected_with_wrong_origin(self):
        _, csrf_body = self._get("/api/csrf-token")
        status, body = self._post(
            f"/api/diagnostics/scopes/{self.scope_id}/start", {"mode": "diagnostic"},
            csrf=csrf_body["csrf_token"], origin="http://evil.example",
        )
        self.assertEqual(status, 403)

    def test_full_flow_with_csrf_redacts_until_submit(self):
        _, csrf_body = self._get("/api/csrf-token")
        csrf = csrf_body["csrf_token"]

        status, attempt = self._post(
            f"/api/diagnostics/scopes/{self.scope_id}/start", {"mode": "diagnostic"}, csrf=csrf,
        )
        self.assertEqual(status, 201)
        self.assertTrue(attempt["answers_redacted"])
        for r in attempt["responses"]:
            self.assertNotIn("correct_answers", r)

        status, fetched = self._get(f"/api/diagnostics/attempts/{attempt['id']}")
        self.assertEqual(status, 200)
        self.assertTrue(fetched["answers_redacted"])

        responses = [
            {"question_id": r["question_id"], "selected": [0], "confidence": "high"}
            for r in attempt["responses"]
        ]
        status, result = self._post(
            f"/api/diagnostics/attempts/{attempt['id']}/submit", {"responses": responses}, csrf=csrf,
        )
        self.assertEqual(status, 200)
        self.assertIn("passed", result)

        status, results2 = self._get(f"/api/diagnostics/attempts/{attempt['id']}/results")
        self.assertEqual(status, 200)
        self.assertIn("gaps", results2)

    def test_remediation_mark_reviewed_requires_csrf(self):
        status, _ = self._post("/api/remediation/1", {})
        self.assertEqual(status, 403)

    def test_abandon_requires_csrf_and_keeps_answers_redacted(self):
        _, csrf_body = self._get("/api/csrf-token")
        csrf = csrf_body["csrf_token"]
        status, attempt = self._post(
            f"/api/diagnostics/scopes/{self.scope_id}/start",
            {"mode": "diagnostic"},
            csrf=csrf,
        )
        if status == 409:
            _, scope = self._get(f"/api/diagnostics/scopes/{self.scope_id}")
            current = next(a for a in scope["recent_attempts"] if a["state"] == "in_progress")
            _, attempt = self._get(f"/api/diagnostics/attempts/{current['id']}")
        status, _ = self._post(
            f"/api/diagnostics/attempts/{attempt['id']}/abandon", {}
        )
        self.assertEqual(status, 403)
        status, abandoned = self._post(
            f"/api/diagnostics/attempts/{attempt['id']}/abandon", {}, csrf=csrf
        )
        self.assertEqual(status, 200)
        self.assertEqual(abandoned["state"], "abandoned")
        self.assertTrue(abandoned["answers_redacted"])
        for response in abandoned["responses"]:
            self.assertNotIn("correct_answers", response)

    def test_study_next_read_route(self):
        status, body = self._get("/api/study-next")
        self.assertEqual(status, 200)
        self.assertIn("primary", body)
        self.assertIn("items", body)
        self.assertIn("counts", body)

    def test_learning_architecture_read_routes(self):
        status, spines = self._get("/api/certification-spines")
        self.assertEqual(status, 200)
        self.assertEqual(spines["counts"]["certifications"], 6)
        self.assertEqual(spines["counts"]["exam_sittings"], 7)

        status, aplus = self._get("/api/certification-spines/aplus")
        self.assertEqual(status, 200)
        self.assertEqual(aplus["scope_status"], "published_pack")

        status, career = self._get("/api/career-context?certification=secplus")
        self.assertEqual(status, 200)
        self.assertEqual(career["alignment"]["relevance"], "supporting")

        status, result = self._get("/api/readiness?exam=220-1201")
        self.assertEqual(status, 200)
        self.assertFalse(result["ready_to_schedule"])
        self.assertIsNone(result["policy"]["composite_score"])

    def test_learning_event_requires_csrf_and_updates_objective(self):
        _, objectives = self._get("/api/objectives?exam=220-1201")
        objective_id = objectives["objectives"][0]["id"]
        payload = {
            "objective_id": objective_id,
            "event_type": "lesson_completed",
            "event_key": f"route-objective:{objective_id}:lesson-completed",
        }
        status, _ = self._post("/api/learning/events", payload)
        self.assertEqual(status, 403)
        _, csrf_body = self._get("/api/csrf-token")
        status, state = self._post(
            "/api/learning/events", payload, csrf=csrf_body["csrf_token"]
        )
        self.assertEqual(status, 200)
        self.assertTrue(state["lesson_completed"])
        status, detail = self._get(f"/api/objectives/{objective_id}")
        self.assertEqual(status, 200)
        self.assertTrue(detail["learning"]["lesson_completed"])
        self.assertIsNotNone(detail["retention"])
        self.assertEqual(detail["retention"]["interval_days"], 1)
        self.assertEqual(detail["mastery"]["status"], "studied")
        self.assertEqual(detail["mastery"]["evidence"]["objective_assessments"], 0)
        status, queue = self._get("/api/retention?horizon_days=7")
        self.assertEqual(status, 200)
        self.assertEqual(queue["upcoming_count"], 1)
        status, _ = self._post(
            "/api/retention/reviews",
            {"objective_id": objective_id, "rating": "good"},
        )
        self.assertEqual(status, 403)
        status, retention_state = self._post(
            "/api/retention/reviews",
            {
                "objective_id": objective_id,
                "rating": "good",
                "event_key": f"route-objective:{objective_id}:review:1",
            },
            csrf=csrf_body["csrf_token"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(retention_state["interval_days"], 3)
        self.assertEqual(retention_state["review_count"], 1)

    def test_annotations_require_csrf_and_remain_recoverable(self):
        _, objectives = self._get("/api/objectives?exam=220-1201")
        objective_id = objectives["objectives"][0]["id"]
        _, detail = self._get(f"/api/objectives/{objective_id}")
        source = detail["evidence"][0]
        payload = {
            "objective_id": objective_id,
            "kind": "highlight",
            "section_stable_id": source["stable_id"],
            "quote_text": "mobile device",
            "note_text": "My note.",
            "content_sha256": source["content_sha256"],
            "client_key": "route-highlight:1",
        }
        status, _ = self._post("/api/annotations", payload)
        self.assertEqual(status, 403)
        _, csrf_body = self._get("/api/csrf-token")
        status, created = self._post(
            "/api/annotations", payload, csrf=csrf_body["csrf_token"]
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["anchor_status"], "exact")
        status, listed = self._get(
            f"/api/annotations?objective_id={objective_id}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["annotations"]), 1)
        status, archived = self._post(
            f"/api/annotations/{created['id']}",
            {"archived": True},
            csrf=csrf_body["csrf_token"],
        )
        self.assertEqual(status, 200)
        self.assertTrue(archived["archived"])
        _, listed = self._get(f"/api/annotations?objective_id={objective_id}")
        self.assertEqual(listed["annotations"], [])

    def test_labs_require_csrf_and_complete_with_evidence(self):
        conn = db.connect(self.db_path)
        objective_id = conn.execute(
            "SELECT id FROM objectives ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        conn.close()
        payload = {
            "objective_id": objective_id,
            "title": "Memory replacement",
            "goal_text": "Replace and verify laptop memory.",
            "environment_text": "Practice laptop",
            "client_key": "route-lab-1",
        }
        status, _ = self._post("/api/labs", payload)
        self.assertEqual(status, 403)
        _, csrf_body = self._get("/api/csrf-token")
        status, created = self._post(
            "/api/labs", payload, csrf=csrf_body["csrf_token"]
        )
        self.assertEqual(status, 201)
        status, completed = self._post(
            f"/api/labs/{created['id']}",
            {
                "status": "completed",
                "evidence_text": "Firmware and OS both report 16 GB.",
                "reflection_text": "Verified seating and reran diagnostics.",
                "completion_level": "referenced",
            },
            csrf=csrf_body["csrf_token"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["completion_level"], "referenced")
        _, listed = self._get(f"/api/labs?objective_id={objective_id}")
        self.assertEqual(listed["summary"]["completed"], 1)

    def test_lab_catalog_launch_requires_csrf_and_returns_snapshot(self):
        status, catalog = self._get("/api/lab-catalog")
        self.assertEqual(status, 200)
        self.assertGreater(catalog["summary"]["available"], 0)
        template = catalog["templates"][0]
        status, _ = self._post(
            f"/api/lab-catalog/{template['slug']}/launch",
            {"client_key": "route-catalog-lab-1"},
        )
        self.assertEqual(status, 403)
        _, csrf_body = self._get("/api/csrf-token")
        status, lab = self._post(
            f"/api/lab-catalog/{template['slug']}/launch",
            {"client_key": "route-catalog-lab-1"},
            csrf=csrf_body["csrf_token"],
        )
        self.assertEqual(status, 201)
        self.assertEqual(lab["template_slug"], template["slug"])
        self.assertGreater(len(lab["template"]["steps"]), 0)

    def test_daily_session_http_lifecycle_requires_csrf_and_returns_recap(self):
        status, _ = self._post(
            "/api/daily-session/start", {"target_minutes": 25}
        )
        self.assertEqual(status, 403)
        _, csrf_body = self._get("/api/csrf-token")
        csrf = csrf_body["csrf_token"]
        status, active = self._post(
            "/api/daily-session/start", {"target_minutes": 25}, csrf=csrf
        )
        self.assertEqual(status, 201)
        self.assertEqual(active["status"], "active")

        status, with_event = self._post(
            "/api/daily-session/events",
            {
                "event_type": "reading_opened",
                "label": "Mobile Devices",
                "event_key": "route-reading",
            },
            csrf=csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(with_event["events"]), 1)

        status, paused = self._post(
            f"/api/daily-session/{active['id']}/pause",
            {"occurred_at": active["started_at"]},
            csrf=csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(paused["tracking_state"], "paused")
        status, resumed = self._post(
            f"/api/daily-session/{active['id']}/resume", {}, csrf=csrf
        )
        self.assertEqual(status, 200)
        self.assertEqual(resumed["tracking_state"], "running")

        status, finished = self._post(
            f"/api/daily-session/{active['id']}/finish",
            {"notes": "Useful session."},
            csrf=csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["recap"]["counts"]["reading_opened"], 1)

        status, overview = self._get("/api/daily-session")
        self.assertEqual(status, 200)
        self.assertIsNone(overview["active"])
        self.assertEqual(overview["recent"][0]["id"], active["id"])

        status, history = self._get("/api/daily-session/history?limit=50")
        self.assertEqual(status, 200)
        self.assertEqual(history["sessions"][0]["id"], active["id"])
        status, _ = self._post(f"/api/daily-session/{active['id']}/delete", {})
        self.assertEqual(status, 403)
        status, deleted = self._post(
            f"/api/daily-session/{active['id']}/delete", {}, csrf=csrf
        )
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])
        _, history = self._get("/api/daily-session/history?limit=50")
        self.assertEqual(history["sessions"], [])

    def test_encoded_stable_id_opens_cited_section(self):
        _, search = self._get("/api/search?q=devices&limit=1")
        stable_id = search["results"][0]["stable_id"]
        encoded = urllib.parse.quote(stable_id, safe="")

        status, section = self._get(f"/api/sections/{encoded}")

        self.assertEqual(status, 200)
        self.assertEqual(section["stable_id"], stable_id)

    def test_service_credential_protects_api_but_not_health(self):
        original = app_module.SERVICE_TOKEN
        app_module.SERVICE_TOKEN = "test-service-token"
        try:
            status, health = self._get("/api/health")
            self.assertEqual(status, 200)
            self.assertEqual(health["service_auth"], "required")

            status, _ = self._get("/api/books")
            self.assertEqual(status, 401)

            status, books = self._get(
                "/api/books",
                headers={"X-Waypoint-Service-Token": "test-service-token"},
            )
            self.assertEqual(status, 200)
            self.assertIn("books", books)
        finally:
            app_module.SERVICE_TOKEN = original

    def test_waypoint_state_accepts_only_trusted_gateway_mutation(self):
        state = {
            "meta": {"name": "David", "startDate": "2026-09-01", "wguStartDate": "2027-08-01"},
            "certs": [{
                "id": "aplus", "order": 1, "name": "CompTIA A+",
                "kind": "CompTIA", "code": "220-1201 / 220-1202",
                "exam": "", "pass": "", "status": "studying",
                "price": 548, "cu": 8, "wlo": 5, "whi": 6,
                "started": "", "actualHours": None, "estHoursLow": 140, "estHoursHigh": 200,
            }],
            "courses": [], "log": [],
            "studyEndpoint": "/api/waypoint/summary",
            "studySummary": None, "studySummaryReceivedAt": None,
        }
        _, current = self._get("/api/waypoint/state")
        current_revision = current.get("revision", 0) if isinstance(current, dict) else 0
        original = app_module.SERVICE_TOKEN
        app_module.SERVICE_TOKEN = "test-service-token"
        try:
            status, _ = self._post(
                "/api/waypoint/state",
                {"expected_revision": current_revision, "state": state},
                origin=self.base,
                extra_headers={"X-Waypoint-Service-Token": "test-service-token"},
            )
            self.assertEqual(status, 403)

            status, saved = self._post(
                "/api/waypoint/state",
                {"expected_revision": current_revision, "state": state},
                origin=self.base,
                extra_headers={
                    "X-Waypoint-Service-Token": "test-service-token",
                    "X-Waypoint-Trusted-Mutation": "1",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(saved["revision"], current_revision + 1)
        finally:
            app_module.SERVICE_TOKEN = original

    def test_timeline_projects_from_the_saved_waypoint_state(self):
        state = {
            "meta": {"name": "David", "startDate": "2026-09-01", "wguStartDate": "2027-08-01"},
            "certs": [
                {
                    "id": "aplus", "order": 1, "name": "CompTIA A+",
                    "kind": "CompTIA", "code": "220-1201 / 220-1202",
                    "exam": "", "pass": "", "status": "studying",
                    "price": 548, "cu": 8, "wlo": 5, "whi": 6,
                    "started": "2020-01-01", "actualHours": None,
                    "estHoursLow": 140, "estHoursHigh": 200,
                },
                {
                    "id": "netplus", "order": 2, "name": "Network+",
                    "kind": "CompTIA", "code": "N10-009",
                    "exam": "", "pass": "", "status": "todo",
                    "price": 369, "cu": 4, "wlo": 5, "whi": 6,
                    "started": "", "actualHours": None,
                    "estHoursLow": 70, "estHoursHigh": 110,
                },
            ],
            "courses": [], "log": [],
            "studyEndpoint": "/api/waypoint/summary",
            "studySummary": None, "studySummaryReceivedAt": None,
        }
        _, current = self._get("/api/waypoint/state")
        current_revision = current.get("revision", 0) if isinstance(current, dict) else 0
        original = app_module.SERVICE_TOKEN
        app_module.SERVICE_TOKEN = "test-service-token"
        try:
            status, _ = self._post(
                "/api/waypoint/state",
                {"expected_revision": current_revision, "state": state},
                origin=self.base,
                extra_headers={
                    "X-Waypoint-Service-Token": "test-service-token",
                    "X-Waypoint-Trusted-Mutation": "1",
                },
            )
            self.assertEqual(status, 200)
        finally:
            app_module.SERVICE_TOKEN = original

        # A non-zero pace is required for projectedFinish (and therefore any weeks) to
        # compute at all -- this fresh test DB has no weekly goal set otherwise.
        _, csrf_body = self._get("/api/csrf-token")
        status, _ = self._post(
            "/api/study-goal", {"daily_target_minutes": 60}, csrf=csrf_body["csrf_token"], origin=self.base,
        )
        self.assertEqual(status, 200)

        status, payload = self._get("/api/timeline")
        self.assertEqual(status, 200)
        entries = {e["id"]: e for e in payload["entries"]}
        self.assertEqual(entries["aplus"]["status"], "studying")
        self.assertEqual(entries["netplus"]["status"], "todo")
        self.assertIsNotNone(entries["netplus"]["projectedStart"])
        self.assertIn("pace_hours_per_week", payload)
        self.assertEqual(payload["target_date"], "2027-08-01")
        self.assertIsNotNone(payload["projected_all_complete"])
        self.assertIsInstance(payload["schedule_delta_days"], int)
        self.assertGreater(payload["required_pace_hours_per_week"], 0)

        # A+ has real ingested content (from setUpClass's book/plan fixtures) -- its weeks
        # come from the real plan, not a domain guess.
        aplus_weeks = entries["aplus"]["weeks"]
        self.assertTrue(aplus_weeks)
        self.assertTrue(all(w["source"] == "real" for w in aplus_weeks))
        self.assertTrue(all(w["topic"] for w in aplus_weeks))

        # Network+ has no ingested content -- its weeks are domain-derived and unstarted.
        netplus_weeks = entries["netplus"]["weeks"]
        self.assertTrue(netplus_weeks)
        self.assertTrue(all(w["source"] == "projected" for w in netplus_weeks))
        self.assertTrue(all(w["progress_percent"] == 0 for w in netplus_weeks))
        self.assertIn("Networking Concepts", [w["topic"] for w in netplus_weeks])

    def test_progress_and_adaptive_curriculum_read_routes(self):
        status, progress = self._get("/api/progress")
        self.assertEqual(status, 200)
        self.assertIn("current_week_tasks", progress)
        self.assertIn("domain_mastery", progress)

        status, mastery_map = self._get("/api/mastery-map?exam=220-1201")
        self.assertEqual(status, 200)
        self.assertEqual(mastery_map["exams"][0]["code"], "220-1201")
        self.assertIn("evidence_note", mastery_map)

        status, curriculum = self._get(
            "/api/adaptive-curriculum?days=5&minutes_per_day=30"
        )
        self.assertEqual(status, 200)
        self.assertEqual(curriculum["days"], 5)
        self.assertEqual(curriculum["minutes_per_day"], 30)

        status, analytics = self._get("/api/analytics?days=30")
        self.assertEqual(status, 200)
        self.assertEqual(len(analytics["timeline"]), 30)
        self.assertIn("no_composite_note", analytics)

    def test_hours_since_requires_a_since_param_and_reports_zero_with_none_logged(self):
        status, body = self._get("/api/hours-since")
        self.assertEqual(status, 400)

        status, body = self._get("/api/hours-since?since=2020-01-01T00:00:00Z")
        self.assertEqual(status, 200)
        self.assertEqual(body["since"], "2020-01-01T00:00:00Z")
        self.assertEqual(body["hours"], 0.0)

    def test_ai_context_read_route_is_bounded(self):
        status, packet = self._get("/api/ai/context?q=devices&limit=2&max_chars=2000")
        self.assertEqual(status, 200)
        self.assertEqual(packet["schema_version"], "1")
        self.assertLessEqual(packet["retrieval"]["citation_count"], 2)
        self.assertIn("adaptive_curriculum", packet)

    def test_coach_route_requires_csrf(self):
        status, body = self._post(
            "/api/coach/ask", {"mode": "ask", "question": "What is USB?"}
        )
        self.assertEqual(status, 403)

    def test_coach_route_uses_subscription_runner_and_redacts_practice_bank(self):
        _, csrf_body = self._get("/api/csrf-token")
        original = coach._run_claude

        def fake_runner(_prompt):
            return {
                "title": "Focused review",
                "summary": "Use the current cited section.",
                "steps": ["Read and recall."],
                "check_yourself": ["Explain the concept."],
                "citations": [],
                "caveat": "No mastery claim.",
            }

        coach._run_claude = fake_runner
        try:
            status, body = self._post(
                "/api/coach/ask",
                {"mode": "today", "provider": "claude"},
                csrf=csrf_body["csrf_token"],
            )
        finally:
            coach._run_claude = original
        self.assertEqual(status, 200)
        self.assertEqual(body["provider_label"], "Claude Max subscription")
        self.assertFalse(body["privacy"]["practice_bank_included"])


if __name__ == "__main__":
    unittest.main()
