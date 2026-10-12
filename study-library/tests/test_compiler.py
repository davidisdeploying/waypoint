import json
import tempfile
import unittest
from pathlib import Path

from ingest.ingest import ingest_all
from lib import compiler, db
from tests.fixtures import build_all_sources


class TestCertificationCompiler(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.sources = build_all_sources(self.root)
        ingest_all(self.conn, self.sources)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def _manifest(self, review_hash="b" * 64):
        payload = {
            "certification_code": "aplus",
            "certification_name": "CompTIA A+",
            "pack_version": "fixture-v15",
            "exam_version": "V15",
            "policy_version": "test-v1",
            "official_hosts": ["example.test"],
            "exams": [
                {
                    "code": "220-1201",
                    "name": "Core 1",
                    "objectives_document_version": "3.0",
                    "objective_codes": ["1.1"],
                    "domains": [{"code": "1", "name": "Mobile Devices", "weight": 100}],
                },
                {
                    "code": "220-1202",
                    "name": "Core 2",
                    "objectives_document_version": "3.0",
                    "objective_codes": ["1.1"],
                    "domains": [{"code": "1", "name": "Operating Systems", "weight": 100}],
                },
            ],
            "sources": [
                {
                    "source_key": "official-1201",
                    "title": "Official 1201",
                    "publisher": "CompTIA",
                    "source_type": "official_objectives",
                    "authority_tier": 1,
                    "version_label": "V15 document 3.0",
                    "exam_codes": ["220-1201"],
                    "source_url": "https://example.test/1201.pdf",
                    "source_sha256": "1" * 64,
                    "use_role": "authoritative_scope",
                    "required": True,
                    "verified_at": "2026-07-30T00:00:00Z",
                },
                {
                    "source_key": "official-1202",
                    "title": "Official 1202",
                    "publisher": "CompTIA",
                    "source_type": "official_objectives",
                    "authority_tier": 1,
                    "version_label": "V15 document 3.0",
                    "exam_codes": ["220-1202"],
                    "source_url": "https://example.test/1202.pdf",
                    "source_sha256": "2" * 64,
                    "use_role": "authoritative_scope",
                    "required": True,
                    "verified_at": "2026-07-30T00:00:00Z",
                },
                {
                    "source_key": "fixture-review",
                    "title": "Fixture Review",
                    "publisher": "Test",
                    "source_type": "review",
                    "authority_tier": 3,
                    "version_label": "220-1201 and 220-1202",
                    "exam_codes": ["220-1201", "220-1202"],
                    "book_slug": "fixture-review",
                    "ingest": {
                        "kind": "review",
                        "parser": "divider-bare-objectives-domain-v1",
                        "dir": "/fixture/review",
                    },
                    "source_sha256": review_hash,
                    "use_role": "primary_instruction",
                    "required": True,
                },
                {
                    "source_key": "fixture-guide",
                    "title": "Fixture Guide",
                    "publisher": "Test",
                    "source_type": "instruction",
                    "authority_tier": 3,
                    "version_label": "220-1201",
                    "exam_codes": ["220-1201"],
                    "book_slug": "fixture-guide",
                    "ingest": {
                        "kind": "guide",
                        "parser": "inline-prefixed-objectives-v1",
                        "dir": "/fixture/guide",
                    },
                    "source_sha256": "a" * 64,
                    "use_role": "supplemental_instruction",
                    "required": False,
                },
                {
                    "source_key": "fixture-practice",
                    "title": "Fixture Practice",
                    "publisher": "Test",
                    "source_type": "assessment",
                    "authority_tier": 4,
                    "version_label": "220-1201 and 220-1202",
                    "exam_codes": ["220-1201", "220-1202"],
                    "book_slug": "fixture-practice",
                    "ingest": {
                        "kind": "practice",
                        "parser": "divider-bare-objectives-v1",
                        "dir": "/fixture/practice",
                    },
                    "source_sha256": "c" * 62,
                    "use_role": "assessment_only",
                    "required": False,
                },
            ],
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_builds_ready_pack_and_excludes_assessment_from_lessons(self):
        report = compiler.compile_pack(self.conn, self._manifest())
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["objectives"], 2)
        self.assertEqual(report["covered_objectives"], 2)
        self.assertEqual(report["quarantined_sources"], 0)
        self.assertEqual(report["dossiers"]["total"], 2)
        self.assertEqual(report["dossiers"]["complete"], 1)
        self.assertEqual(report["dossiers"]["thin"], 1)

        pack = compiler.get_pack_report(self.conn)
        self.assertEqual(pack["status"], "ready")
        self.assertEqual(len(pack["coverage_by_exam"]), 2)

        objective_id = self.conn.execute(
            "SELECT id FROM objectives ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        from lib.api_logic import get_objective
        detail = get_objective(self.conn, objective_id)
        self.assertTrue(detail["evidence"])
        self.assertTrue(all(
            evidence["source_role"] != "assessment_only"
            for evidence in detail["evidence"]
        ))
        self.assertIn("certification_pack", detail)

        from lib import dossiers
        summary = dossiers.get_dossier_summary(self.conn)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["counts"]["complete"], 1)
        self.assertEqual(summary["counts"]["thin"], 1)
        dossier = dossiers.get_dossier(self.conn, objective_id)
        self.assertIsNotNone(dossier)
        payload = dossier["dossier"]
        self.assertEqual(payload["official_scope"]["granularity"], "objective_code")
        self.assertTrue(
            payload["official_scope"]["note"].startswith(
                "The official source pins"
            )
        )
        self.assertTrue(all(
            citation["use_role"] != "assessment_only"
            for citation in payload["instructional_citations"]
        ))
        self.assertEqual(payload["assessment"]["source_count"], 1)
        self.assertEqual(
            payload["assessment"]["direct_objective_question_count"], 0
        )
        selected = [
            citation for citation in payload["instructional_citations"]
            if citation["selected_primary"]
        ]
        self.assertEqual(len(selected), 1)
        self.assertTrue(selected[0]["focused_excerpt"])
        from lib import api_logic
        self.assertEqual(
            api_logic.get_objective_dossier_summary(self.conn)["total"], 2
        )
        self.assertEqual(
            api_logic.get_objective_dossier(self.conn, objective_id)["status"],
            dossier["status"],
        )

    def test_required_hash_mismatch_quarantines_and_blocks(self):
        report = compiler.compile_pack(self.conn, self._manifest("f" * 64))
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["quarantined_sources"], 1)
        pack = compiler.get_pack_report(self.conn)
        self.assertTrue(any(
            finding["severity"] == "blocking"
            for finding in pack["findings"]
        ))
        from lib import dossiers
        summary = dossiers.get_dossier_summary(self.conn)
        self.assertGreaterEqual(summary["counts"]["missing"], 1)

    def test_compile_is_idempotent(self):
        first = compiler.compile_pack(self.conn, self._manifest())
        second = compiler.compile_pack(self.conn, self._manifest())
        self.assertEqual(first["status"], second["status"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) n FROM certification_packs").fetchone()["n"],
            1,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) n FROM objective_dossiers").fetchone()["n"],
            2,
        )

    def test_manifest_rejects_unknown_parser_adapter(self):
        path = self._manifest()
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["sources"][2]["ingest"]["parser"] = "dynamic-python-import"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(compiler.CompilerError, "unknown parser"):
            compiler.load_manifest(path)

    def test_manifest_rejects_tampered_official_objective_file(self):
        path = self._manifest()
        payload = json.loads(path.read_text(encoding="utf-8"))
        objective_file = self.root / "official.json"
        objective_file.write_text(
            json.dumps([{"code": "1.1", "description": "Official."}]),
            encoding="utf-8",
        )
        payload["exams"][0]["objectives_file"] = objective_file.name
        payload["exams"][0]["objectives_sha256"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(compiler.CompilerError, "JSON hash mismatch"):
            compiler.load_manifest(path)

    def test_parser_selection_is_part_of_source_set_hash(self):
        path = self._manifest()
        first = compiler.compile_pack(self.conn, path)
        first_hash = self.conn.execute(
            "SELECT source_set_sha256 FROM certification_packs"
        ).fetchone()["source_set_sha256"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["sources"][2]["ingest"]["parser"] = (
            "divider-bare-objectives-v1"
        )
        path.write_text(json.dumps(payload), encoding="utf-8")
        second = compiler.compile_pack(self.conn, path)
        second_hash = self.conn.execute(
            "SELECT source_set_sha256 FROM certification_packs"
        ).fetchone()["source_set_sha256"]
        self.assertEqual(first["status"], second["status"])
        self.assertNotEqual(first_hash, second_hash)

    def test_preview_is_immutable_until_explicit_publish(self):
        path = self._manifest()
        compiler.compile_pack(self.conn, path)
        before = {
            row["code"]: row["description"]
            for row in self.conn.execute("SELECT code, description FROM objectives")
        }
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["exams"][0]["objectives"] = [
            {"code": "1.1", "description": "Official Core 1 description."}
        ]
        payload["exams"][1]["objectives"] = [
            {"code": "1.1", "description": "Official Core 2 description."}
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")

        preview = compiler.preview_pack(self.conn, path)
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(
            preview["diff"]["summary"]["official_descriptions_changed"], 2
        )
        after_preview = {
            row["code"]: row["description"]
            for row in self.conn.execute("SELECT code, description FROM objectives")
        }
        self.assertEqual(after_preview, before)

        state = compiler.publish_pack(self.conn, preview["id"], path)
        self.assertEqual(state["active"]["status"], "published")
        descriptions = [
            row["description"]
            for row in self.conn.execute(
                "SELECT o.description FROM objectives o JOIN exams e ON e.id = o.exam_id "
                "WHERE o.code = '1.1' ORDER BY e.sequence_order"
            )
        ]
        self.assertEqual(
            descriptions,
            ["Official Core 1 description.", "Official Core 2 description."],
        )
        dossier_payloads = [
            json.loads(row["dossier_json"])
            for row in self.conn.execute(
                "SELECT dossier_json FROM objective_dossiers ORDER BY id"
            )
        ]
        self.assertTrue(all(
            payload["official_scope"]["granularity"] == "objective_heading"
            for payload in dossier_payloads
        ))

    def test_publish_rejects_changed_inputs_after_preview(self):
        path = self._manifest()
        compiler.compile_pack(self.conn, path)
        preview = compiler.preview_pack(self.conn, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["sources"][2]["ingest"]["parser"] = "divider-bare-objectives-v1"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(compiler.CompilerError, "inputs changed"):
            compiler.publish_pack(self.conn, preview["id"], path)
        self.assertEqual(
            self.conn.execute(
                "SELECT status FROM certification_pack_builds WHERE id = ?",
                (preview["id"],),
            ).fetchone()["status"],
            "preview",
        )

    def test_preview_snapshot_columns_are_database_immutable(self):
        path = self._manifest()
        compiler.compile_pack(self.conn, path)
        preview = compiler.preview_pack(self.conn, path)
        with self.assertRaisesRegex(
            Exception, "certification pack build snapshots are immutable"
        ):
            self.conn.execute(
                "UPDATE certification_pack_builds SET build_sha256 = ? WHERE id = ?",
                ("0" * 64, preview["id"]),
            )
