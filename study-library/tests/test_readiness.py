import json
import unittest

from lib import db, readiness


NOW = "2026-08-14T12:00:00+00:00"


class TestExamReadiness(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        c = self.conn.execute(
            "INSERT INTO certifications(code,name,sequence_order,created_at,updated_at) VALUES ('aplus','A+',1,?,?)",
            (NOW, NOW),
        )
        self.cert_id = c.lastrowid
        e = self.conn.execute(
            "INSERT INTO exams(certification_id,code,name,sequence_order,created_at,updated_at) VALUES (?,'220-1201','Core 1',1,?,?)",
            (self.cert_id, NOW, NOW),
        )
        self.exam_id = e.lastrowid
        d = self.conn.execute(
            "INSERT INTO domains(exam_id,code,name,provenance,confidence,created_at,updated_at) VALUES (?,'1','Mobile Devices','test',1,?,?)",
            (self.exam_id, NOW, NOW),
        )
        self.domain_id = d.lastrowid
        o = self.conn.execute(
            "INSERT INTO objectives(exam_id,domain_id,code,description,provenance,confidence,created_at,updated_at) VALUES (?,?,'1.1','Test objective','test',1,?,?)",
            (self.exam_id, self.domain_id, NOW, NOW),
        )
        self.objective_id = o.lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_readiness_uses_separate_fail_closed_gates(self):
        result = readiness.get_exam_readiness(self.conn, "220-1201")
        self.assertFalse(result["ready_to_schedule"])
        self.assertIsNone(result["policy"]["composite_score"])
        self.assertEqual(result["total_gate_count"], 10)
        self.assertEqual(result["next_gate"]["key"], "published_pack")

    def test_all_direct_evidence_is_required_for_ready_to_schedule(self):
        source = self.conn.execute(
            "INSERT INTO source_registry(certification_id,source_key,title,publisher,source_type,authority_tier,version_label,exam_codes_json,source_url,source_sha256,status,status_reason,metadata_json,verified_at,created_at,updated_at) "
            "VALUES (?,'official','Official','CompTIA','official_objectives',1,'v','[\"220-1201\"]','https://example.test','" + "a" * 64 + "','active','test','{}',?,?,?)",
            (self.cert_id, NOW, NOW, NOW),
        )
        pack = self.conn.execute(
            "INSERT INTO certification_packs(certification_id,pack_version,exam_version,status,compiler_version,policy_version,source_set_sha256,official_count,active_source_count,quarantined_count,objective_count,covered_count,conflict_count,report_json,compiled_at,created_at,updated_at) "
            "VALUES (?,'p','v','ready','c','p','" + "b" * 64 + "',1,1,0,1,1,0,'{}',?,?,?)",
            (self.cert_id, NOW, NOW, NOW),
        )
        build = self.conn.execute(
            "INSERT INTO certification_pack_builds(certification_id,pack_version,exam_version,compiler_version,policy_version,source_set_sha256,build_sha256,status,report_json,snapshot_json,diff_json,compiled_at,published_at,created_at) "
            "VALUES (?,'p','v','c','p','" + "b" * 64 + "','" + "c" * 64 + "','published','{}','{}','{}',?,?,?)",
            (self.cert_id, NOW, NOW, NOW),
        )
        self.conn.execute(
            "INSERT INTO certification_pack_active_builds(certification_id,build_id,promoted_at) VALUES (?,?,?)",
            (self.cert_id, build.lastrowid, NOW),
        )
        self.conn.execute(
            "INSERT INTO objective_dossiers(pack_id,objective_id,official_source_id,status,quality_score,primary_source_count,supplemental_source_count,assessment_source_count,direct_question_count,domain_question_count,dossier_json,compiled_at,created_at,updated_at) VALUES (?,?,?,'complete',100,1,0,0,0,0,'{}',?,?,?)",
            (pack.lastrowid, self.objective_id, source.lastrowid, NOW, NOW, NOW),
        )
        for event in ("lesson_completed", "recall_completed"):
            self.conn.execute(
                "INSERT INTO learning_events(objective_id,event_type,event_key,metadata_json,occurred_at,created_at) VALUES (?,?,?,?,?,?)",
                (self.objective_id, event, event, "{}", NOW, NOW),
            )
        self.conn.execute(
            "INSERT INTO objective_retention_state(objective_id,stage,interval_days,due_at,review_count,created_at,updated_at) VALUES (?,1,7,'2099-01-01T00:00:00+00:00',1,?,?)",
            (self.objective_id, NOW, NOW),
        )
        scope = self.conn.execute(
            "INSERT INTO diagnostic_scopes(slug,name,scope_type,exam_id,domain_id,question_target,min_valid_questions,raw_pass_threshold_pct,effective_pass_threshold_pct,retention_interval_days,provenance,enabled,coverage_metadata_json,created_at,updated_at) VALUES ('d','Domain','domain',?,?,1,1,85,80,14,'test',1,'{}',?,?)",
            (self.exam_id, self.domain_id, NOW, NOW),
        )
        self.conn.execute(
            "INSERT INTO scope_mastery(scope_id,status,updated_at) VALUES (?,'provisional_mastery',?)",
            (scope.lastrowid, NOW),
        )
        self.conn.execute(
            "INSERT INTO hands_on_labs(objective_id,title,goal_text,evidence_text,reflection_text,status,completion_level,archived,created_at,updated_at) VALUES (?,'Lab','Goal','Evidence','Reflection','completed','unaided',0,?,?)",
            (self.objective_id, NOW, NOW),
        )
        question = self.conn.execute(
            "INSERT INTO question_bank(stable_id,exam_id,domain_id,objective_id,mapping_granularity,question_book_slug,question_number,answer_book_slug,prompt,options_json,correct_answers_json,explanation,provenance,content_hash,requires_figure,critical,active,created_at,updated_at) VALUES ('q',?,?,?,'objective','book',1,'book','Q','[]','[]','E','test','h',0,0,1,?,?)",
            (self.exam_id, self.domain_id, self.objective_id, NOW, NOW),
        )
        for attempt_id in (1, 2):
            self.conn.execute(
                "INSERT INTO practice_exam_attempts(id,exam_id,state,question_target,duration_minutes,started_at,expires_at,submitted_at,question_ids_json,reused_question_ids_json,selection_disclosure,raw_score_pct,readiness_band,timed_out,created_at,updated_at) VALUES (?,?,'submitted',1,90,?,?,?,'[1]','[]','fresh',100,'strong_signal',0,?,?)",
                (attempt_id, self.exam_id, NOW, NOW, NOW, NOW, NOW),
            )
            self.conn.execute(
                "INSERT INTO practice_exam_responses(attempt_id,question_id,position,domain_id,objective_id,mapping_granularity,prompt_snapshot,options_snapshot_json,correct_answers_snapshot_json,submitted_answer_json,is_correct,created_at,updated_at) VALUES (?,?,1,?,?,'objective','Q','[]','[]','[]',1,?,?)",
                (attempt_id, question.lastrowid, self.domain_id, self.objective_id, NOW, NOW),
            )
        self.conn.commit()

        result = readiness.get_exam_readiness(self.conn, "220-1201")
        self.assertTrue(result["ready_to_schedule"])
        self.assertEqual(result["passed_gate_count"], result["total_gate_count"])
        self.assertIsNone(result["next_gate"])


if __name__ == "__main__":
    unittest.main()
