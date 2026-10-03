import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingest.ingest import ingest_all
from lib import compiler, db, source_verifier
from tests.fixtures import build_all_sources


class FakeResponse:
    def __init__(self, url, body):
        self.url = url
        self.body = body
        self.offset = 0
        self.headers = {
            "Content-Length": str(len(body)),
            "ETag": '"fixture"',
            "Last-Modified": "Thu, 30 Jul 2026 00:00:00 GMT",
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.url

    def read(self, size):
        chunk = self.body[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class FakeOpener:
    def __init__(self, bodies, final_host="vendor.test"):
        self.bodies = bodies
        self.final_host = final_host

    def open(self, request, timeout):
        name = request.full_url.rsplit("/", 1)[-1]
        return FakeResponse(
            f"https://{self.final_host}/{name}",
            self.bodies[name],
        )


class TestSourceVerifier(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.sources = build_all_sources(self.root)
        ingest_all(self.conn, self.sources)
        self.bodies = {"1201.pdf": b"official-one", "1202.pdf": b"official-two"}

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def _manifest(self):
        sources = []
        for name in ("1201", "1202"):
            sources.append({
                "source_key": f"official-{name}",
                "title": f"Official {name}",
                "publisher": "Vendor",
                "source_type": "official_objectives",
                "authority_tier": 1,
                "version_label": "current",
                "exam_codes": [f"220-{name}"],
                "source_url": f"https://vendor.test/{name}.pdf",
                "source_sha256": hashlib.sha256(
                    self.bodies[f"{name}.pdf"]
                ).hexdigest(),
                "use_role": "authoritative_scope",
                "required": True,
                "verified_at": "2026-07-29T00:00:00Z",
            })
        sources.append({
            "source_key": "fixture-review",
            "title": "Fixture Review",
            "publisher": "Test",
            "source_type": "review",
            "authority_tier": 3,
            "version_label": "current",
            "exam_codes": ["220-1201", "220-1202"],
            "book_slug": "fixture-review",
            "ingest": {
                "kind": "review",
                "parser": "divider-bare-objectives-domain-v1",
                "dir": "/fixture/review",
            },
            "source_sha256": "b" * 64,
            "use_role": "primary_instruction",
            "required": True,
        })
        payload = {
            "certification_code": "aplus",
            "certification_name": "CompTIA A+",
            "pack_version": "verify-fixture",
            "exam_version": "V15",
            "policy_version": "test",
            "official_hosts": ["vendor.test"],
            "exams": [
                {
                    "code": "220-1201", "name": "Core 1",
                    "objective_codes": ["1.1"],
                    "domains": [{"code": "1", "name": "Mobile", "weight": 100}],
                },
                {
                    "code": "220-1202", "name": "Core 2",
                    "objective_codes": ["1.1"],
                    "domains": [{"code": "1", "name": "OS", "weight": 100}],
                },
            ],
            "sources": sources,
        }
        path = self.root / "verify-manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_matching_sources_are_recorded_and_exposed(self):
        manifest = self._manifest()
        compiler.compile_pack(self.conn, manifest)
        result = source_verifier.verify_official_sources(
            self.conn, manifest, opener=FakeOpener(self.bodies)
        )
        self.assertEqual(result["status"], "match")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) n FROM source_verification_runs WHERE status='match'"
            ).fetchone()["n"],
            2,
        )
        pack = compiler.get_pack_report(self.conn)
        official = [s for s in pack["sources"] if s["authority_tier"] == 1]
        self.assertTrue(all(s["refresh_status"] == "match" for s in official))
        self.assertTrue(all(s["last_checked_at"] for s in official))
        live_verified_at = official[0]["verified_at"]
        compiler.compile_pack(self.conn, manifest)
        official_after_recompile = [
            s for s in compiler.get_pack_report(self.conn)["sources"]
            if s["source_key"] == official[0]["source_key"]
        ][0]
        self.assertEqual(official_after_recompile["verified_at"], live_verified_at)

    def test_drift_is_recorded_without_changing_the_pin_or_pack(self):
        manifest = self._manifest()
        compiler.compile_pack(self.conn, manifest)
        changed = dict(self.bodies)
        changed["1201.pdf"] = b"changed-upstream"
        result = source_verifier.verify_official_sources(
            self.conn, manifest, opener=FakeOpener(changed)
        )
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["sources"][0]["status"], "drift")
        source = self.conn.execute(
            "SELECT source_sha256, status FROM source_registry "
            "WHERE source_key='official-1201'"
        ).fetchone()
        self.assertEqual(
            source["source_sha256"],
            hashlib.sha256(self.bodies["1201.pdf"]).hexdigest(),
        )
        self.assertEqual(source["status"], "active")
        self.assertEqual(
            compiler.get_pack_report(self.conn)["status"], "ready"
        )

    def test_untrusted_final_host_is_an_error(self):
        manifest = self._manifest()
        compiler.compile_pack(self.conn, manifest)
        result = source_verifier.verify_official_sources(
            self.conn,
            manifest,
            opener=FakeOpener(self.bodies, final_host="evil.test"),
        )
        self.assertEqual(result["status"], "review_required")
        self.assertTrue(all(s["status"] == "error" for s in result["sources"]))

    def test_spine_verifier_discloses_pins_and_pending_sources(self):
        body = b"vendor-objectives"
        spines = [{
            "id": "fixture",
            "exams": [
                {"code": "EX-1", "official_source": {
                    "url": "https://vendor.test/ex1.pdf",
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "verification_status": "hash_verified",
                }},
                {"code": "EX-2", "official_source": {
                    "url": "https://vendor.test/ex2",
                    "sha256": None,
                    "verification_status": "official_page_verified_document_hash_pending",
                }},
            ],
        }]
        with patch("lib.certification_spines.list_spines", return_value=spines), patch(
            "lib.certification_spines.load_registry",
            return_value={"registry_version": "test-v1"},
        ):
            result = source_verifier.verify_spine_sources(
                opener=FakeOpener({"ex1.pdf": body})
            )
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["sources"][0]["status"], "match")
        self.assertEqual(
            result["sources"][1]["status"], "manual_review_required"
        )


if __name__ == "__main__":
    unittest.main()
