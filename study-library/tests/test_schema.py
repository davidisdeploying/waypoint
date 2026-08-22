import unittest

from lib import db


class TestSchema(unittest.TestCase):
    def test_init_creates_tables_and_version(self):
        conn = db.connect(":memory:")
        db.init_db(conn)
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        expected = {
            "books", "sections", "certifications", "exams", "domains", "objectives",
            "objective_chunk_links", "study_plans", "plan_weeks", "plan_tasks",
            "study_sessions", "practice_attempts", "objective_mastery", "schema_meta",
            "waypoint_state",
            "library_jobs",
            "guided_study_sessions",
            "guided_study_events",
            "source_registry",
            "certification_packs",
            "certification_pack_sources",
            "certification_pack_objectives",
            "compiler_findings",
            "source_verification_runs",
            "objective_dossiers",
            "certification_pack_builds",
            "certification_pack_active_builds",
            "learning_events",
            "objective_retention_state",
            "objective_retention_reviews",
            "study_annotations",
            "hands_on_labs",
            "practice_exam_question_pool",
            "practice_exam_attempts",
            "practice_exam_responses",
            "lab_template_launches",
        }
        self.assertTrue(expected.issubset(tables))
        self.assertEqual(db.get_schema_version(conn), db.SCHEMA_VERSION)
        conn.close()

    def test_init_is_idempotent(self):
        conn = db.connect(":memory:")
        db.init_db(conn)
        db.init_db(conn)  # must not raise
        self.assertEqual(db.get_schema_version(conn), db.SCHEMA_VERSION)
        conn.close()

    def test_v2_tables_present(self):
        conn = db.connect(":memory:")
        db.init_db(conn)
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        expected_v2 = {
            "diagnostic_scopes", "question_bank", "diagnostic_attempts",
            "diagnostic_responses", "remediation_items", "remediation_readings",
            "scope_mastery", "plan_task_exemptions",
        }
        self.assertTrue(expected_v2.issubset(tables))
        conn.close()

    def test_existing_v1_db_upgrades_without_data_loss(self):
        # Simulate a pre-existing v1 database (only schema.sql applied) that
        # already has user data, then run the current additive migrations and
        # confirm the v1 row survives and newer tables appear alongside it.
        conn = db.connect(":memory:")
        conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1')"
        )
        ts = "2026-01-01T00:00:00+00:00"
        conn.execute(
            "INSERT INTO certifications(code, name, sequence_order, created_at, updated_at) "
            "VALUES ('aplus', 'CompTIA A+', 1, ?, ?)", (ts, ts),
        )
        conn.commit()

        db.init_db(conn)

        row = conn.execute("SELECT * FROM certifications WHERE code = 'aplus'").fetchone()
        self.assertIsNotNone(row, "pre-existing v1 data must survive the v2 upgrade")
        self.assertEqual(db.get_schema_version(conn), "19")
        book_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(books)").fetchall()
        }
        self.assertIn("source_epub_path", book_columns)
        guided_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(guided_study_sessions)").fetchall()
        }
        self.assertIn("history_session_id", guided_columns)
        self.assertIn("deleted_at", guided_columns)
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        self.assertIn("question_bank", tables)
        self.assertIn("waypoint_state", tables)
        conn.close()

    def test_upgrade_is_idempotent_on_existing_db(self):
        conn = db.connect(":memory:")
        conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
        db.init_db(conn)
        db.init_db(conn)  # must not raise on a second additive pass
        self.assertEqual(db.get_schema_version(conn), "19")
        conn.close()

    def test_existing_active_session_upgrades_paused_without_losing_observed_time(self):
        conn = db.connect(":memory:")
        conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "CREATE TABLE guided_study_sessions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, "
            "started_at TEXT NOT NULL, ended_at TEXT, target_minutes INTEGER NOT NULL, "
            "duration_minutes INTEGER, exam_id INTEGER, week_id INTEGER, task_kind TEXT, "
            "task_title TEXT NOT NULL, task_action_json TEXT, notes TEXT, recap_json TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO guided_study_sessions(status, started_at, target_minutes, task_title, created_at, updated_at) "
            "VALUES ('active', '2026-08-09T12:00:00+00:00', 25, 'Review', "
            "'2026-08-09T12:00:00+00:00', '2026-08-09T12:10:30+00:00')"
        )
        conn.commit()

        db.init_db(conn)

        row = conn.execute(
            "SELECT active_seconds, tracking_state, resumed_at FROM guided_study_sessions"
        ).fetchone()
        self.assertTrue(629 <= row["active_seconds"] <= 630)
        self.assertEqual(row["tracking_state"], "paused")
        self.assertIsNone(row["resumed_at"])
        db.init_db(conn)
        again = conn.execute(
            "SELECT active_seconds, tracking_state FROM guided_study_sessions"
        ).fetchone()
        self.assertEqual(again["active_seconds"], row["active_seconds"])
        self.assertEqual(again["tracking_state"], "paused")
        conn.close()

    def test_existing_completed_guided_session_links_to_legacy_history(self):
        conn = db.connect(":memory:")
        db.init_db(conn)
        ts = "2026-08-09T12:00:00+00:00"
        legacy = conn.execute(
            "INSERT INTO study_sessions(occurred_at, duration_minutes, notes, created_at) "
            "VALUES (?, 12, 'Recorded session', ?)",
            (ts, ts),
        )
        guided = conn.execute(
            "INSERT INTO guided_study_sessions("
            "status, started_at, ended_at, target_minutes, duration_minutes, active_seconds, "
            "tracking_state, task_title, created_at, updated_at"
            ") VALUES ('completed', ?, ?, 25, 12, 720, 'paused', 'Review', ?, ?)",
            (ts, ts, ts, ts),
        )
        conn.commit()

        db.init_db(conn)

        linked = conn.execute(
            "SELECT history_session_id FROM guided_study_sessions WHERE id = ?",
            (guided.lastrowid,),
        ).fetchone()
        self.assertEqual(linked["history_session_id"], legacy.lastrowid)
        conn.close()


if __name__ == "__main__":
    unittest.main()
