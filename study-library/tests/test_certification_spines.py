import copy
import json
import tempfile
import unittest
from pathlib import Path

from lib import certification_spines


class TestCertificationSpines(unittest.TestCase):
    def test_registry_is_complete_and_ordered(self):
        registry = certification_spines.load_registry()
        self.assertEqual([item["id"] for item in registry["certifications"]], [
            "aplus", "netplus", "secplus", "cloudplus", "ccna", "ccsp",
        ])
        self.assertEqual(sum(item["exam_sittings"] for item in registry["certifications"]), 7)
        self.assertEqual(len(registry["registry_sha256"]), 64)

    def test_bound_pack_fails_closed_on_domain_drift(self):
        manifest_path = certification_spines.REGISTRY_PATH.parent / "aplus-v15.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        certification_spines.validate_pack_manifest(manifest)
        changed = copy.deepcopy(manifest)
        changed["exams"][0]["domains"][0]["weight"] += 1
        with self.assertRaisesRegex(certification_spines.SpineError, "domains diverge"):
            certification_spines.validate_pack_manifest(changed)

    def test_pre_registry_manifest_remains_readable(self):
        manifest = {"certification_code": "aplus"}
        self.assertEqual(certification_spines.validate_pack_manifest(manifest)["id"], "aplus")


if __name__ == "__main__":
    unittest.main()
