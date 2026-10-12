import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import career_context


class TestCareerContext(unittest.TestCase):
    def test_claim_text_stays_canonical_and_hash_guarded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims = root / "claims.md"
            claims.write_text("# Canonical claims\n", encoding="utf-8")
            digest = hashlib.sha256(claims.read_bytes()).hexdigest()
            payload = career_context.load_context()
            payload["canonical_source"] = {
                "path": str(claims), "sha256": digest, "last_verified": "2026-08-14",
            }
            context = root / "context.json"
            context.write_text(json.dumps(payload), encoding="utf-8")
            result = career_context.get_context("secplus", context)
            self.assertEqual(result["canonical_source"]["status"], "verified")
            self.assertEqual(result["alignment"]["relevance"], "supporting")
            self.assertIn("cybersecurity", result["alignment"]["note"])

            claims.write_text("# Changed claims\n", encoding="utf-8")
            result = career_context.get_context("secplus", context)
            self.assertEqual(
                result["canonical_source"]["status"], "changed_review_required"
            )

    def test_missing_canonical_file_is_disclosed(self):
        with patch.dict(os.environ, {"CAREER_CLAIMS_PATH": "/definitely/missing/claims.md"}):
            result = career_context.get_context("aplus")
        self.assertEqual(result["canonical_source"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
