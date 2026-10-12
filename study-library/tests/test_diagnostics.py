import json
import tempfile
import unittest
from pathlib import Path

from lib import db, api_logic
from lib.api_logic import ApiError
from lib import diagnostics
from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from ingest.diagnostics_importer import import_questions, seed_diagnostic_scopes
from tests.fixtures import build_review_source, build_diagnostics_practice_source


def _now():
    return diagnostics.now_iso()


def _insert_synthetic_questions(conn, exam_id, domain_id, n, critical_indexes=()):
    """Adds n deterministic single-answer 4-option questions directly to
    question_bank, for exercising the assessment engine without needing a
    giant markdown fixture. question_number starts past the current max to
    avoid colliding with the importer's fixture-derived rows or earlier calls."""
    ts = _now()
    ids = []
    base = (conn.execute("SELECT COALESCE(MAX(question_number), 9000) AS n FROM question_bank").fetchone()["n"]) + 1
    for i in range(n):
        qnum = base + i
        stable_id = f"aplus-practice-tests:synthetic:{exam_id}:{domain_id}:{qnum}"
        correct = i % 4
        options = [f"opt-{i}-{j}" for j in range(4)]
        conn.execute(
            "INSERT INTO question_bank(stable_id, exam_id, domain_id, objective_id, mapping_granularity, "
            "question_book_slug, question_section_id, question_number, answer_book_slug, answer_section_id, "
            "prompt, options_json, correct_answers_json, explanation, provenance, content_hash, "
            "requires_figure, critical, active, created_at, updated_at) "
            "VALUES (?, ?, ?, NULL, 'domain', 'aplus-practice-tests', NULL, ?, 'aplus-practice-tests', NULL, "
            "?, ?, ?, ?, 'synthetic test fixture', ?, 0, ?, 1, ?, ?)",
            (stable_id, exam_id, domain_id, qnum, f"Synthetic question {qnum}?",
             json.dumps(options), json.dumps([correct]), f"Explanation {qnum}.",
             f"hash-{qnum}", 1 if i in critical_indexes else 0, ts, ts),
        )
        ids.append(conn.execute("SELECT id FROM question_bank WHERE stable_id = ?", (stable_id,)).fetchone()["id"])
    conn.commit()
    return ids


class DiagnosticsTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        review_src = build_review_source(Path(self.tmp.name))
        diag_src = build_diagnostics_practice_source(Path(self.tmp.name))
        ingest_all(self.conn, [review_src, diag_src])
        seed_plan(self.conn)
        import_questions(self.conn)
        seed_diagnostic_scopes(self.conn)

        self.scope_row = self.conn.execute(
            "SELECT * FROM diagnostic_scopes WHERE slug = 'aplus-week1-domain-1'"
        ).fetchone()
        _insert_synthetic_questions(self.conn, self.scope_row["exam_id"], self.scope_row["domain_id"], 20)
        self.conn.execute(
            "UPDATE diagnostic_scopes SET enabled = 1, question_target = 20, min_valid_questions = 2 WHERE id = ?",
            (self.scope_row["id"],),
        )
        self.conn.commit()
        self.scope_id = self.scope_row["id"]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _start(self, mode="diagnostic"):
        return diagnostics.start_attempt(self.conn, self.scope_id, mode)

    def _answer_all(self, attempt, n_correct, confidence="high"):
        """Answers the first n_correct questions correctly, the rest wrong,
        all at the given confidence. Returns the responses payload."""
        qids = [r["question_id"] for r in attempt["responses"]]
        qrows = {
            r["id"]: r for r in self.conn.execute(
                f"SELECT * FROM question_bank WHERE id IN ({','.join('?' * len(qids))})", qids
            )
        }
        responses = []
        for i, r in enumerate(attempt["responses"]):
            q = qrows[r["question_id"]]
            correct = json.loads(q["correct_answers_json"])
            if i < n_correct:
                responses.append({"question_id": r["question_id"], "selected": correct, "confidence": confidence})
            else:
                wrong = [x for x in range(len(r["options"])) if x not in correct][:1]
                responses.append({"question_id": r["question_id"], "selected": wrong, "confidence": confidence})
        return responses


class TestAttemptStartAndRedaction(DiagnosticsTestBase):
    def test_start_attempt_redacts_correct_answers(self):
        attempt = self._start()
        self.assertTrue(attempt["answers_redacted"])
        for r in attempt["responses"]:
            self.assertNotIn("correct_answers", r)
            self.assertIsNone(r["is_correct"])
            self.assertIsNone(r["effective_score"])

    def test_get_attempt_in_progress_stays_redacted(self):
        attempt = self._start()
        fetched = diagnostics.get_attempt(self.conn, attempt["id"])
        self.assertTrue(fetched["answers_redacted"])
        self.assertNotIn("correct_answers", fetched["responses"][0])

    def test_cannot_start_second_concurrent_attempt(self):
        self._start()
        with self.assertRaises(ApiError):
            self._start()

    def test_disabled_scope_cannot_start(self):
        self.conn.execute("UPDATE diagnostic_scopes SET enabled = 0 WHERE id = ?", (self.scope_id,))
        self.conn.commit()
        with self.assertRaises(ApiError):
            self._start()


class TestScoringThresholds(DiagnosticsTestBase):
    def test_pass_at_exactly_85_raw_and_80_effective(self):
        attempt = self._start()
        # 17/20 = 85% raw, all high confidence -> 85% effective too
        responses = self._answer_all(attempt, n_correct=17, confidence="high")
        result = diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        self.assertEqual(result["raw_score_pct"], 85.0)
        self.assertEqual(result["effective_score_pct"], 85.0)
        self.assertTrue(result["passed"])
        self.assertEqual(result["bucket_result"], "provisional_mastery")

    def test_fail_below_raw_threshold(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=10, confidence="high")  # 50%
        result = diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        self.assertFalse(result["passed"])
        self.assertEqual(result["bucket_result"], "needs_remediation")

    def test_confidence_adjustment_can_fail_effective_despite_raw_pass(self):
        attempt = self._start()
        # 17/20 correct (85% raw, clears raw threshold) but all at low confidence
        # -> effective = 17*0.7/20*100 = 59.5%, below the 80% effective threshold.
        responses = self._answer_all(attempt, n_correct=17, confidence="low")
        result = diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        self.assertEqual(result["raw_score_pct"], 85.0)
        self.assertLess(result["effective_score_pct"], 80.0)
        self.assertFalse(result["passed"])

    def test_critical_item_incorrect_forces_fail_even_if_thresholds_met(self):
        crit_ids = _insert_synthetic_questions(
            self.conn, self.scope_row["exam_id"], self.scope_row["domain_id"], 1, critical_indexes=(0,)
        )
        self.conn.execute("UPDATE question_bank SET critical = 1 WHERE id = ?", (crit_ids[0],))
        self.conn.commit()
        attempt = self._start()
        crit_qids = {r["question_id"] for r in attempt["responses"]} & set(crit_ids)
        responses = self._answer_all(attempt, n_correct=len(attempt["responses"]), confidence="high")
        if crit_qids:
            # Force the critical question wrong regardless of its position.
            crit_qid = next(iter(crit_qids))
            for r in responses:
                if r["question_id"] == crit_qid:
                    q = self.conn.execute("SELECT * FROM question_bank WHERE id = ?", (crit_qid,)).fetchone()
                    correct = set(json.loads(q["correct_answers_json"]))
                    wrong = [x for x in range(4) if x not in correct][:1]
                    r["selected"] = wrong
            result = diagnostics.submit_attempt(self.conn, attempt["id"], responses)
            self.assertFalse(result["passed"], "an incorrect critical item must force failure")

    def test_multi_select_requires_exact_set_match(self):
        # Directly exercise scoring logic with a synthetic multi-select question.
        ts = _now()
        self.conn.execute(
            "INSERT INTO question_bank(stable_id, exam_id, domain_id, objective_id, mapping_granularity, "
            "question_book_slug, question_section_id, question_number, answer_book_slug, answer_section_id, "
            "prompt, options_json, correct_answers_json, explanation, provenance, content_hash, "
            "requires_figure, critical, active, created_at, updated_at) "
            "VALUES ('multi-test', ?, ?, NULL, 'domain', 'aplus-practice-tests', NULL, 8888, "
            "'aplus-practice-tests', NULL, 'Pick two?', ?, '[0, 2]', 'exp', 'prov', 'hash', 0, 0, 1, ?, ?)",
            (self.scope_row["exam_id"], self.scope_row["domain_id"], json.dumps(["a", "b", "c", "d"]), ts, ts),
        )
        self.conn.commit()
        # Include the injected multiselect deterministically even if the fixture
        # pool grows; start_attempt bounds the target to the available pool.
        self.conn.execute(
            "UPDATE diagnostic_scopes SET question_target = 999 WHERE id = ?", (self.scope_id,)
        )
        self.conn.commit()
        attempt = self._start()
        multi_qid = self.conn.execute("SELECT id FROM question_bank WHERE stable_id = 'multi-test'").fetchone()["id"]
        responses = self._answer_all(attempt, n_correct=len(attempt["responses"]), confidence="high")
        for r in responses:
            if r["question_id"] == multi_qid:
                r["selected"] = [0]  # partial match only -- must count as incorrect
        result = diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        resp_row = self.conn.execute(
            "SELECT is_correct FROM diagnostic_responses WHERE attempt_id = ? AND question_id = ?",
            (attempt["id"], multi_qid),
        ).fetchone()
        self.assertEqual(resp_row["is_correct"], 0, "a partial multi-select match must not count as correct")


class TestSubmissionValidationAndTransactions(DiagnosticsTestBase):
    def test_abandon_redacts_answers_and_unblocks_a_new_attempt(self):
        attempt = self._start()
        abandoned = diagnostics.abandon_attempt(self.conn, attempt["id"])
        self.assertEqual(abandoned["state"], "abandoned")
        self.assertTrue(abandoned["answers_redacted"])
        for response in abandoned["responses"]:
            self.assertNotIn("correct_answers", response)
            self.assertNotIn("explanation", response)
        replacement = self._start()
        self.assertNotEqual(replacement["id"], attempt["id"])

    def test_submitted_attempt_cannot_be_abandoned(self):
        attempt = self._start()
        responses = self._answer_all(
            attempt, n_correct=len(attempt["responses"]), confidence="high"
        )
        diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        with self.assertRaises(ApiError):
            diagnostics.abandon_attempt(self.conn, attempt["id"])

    def test_double_submit_rejected(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=20, confidence="high")
        diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        with self.assertRaises(ApiError):
            diagnostics.submit_attempt(self.conn, attempt["id"], responses)

    def test_incomplete_submission_rejected_and_nothing_persisted(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=20, confidence="high")[:-1]  # missing one
        with self.assertRaises(ApiError):
            diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        fresh = diagnostics.get_attempt(self.conn, attempt["id"])
        self.assertEqual(fresh["state"], "in_progress")
        for r in fresh["responses"]:
            self.assertIsNone(r["submitted_answer"])

    def test_malformed_confidence_rejected_and_rolled_back(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=20, confidence="high")
        responses[0]["confidence"] = "extremely-sure"  # invalid enum
        with self.assertRaises(ApiError):
            diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        fresh = diagnostics.get_attempt(self.conn, attempt["id"])
        self.assertEqual(fresh["state"], "in_progress")
        self.assertIsNone(fresh["responses"][0]["submitted_answer"])

    def test_out_of_range_option_index_rejected(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=20, confidence="high")
        responses[0]["selected"] = [99]
        with self.assertRaises(ApiError):
            diagnostics.submit_attempt(self.conn, attempt["id"], responses)


class TestRemediationGapCreation(DiagnosticsTestBase):
    def test_gaps_only_for_incorrect_and_correct_low_confidence(self):
        attempt = self._start()
        qids = [r["question_id"] for r in attempt["responses"]]
        qrows = {r["id"]: r for r in self.conn.execute(
            f"SELECT * FROM question_bank WHERE id IN ({','.join('?' * len(qids))})", qids)}
        responses = []
        for i, r in enumerate(attempt["responses"]):
            q = qrows[r["question_id"]]
            correct = json.loads(q["correct_answers_json"])
            if i == 0:
                responses.append({"question_id": r["question_id"], "selected": correct, "confidence": "low"})  # gap
            elif i == 1:
                responses.append({"question_id": r["question_id"], "selected": correct, "confidence": "medium"})  # no gap
            elif i < 12:  # enough incorrect to fail the attempt
                wrong = [x for x in range(4) if x not in correct][:1]
                responses.append({"question_id": r["question_id"], "selected": wrong, "confidence": "high"})  # gap
            else:
                responses.append({"question_id": r["question_id"], "selected": correct, "confidence": "high"})  # no gap
        result = diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        self.assertFalse(result["passed"])
        gap_reasons = {g["gap_reason"] for g in result["gaps"]}
        self.assertIn("correct_low_confidence", gap_reasons)
        self.assertIn("incorrect", gap_reasons)
        # exactly the 1 low-confidence-correct + 10 incorrect responses got gaps
        self.assertEqual(len(result["gaps"]), 11)

    def test_passed_attempt_creates_no_remediation_even_with_low_confidence(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=20, confidence="high")
        responses[0]["confidence"] = "low"  # correct + low confidence, but attempt still passes overall
        result = diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["gaps"]), 0)

    def test_retest_blocked_until_gaps_reviewed_then_allowed(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=10, confidence="high")  # fail
        result = diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        self.assertFalse(result["passed"])
        with self.assertRaises(ApiError):
            diagnostics.start_attempt(self.conn, self.scope_id, "retest")
        for g in result["gaps"]:
            diagnostics.mark_reviewed(self.conn, g["remediation_id"])
        retest = diagnostics.start_attempt(self.conn, self.scope_id, "retest")
        self.assertEqual(retest["mode"], "retest")

    def test_retest_pass_yields_mastered_after_remediation(self):
        attempt = self._start()
        fail_responses = self._answer_all(attempt, n_correct=10, confidence="high")
        result = diagnostics.submit_attempt(self.conn, attempt["id"], fail_responses)
        for g in result["gaps"]:
            diagnostics.mark_reviewed(self.conn, g["remediation_id"])
        retest = diagnostics.start_attempt(self.conn, self.scope_id, "retest")
        pass_responses = self._answer_all(retest, n_correct=20, confidence="high")
        retest_result = diagnostics.submit_attempt(self.conn, retest["id"], pass_responses)
        self.assertTrue(retest_result["passed"])
        self.assertEqual(retest_result["bucket_result"], "mastered_after_remediation")


class TestUnseenSelectionAndDisclosure(DiagnosticsTestBase):
    def test_no_reuse_when_pool_sufficient(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=20, confidence="high")
        diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        # A fresh diagnostic attempt for the same scope is blocked by state rules
        # in this suite (one active pass is enough); verify disclosure text on
        # this first attempt showed no reuse since the pool (22 questions) exceeds target (20).
        first = diagnostics.get_attempt(self.conn, attempt["id"])
        self.assertIn("sampled without repeats", first["selection_disclosure"])

    def test_reuse_disclosed_when_pool_exhausted(self):
        # Shrink the pool below target so a second attempt must reuse questions.
        self.conn.execute(
            "UPDATE diagnostic_scopes SET question_target = 5, min_valid_questions = 2 WHERE id = ?",
            (self.scope_id,),
        )
        self.conn.commit()
        first = self._start()
        responses = self._answer_all(first, n_correct=5, confidence="high")
        diagnostics.submit_attempt(self.conn, first["id"], responses)

        # Restrict pool to exactly the 5 already-seen questions so the next
        # attempt has no unseen options left, forcing disclosed reuse.
        seen_ids = [r["question_id"] for r in first["responses"]]
        self.conn.execute(
            f"UPDATE question_bank SET active = 0 WHERE domain_id = ? AND id NOT IN "
            f"({','.join('?' * len(seen_ids))})",
            (self.scope_row["domain_id"], *seen_ids),
        )
        self.conn.commit()
        second = diagnostics.start_attempt(self.conn, self.scope_id, "retention")
        self.assertIn("reuse disclosed", second["selection_disclosure"])
        self.assertEqual(len(json.loads(second["reused_question_ids_json"])), 5)


class TestRetentionTransitions(DiagnosticsTestBase):
    def test_retention_pass_refreshes_due_date_without_changing_status(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=20, confidence="high")
        diagnostics.submit_attempt(self.conn, attempt["id"], responses)
        mastery_before = self.conn.execute(
            "SELECT * FROM scope_mastery WHERE scope_id = ?", (self.scope_id,)
        ).fetchone()
        self.assertEqual(mastery_before["status"], "provisional_mastery")

        retention_attempt = diagnostics.start_attempt(self.conn, self.scope_id, "retention")
        retention_responses = self._answer_all(retention_attempt, n_correct=20, confidence="high")
        diagnostics.submit_attempt(self.conn, retention_attempt["id"], retention_responses)
        mastery_after = self.conn.execute(
            "SELECT * FROM scope_mastery WHERE scope_id = ?", (self.scope_id,)
        ).fetchone()
        self.assertEqual(mastery_after["status"], "provisional_mastery")
        self.assertGreaterEqual(mastery_after["retention_due_at"], mastery_before["retention_due_at"])

    def test_retention_failure_returns_to_needs_remediation(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=20, confidence="high")
        diagnostics.submit_attempt(self.conn, attempt["id"], responses)

        retention_attempt = diagnostics.start_attempt(self.conn, self.scope_id, "retention")
        fail_responses = self._answer_all(retention_attempt, n_correct=5, confidence="high")
        result = diagnostics.submit_attempt(self.conn, retention_attempt["id"], fail_responses)
        self.assertFalse(result["passed"])
        mastery = self.conn.execute(
            "SELECT * FROM scope_mastery WHERE scope_id = ?", (self.scope_id,)
        ).fetchone()
        self.assertEqual(mastery["status"], "needs_remediation")
        self.assertIsNone(mastery["retention_due_at"])


class TestPlanTaskExemptions(DiagnosticsTestBase):
    def test_pass_creates_exemptions_without_marking_tasks_completed(self):
        week_id = self.scope_row["plan_week_id"]
        tasks_before = self.conn.execute(
            "SELECT id, completed FROM plan_tasks WHERE week_id = ?", (week_id,)
        ).fetchall()
        self.assertTrue(all(t["completed"] == 0 for t in tasks_before))

        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=20, confidence="high")
        diagnostics.submit_attempt(self.conn, attempt["id"], responses)

        tasks_after = self.conn.execute(
            "SELECT id, completed FROM plan_tasks WHERE week_id = ?", (week_id,)
        ).fetchall()
        self.assertTrue(all(t["completed"] == 0 for t in tasks_after), "exemption must not falsify completion")

        exemptions = self.conn.execute(
            "SELECT * FROM plan_task_exemptions WHERE scope_id = ?", (self.scope_id,)
        ).fetchall()
        self.assertEqual(len(exemptions), len(tasks_after))

        plan = api_logic.get_plan(self.conn)
        week = next(w for w in plan["weeks"] if w["id"] == week_id)
        self.assertTrue(all(t["exemption_reason"] for t in week["tasks"]))


class TestDiagnosticReadingUxAndRemediation(DiagnosticsTestBase):
    def test_in_progress_redaction_proves_no_explanation_or_answer_text(self):
        attempt = self._start()
        fetched = diagnostics.get_attempt(self.conn, attempt["id"])
        self.assertTrue(fetched["answers_redacted"])
        for r in fetched["responses"]:
            self.assertNotIn("correct_answers", r)
            self.assertNotIn("correct_answer_text", r)
            self.assertNotIn("submitted_answer_text", r)
            self.assertNotIn("explanation", r)
            self.assertNotIn("practice_book_explanation", r)

    def test_submitted_gap_includes_explanation_and_mapped_answer_text_single_and_multiselect(self):
        ts = _now()
        options = ["Alpha option", "Beta option", "Gamma option", "Delta option"]
        self.conn.execute(
            "INSERT INTO question_bank(stable_id, exam_id, domain_id, objective_id, mapping_granularity, "
            "question_book_slug, question_section_id, question_number, answer_book_slug, answer_section_id, "
            "prompt, options_json, correct_answers_json, explanation, provenance, content_hash, "
            "requires_figure, critical, active, created_at, updated_at) "
            "VALUES ('multi-ux-test', ?, ?, NULL, 'domain', 'aplus-practice-tests', NULL, 9999, "
            "'aplus-practice-tests', NULL, 'Choose two items?', ?, '[0, 2]', 'Practice book explanation for multi.', "
            "'prov', 'hash-multi', 0, 0, 1, ?, ?)",
            (self.scope_row["exam_id"], self.scope_row["domain_id"], json.dumps(options), ts, ts),
        )
        self.conn.commit()
        self.conn.execute(
            "UPDATE diagnostic_scopes SET question_target = 999 WHERE id = ?", (self.scope_id,)
        )
        self.conn.commit()

        attempt = self._start()
        multi_qid = self.conn.execute("SELECT id FROM question_bank WHERE stable_id = 'multi-ux-test'").fetchone()["id"]
        responses = self._answer_all(attempt, n_correct=0, confidence="high")
        for r in responses:
            if r["question_id"] == multi_qid:
                r["selected"] = [1, 3]  # Beta option, Delta option (incorrect)
        results = diagnostics.submit_attempt(self.conn, attempt["id"], responses)

        # Check attempt responses
        multi_resp = next(r for r in results["responses"] if r["question_id"] == multi_qid)
        self.assertEqual(multi_resp["submitted_answer_text"], ["Beta option", "Delta option"])
        self.assertEqual(multi_resp["correct_answer_text"], ["Alpha option", "Gamma option"])
        self.assertEqual(multi_resp["explanation"], "Practice book explanation for multi.")

        # Check gaps
        multi_gap = next(g for g in results["gaps"] if g["question_id"] == multi_qid)
        self.assertEqual(multi_gap["submitted_answer_text"], ["Beta option", "Delta option"])
        self.assertEqual(multi_gap["correct_answer_text"], ["Alpha option", "Gamma option"])
        self.assertEqual(multi_gap["explanation"], "Practice book explanation for multi.")
        self.assertEqual(multi_gap["practice_book_explanation"], "Practice book explanation for multi.")

    def test_malformed_stored_index_cannot_crash_results(self):
        attempt = self._start()
        responses = self._answer_all(attempt, n_correct=0, confidence="high")
        diagnostics.submit_attempt(self.conn, attempt["id"], responses)

        # Corrupt submitted_answer_json with out-of-bounds / invalid data
        self.conn.execute(
            "UPDATE diagnostic_responses SET submitted_answer_json = '[999, -1, \"bad\"]' WHERE attempt_id = ?",
            (attempt["id"],),
        )
        self.conn.commit()

        results = diagnostics.get_attempt_results(self.conn, attempt["id"])
        self.assertIsNotNone(results)
        gap0 = results["gaps"][0]
        self.assertIn("[Invalid index: 999]", gap0["submitted_answer_text"])
        self.assertIn("[Invalid index: -1]", gap0["submitted_answer_text"])

    def test_js_ui_source_assertions(self):
        js_content = (Path(__file__).resolve().parent.parent / "static" / "js" / "app.js").read_text()

        # WireGapCards in reading handler must NOT truncate section content at 1200 chars
        import re
        wire_gap_match = re.search(r"function wireGapCards\(.*?\)\s*\{([\s\S]*?)\n  \}", js_content)
        self.assertTrue(wire_gap_match, "wireGapCards function must exist in app.js")
        self.assertNotIn(".slice(0, 1200)", wire_gap_match.group(1))
        self.assertNotIn(".slice(0,1200)", wire_gap_match.group(1))

        # Citation UI must display book_title, section_stable_id, content_hash, and practice-book explanation
        gap_card_match = re.search(r"function gapCardHtml\(.*?\)\s*\{([\s\S]*?)\n  \}", js_content)
        self.assertTrue(gap_card_match, "gapCardHtml function must exist in app.js")
        gap_card_code = gap_card_match.group(1)
        self.assertIn("rd.book_title", gap_card_code)
        self.assertIn("rd.section_stable_id", gap_card_code)
        self.assertIn("rd.content_hash", gap_card_code)
        self.assertIn("Practice-book explanation", gap_card_code)

    def test_study_next_mobile_ui_source_contract(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / "static" / "index.html").read_text()
        js = (root / "static" / "js" / "app.js").read_text()
        css = (root / "static" / "css" / "style.css").read_text()
        self.assertIn('data-view="next"', html)
        self.assertIn('data-view-panel="next"', html)
        self.assertIn('api("/api/study-next")', js)
        self.assertIn("function renderStudyNext", js)
        self.assertIn('location.hash.slice(1) : "next"', js)
        self.assertIn(".study-next-hero", css)
        self.assertIn(".diagnostic-actions", css)
        self.assertIn("min-height: 44px", css)


if __name__ == "__main__":
    unittest.main()
