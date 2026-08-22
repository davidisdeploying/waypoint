import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from pathlib import Path

from lib import db, api_logic, daily_sessions
from lib.api_logic import ApiError
from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from tests.fixtures import build_all_sources


class TestApiLogicWithData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        sources = build_all_sources(Path(self.tmp.name))
        ingest_all(self.conn, sources)
        seed_plan(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_update_plan_task_completion(self):
        task = self.conn.execute("SELECT id FROM plan_tasks ORDER BY id LIMIT 1").fetchone()
        updated = api_logic.update_plan_task(self.conn, task["id"], completed=True)
        self.assertEqual(updated["completed"], 1)
        self.assertIsNotNone(updated["completed_at"])

    def test_update_plan_task_rejects_bad_types(self):
        task = self.conn.execute("SELECT id FROM plan_tasks ORDER BY id LIMIT 1").fetchone()
        with self.assertRaises(ApiError):
            api_logic.update_plan_task(self.conn, task["id"], completed="yes")
        with self.assertRaises(ApiError):
            api_logic.update_plan_task(self.conn, task["id"], notes=12345)

    def test_update_plan_task_unknown_id_returns_none(self):
        self.assertIsNone(api_logic.update_plan_task(self.conn, 999999, completed=True))

    def test_create_attempt_validation(self):
        exam = self.conn.execute("SELECT id FROM exams LIMIT 1").fetchone()
        with self.assertRaises(ApiError):
            api_logic.create_attempt(self.conn, exam_id=None, score=1, total=1, occurred_at="x")
        with self.assertRaises(ApiError):
            api_logic.create_attempt(self.conn, exam_id=exam["id"], score=5, total=3, occurred_at="x")
        with self.assertRaises(ApiError):
            api_logic.create_attempt(self.conn, exam_id=exam["id"], score=-1, total=3, occurred_at="x")
        with self.assertRaises(ApiError):
            api_logic.create_attempt(self.conn, exam_id=999999, score=1, total=3, occurred_at="x")
        ok = api_logic.create_attempt(self.conn, exam_id=exam["id"], score=2, total=4, occurred_at="2026-01-01T00:00:00Z")
        self.assertEqual(ok["score"], 2)

    def test_create_session_validation(self):
        with self.assertRaises(ApiError):
            api_logic.create_session(self.conn, occurred_at=None, duration_minutes=30)
        with self.assertRaises(ApiError):
            api_logic.create_session(self.conn, occurred_at="2026-01-01T00:00:00Z", duration_minutes=0)
        with self.assertRaises(ApiError):
            api_logic.create_session(self.conn, occurred_at="2026-01-01T00:00:00Z", duration_minutes=99999)
        ok = api_logic.create_session(self.conn, occurred_at="2026-01-01T00:00:00Z", duration_minutes=45)
        self.assertEqual(ok["duration_minutes"], 45)

    def test_daily_session_lifecycle_builds_evidence_recap(self):
        primary = api_logic.get_study_next(self.conn, limit=1)["primary"]
        active = daily_sessions.start(self.conn, 25, primary)
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["target_minutes"], 25)

        same = daily_sessions.start(self.conn, 45, primary)
        self.assertEqual(same["id"], active["id"])
        self.assertEqual(same["target_minutes"], 25)

        daily_sessions.log_event(
            self.conn,
            "reading_opened",
            "Mobile device power",
            event_key="section:power",
        )
        daily_sessions.log_event(
            self.conn,
            "reading_opened",
            "Mobile device power",
            event_key="section:power",
        )
        daily_sessions.log_event(
            self.conn,
            "gap_reviewed",
            "AC adapter polarity",
            event_key="gap:1",
        )
        finished = daily_sessions.finish(
            self.conn, active["id"], notes="Polarity matters."
        )
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["recap"]["counts"]["reading_opened"], 1)
        self.assertEqual(finished["recap"]["counts"]["gap_reviewed"], 1)
        self.assertEqual(len(finished["events"]), 2)
        self.assertGreaterEqual(finished["duration_minutes"], 1)
        legacy = self.conn.execute(
            "SELECT * FROM study_sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertIn("Reviewed 1 missed question", legacy["notes"])

        summary = daily_sessions.overview(self.conn, primary)
        self.assertIsNone(summary["active"])
        self.assertEqual(summary["recent"][0]["id"], active["id"])

        recorded = daily_sessions.history(self.conn)
        self.assertEqual(recorded[0]["id"], active["id"])
        deleted = daily_sessions.delete_recorded(self.conn, active["id"])
        self.assertTrue(deleted["deleted"])
        self.assertEqual(daily_sessions.history(self.conn), [])
        self.assertEqual(daily_sessions.overview(self.conn, primary)["recent"], [])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0],
            0,
        )
        audit = self.conn.execute(
            "SELECT deleted_at FROM guided_study_sessions WHERE id = ?", (active["id"],)
        ).fetchone()
        self.assertIsNotNone(audit["deleted_at"])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM guided_study_events WHERE session_id = ?", (active["id"],)
            ).fetchone()[0],
            2,
        )

    def test_daily_session_rejects_invalid_mutations(self):
        primary = api_logic.get_study_next(self.conn, limit=1)["primary"]
        with self.assertRaises(ApiError):
            daily_sessions.start(self.conn, 0, primary)
        with self.assertRaises(ApiError):
            daily_sessions.log_event(self.conn, "reading_opened", "No session")
        active = daily_sessions.start(self.conn, 25, primary)
        with self.assertRaises(ApiError):
            daily_sessions.log_event(self.conn, "made_up", "Bad")
        abandoned = daily_sessions.abandon(self.conn, active["id"])
        self.assertEqual(abandoned["status"], "abandoned")
        with self.assertRaises(ApiError):
            daily_sessions.finish(self.conn, active["id"])

    def test_daily_session_counts_only_running_foreground_time(self):
        primary = api_logic.get_study_next(self.conn, limit=1)["primary"]
        started = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        with patch("lib.daily_sessions._utcnow", return_value=started):
            active = daily_sessions.start(self.conn, 25, primary)

        hidden = started + timedelta(minutes=5)
        # Simulate iOS delivering the pause after a long suspension. The
        # original foreground-loss timestamp, not delivery time, is credited.
        with patch("lib.daily_sessions._utcnow", return_value=started + timedelta(hours=1)):
            paused = daily_sessions.pause(
                self.conn, active["id"], occurred_at=hidden.isoformat()
            )
        self.assertEqual(paused["tracking_state"], "paused")
        self.assertEqual(paused["elapsed_seconds"], 300)

        resumed_at = started + timedelta(hours=1)
        with patch("lib.daily_sessions._utcnow", return_value=resumed_at):
            resumed = daily_sessions.resume(self.conn, active["id"])
        self.assertEqual(resumed["tracking_state"], "running")

        with patch(
            "lib.daily_sessions._utcnow",
            return_value=resumed_at + timedelta(minutes=2),
        ):
            finished = daily_sessions.finish(self.conn, active["id"])
        self.assertEqual(finished["active_seconds"], 420)
        self.assertEqual(finished["duration_minutes"], 7)

    def test_daily_session_presence_transitions_are_idempotent(self):
        primary = api_logic.get_study_next(self.conn, limit=1)["primary"]
        active = daily_sessions.start(self.conn, 25, primary)
        paused = daily_sessions.pause(self.conn, active["id"])
        paused_again = daily_sessions.pause(self.conn, active["id"])
        self.assertEqual(paused_again["active_seconds"], paused["active_seconds"])
        resumed = daily_sessions.resume(self.conn, active["id"])
        resumed_again = daily_sessions.resume(self.conn, active["id"])
        self.assertEqual(resumed_again["resumed_at"], resumed["resumed_at"])

    def test_search_requires_query(self):
        with self.assertRaises(ApiError):
            api_logic.search_sections(self.conn, "")

    def test_search_limit_is_bounded(self):
        results = api_logic.search_sections(self.conn, "devices", limit=99999)
        self.assertLessEqual(len(results), api_logic.MAX_SEARCH_LIMIT)

    def test_study_next_starts_with_current_knowledge_check(self):
        week = self.conn.execute(
            "SELECT id, exam_id FROM plan_weeks ORDER BY week_number LIMIT 1"
        ).fetchone()
        ts = "2026-01-01T00:00:00+00:00"
        self.conn.execute(
            "INSERT INTO diagnostic_scopes("
            "slug, name, scope_type, plan_week_id, exam_id, domain_id, question_target, "
            "min_valid_questions, raw_pass_threshold_pct, effective_pass_threshold_pct, "
            "retention_interval_days, provenance, enabled, coverage_metadata_json, created_at, updated_at"
            ") VALUES ('queue-test', 'Week 1 knowledge check', 'exam_composite', ?, ?, NULL, "
            "20, 10, 85, 80, 14, 'test', 1, '{}', ?, ?)",
            (week["id"], week["exam_id"], ts, ts),
        )
        self.conn.commit()
        queue = api_logic.get_study_next(self.conn)
        self.assertEqual(queue["current_week"], 1)
        self.assertEqual(queue["primary"]["kind"], "knowledge_check")
        self.assertEqual(queue["primary"]["action"]["mode"], "diagnostic")
        self.assertEqual(queue["counts"]["incomplete_current_week_tasks"], 4)
        kinds = [item["kind"] for item in queue["items"][1:]]
        self.assertIn("objective_lesson", kinds)
        self.assertIn("plan_task", kinds)
        self.assertGreater(queue["counts"]["unfinished_lessons"], 0)

    def test_study_next_limit_is_bounded(self):
        queue = api_logic.get_study_next(self.conn, limit=999)
        self.assertLessEqual(len(queue["items"]), 24)
        with self.assertRaises(ApiError):
            api_logic.get_study_next(self.conn, limit="not-a-number")

    def test_progress_summary_is_explainable_and_null_safe(self):
        progress = api_logic.get_progress_summary(self.conn)
        self.assertEqual(progress["current_week"], 1)
        self.assertEqual(progress["current_week_tasks"]["total"], 4)
        self.assertEqual(progress["current_week_tasks"]["remaining"], 4)
        self.assertEqual(progress["study_minutes_last_7_days"], 0)
        self.assertEqual(progress["current_streak_days"], 0)
        self.assertIn("not exact-objective mastery", progress["evidence_note"])

    def test_evening_central_session_stays_on_the_local_day(self):
        # 00:30 UTC on Aug 15 is 19:30 Central on Aug 14. UTC substring bucketing
        # would silently count this as tomorrow and break the streak.
        self.conn.execute(
            "INSERT INTO study_sessions(occurred_at, duration_minutes, notes, created_at) "
            "VALUES (?, 20, 'evening fixture', ?)",
            ("2026-08-15T00:30:00+00:00", "2026-08-15T00:30:00+00:00"),
        )
        self.conn.commit()
        with patch("lib.api_logic.study_clock.today", return_value=date(2026, 8, 14)):
            progress = api_logic.get_progress_summary(self.conn)
        self.assertEqual(progress["days_studied_last_7_days"], 1)
        self.assertEqual(progress["current_streak_days"], 1)

    def test_adaptive_curriculum_is_bounded_and_provisional_after_check(self):
        week = self.conn.execute(
            "SELECT id, exam_id FROM plan_weeks ORDER BY week_number LIMIT 1"
        ).fetchone()
        ts = "2026-01-01T00:00:00+00:00"
        self.conn.execute(
            "INSERT INTO diagnostic_scopes("
            "slug, name, scope_type, plan_week_id, exam_id, domain_id, question_target, "
            "min_valid_questions, raw_pass_threshold_pct, effective_pass_threshold_pct, "
            "retention_interval_days, provenance, enabled, coverage_metadata_json, created_at, updated_at"
            ") VALUES ('adaptive-test', 'Week 1 knowledge check', 'exam_composite', ?, ?, NULL, "
            "20, 10, 85, 80, 14, 'test', 1, '{}', ?, ?)",
            (week["id"], week["exam_id"], ts, ts),
        )
        self.conn.commit()
        plan = api_logic.get_adaptive_curriculum(self.conn, days=7, minutes_per_day=45)
        self.assertEqual(len(plan["schedule"]), 7)
        self.assertEqual(plan["schema_version"], "2")
        self.assertTrue(plan["provisional"])
        self.assertEqual(plan["schedule"][0]["items"][0]["kind"], "knowledge_check")
        self.assertEqual(
            plan["schedule"][1]["items"][0]["conditional_on"],
            plan["replan_after_item_id"],
        )
        self.assertTrue(all("planned_minutes" in day for day in plan["schedule"]))
        with self.assertRaises(ApiError):
            api_logic.get_adaptive_curriculum(self.conn, days=30)

    def test_adaptive_curriculum_starts_on_the_local_study_day(self):
        with patch("lib.api_logic.study_clock.today", return_value=date(2026, 8, 14)):
            plan = api_logic.get_adaptive_curriculum(self.conn, days=2, minutes_per_day=45)
        self.assertEqual(plan["schedule"][0]["date"], "2026-08-14")

    def test_ai_context_is_bounded_and_cited(self):
        packet = api_logic.get_ai_context(
            self.conn, query="devices", exam="220-1201", limit=3, max_chars=3000
        )
        self.assertEqual(packet["schema_version"], "1")
        self.assertEqual(packet["retrieval"]["mode"], "search")
        self.assertLessEqual(packet["retrieval"]["citation_count"], 3)
        self.assertTrue(packet["retrieval"]["citations"])
        citation = packet["retrieval"]["citations"][0]
        for key in (
            "citation_id", "book_title", "section_title", "stable_id",
            "content_sha256", "excerpt", "section_api_path",
        ):
            self.assertIn(key, citation)
        self.assertTrue(
            all("practice" not in c["book_slug"] for c in packet["retrieval"]["citations"])
        )
        self.assertLessEqual(
            sum(len(c["excerpt"]) for c in packet["retrieval"]["citations"]),
            3200,
        )

    def test_export_snapshot_has_version_and_sections(self):
        snap = api_logic.export_snapshot(self.conn, "http://127.0.0.1:8840")
        self.assertEqual(snap["schema_version"], api_logic.EXPORT_SCHEMA_VERSION)
        for key in ("books", "objectives", "plan", "sessions", "attempts", "waypoint_summary", "generated_at"):
            self.assertIn(key, snap)

    def test_waypoint_summary_fields_present_with_data(self):
        summary = api_logic.get_waypoint_summary(self.conn, "http://127.0.0.1:8840")
        required = [
            "schema_version", "generated_at", "certification_id", "certification_name",
            "current_exam", "current_week", "week_title", "next_task", "total_hours",
            "hours_last_7_days", "completed_tasks", "total_tasks", "objective_coverage",
            "practice_average_recent", "weak_objectives", "readiness_label",
            "readiness_components", "study_library_url", "study_library_path",
        ]
        for key in required:
            self.assertIn(key, summary)
        self.assertEqual(summary["certification_id"], "aplus")
        self.assertIn("progress", summary)
        self.assertIn("adaptive_curriculum", summary)


class TestApiLogicEmptyDb(unittest.TestCase):
    """No sessions/attempts/plan at all: every derived metric must be null/0, never raise."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_dashboard_handles_no_data(self):
        d = api_logic.get_dashboard(self.conn)
        self.assertIsNone(d["current_exam"])
        self.assertIsNone(d["current_week"])
        self.assertIsNone(d["next_task"])
        self.assertEqual(d["total_hours"], 0.0)
        self.assertEqual(d["completed_tasks"], 0)
        self.assertEqual(d["total_tasks"], 0)
        self.assertIsNone(d["objective_coverage"])
        self.assertIsNone(d["practice_average_recent"])
        self.assertEqual(d["weak_objectives"], [])
        self.assertEqual(d["readiness_label"], "not enough evidence yet")

    def test_study_next_handles_no_plan(self):
        queue = api_logic.get_study_next(self.conn)
        self.assertIsNone(queue["primary"])
        self.assertEqual(queue["items"], [])
        self.assertEqual(queue["counts"]["open_gaps"], 0)

    def test_ai_context_handles_no_plan_or_sources(self):
        packet = api_logic.get_ai_context(self.conn)
        self.assertIsNone(packet["current_state"]["current_week"])
        self.assertEqual(packet["retrieval"]["citations"], [])
        self.assertEqual(len(packet["adaptive_curriculum"]["schedule"]), 7)

    def test_waypoint_summary_handles_no_data(self):
        summary = api_logic.get_waypoint_summary(self.conn, "http://127.0.0.1:8840")
        self.assertIsNone(summary["current_exam"])
        self.assertEqual(summary["weak_objectives"], [])
        self.assertIsNone(summary["practice_average_recent"])

    def test_export_snapshot_handles_no_plan(self):
        snap = api_logic.export_snapshot(self.conn, "http://127.0.0.1:8840")
        self.assertIsNone(snap["plan"])
        self.assertEqual(snap["sessions"], [])
        self.assertEqual(snap["attempts"], [])

    def test_dashboard_diagnostics_block_is_null_safe_with_no_data(self):
        d = api_logic.get_dashboard(self.conn)
        dg = d["diagnostics"]
        self.assertIsNone(dg["current_scope"])
        self.assertEqual(dg["diagnostic_checks_passed"], 0)
        self.assertEqual(dg["diagnostic_checks_available"], 0)
        self.assertEqual(dg["current_gap_count"], 0)
        self.assertEqual(dg["retention_due_count"], 0)
        self.assertIsNone(dg["retention_due_next_at"])
        self.assertIsNone(dg["domain_mastery_pct"])

    def test_waypoint_summary_diagnostics_key_present_with_no_data(self):
        summary = api_logic.get_waypoint_summary(self.conn, "http://127.0.0.1:8840")
        self.assertIn("diagnostics", summary)
        self.assertEqual(summary["diagnostics"]["diagnostic_checks_available"], 0)


class TestDiagnosticsDashboardAndExport(unittest.TestCase):
    """Dashboard/waypoint/export behavior once diagnostics data exists,
    including an active gap and an in-progress (must stay redacted) attempt."""

    def setUp(self):
        import json as _json
        from ingest.ingest import ingest_all
        from ingest.plan import seed_plan
        from ingest.diagnostics_importer import import_questions, seed_diagnostic_scopes
        from lib import diagnostics
        from tests.fixtures import build_review_source, build_diagnostics_practice_source

        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        review_src = build_review_source(Path(self.tmp.name))
        diag_src = build_diagnostics_practice_source(Path(self.tmp.name))
        ingest_all(self.conn, [review_src, diag_src])
        seed_plan(self.conn)
        import_questions(self.conn)
        seed_diagnostic_scopes(self.conn)

        scope = self.conn.execute(
            "SELECT * FROM diagnostic_scopes WHERE slug = 'aplus-week1-domain-1'"
        ).fetchone()
        ts = "2026-01-01T00:00:00+00:00"
        for i in range(20):
            self.conn.execute(
                "INSERT INTO question_bank(stable_id, exam_id, domain_id, objective_id, mapping_granularity, "
                "question_book_slug, question_section_id, question_number, answer_book_slug, answer_section_id, "
                "prompt, options_json, correct_answers_json, explanation, provenance, content_hash, "
                "requires_figure, critical, active, created_at, updated_at) "
                "VALUES (?, ?, ?, NULL, 'domain', 'aplus-practice-tests', NULL, ?, 'aplus-practice-tests', NULL, "
                "?, ?, '[0]', 'exp', 'prov', ?, 0, 0, 1, ?, ?)",
                (f"export-test-{i}", scope["exam_id"], scope["domain_id"], 8000 + i,
                 f"Q{i}?", _json.dumps(["a", "b", "c", "d"]), f"hash-{i}", ts, ts),
            )
        self.conn.execute(
            "UPDATE diagnostic_scopes SET enabled = 1, question_target = 20, min_valid_questions = 2 WHERE id = ?",
            (scope["id"],),
        )
        self.conn.commit()
        self.scope_id = scope["id"]

        # A failing attempt to generate an open gap.
        attempt = diagnostics.start_attempt(self.conn, self.scope_id, "diagnostic")
        responses = [
            {"question_id": r["question_id"], "selected": [1], "confidence": "high"}
            for r in attempt["responses"]
        ]
        diagnostics.submit_attempt(self.conn, attempt["id"], responses)

        # A second, still in-progress attempt for the redaction assertions.
        self.in_progress_attempt = diagnostics.start_attempt(self.conn, self.scope_id, "diagnostic")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_dashboard_reports_active_gap_count(self):
        d = api_logic.get_dashboard(self.conn)
        self.assertGreaterEqual(d["diagnostics"]["current_gap_count"], 1)

    def test_study_next_prioritizes_open_gaps(self):
        self.conn.execute(
            "UPDATE scope_mastery SET retention_due_at = '2020-01-01T00:00:00+00:00' "
            "WHERE scope_id = ?",
            (self.scope_id,),
        )
        self.conn.commit()
        queue = api_logic.get_study_next(self.conn)
        self.assertEqual(queue["primary"]["kind"], "remediation")
        self.assertEqual(queue["primary"]["action"]["type"], "scope_detail")
        self.assertGreaterEqual(queue["counts"]["open_gaps"], 1)

    def test_export_redacts_in_progress_attempt_and_keeps_submitted(self):
        snap = api_logic.export_snapshot(self.conn, "http://127.0.0.1:8840")
        self.assertIn("diagnostic_attempts", snap)
        self.assertIn("diagnostic_scopes", snap)
        by_id = {a["id"]: a for a in snap["diagnostic_attempts"]}
        in_progress = by_id[self.in_progress_attempt["id"]]
        self.assertEqual(in_progress["state"], "in_progress")
        for r in in_progress["responses"]:
            self.assertNotIn("submitted_answer_json", r)
            self.assertIsNone(r["is_correct"])
            self.assertIsNone(r["effective_score"])

        submitted = [a for a in snap["diagnostic_attempts"] if a["state"] == "submitted"]
        self.assertTrue(submitted)
        self.assertIsNotNone(submitted[0]["responses"][0]["is_correct"])


if __name__ == "__main__":
    unittest.main()
