import tempfile
import unittest
from pathlib import Path

from ops.state_store import (
    StateConflictError,
    StateValidationError,
    WaypointStateStore,
    validate_state,
)


def valid_state():
    return {
        "meta": {"name": "David Gomez", "startDate": "2026-08-01"},
        "certs": [
            {
                "id": "aplus",
                "order": 1,
                "kind": "CompTIA",
                "name": "A+",
                "code": "220-1201 / 220-1202",
                "price": 548,
                "clears": "D316 + D317",
                "cu": 8,
                "wlo": 5,
                "whi": 6,
                "status": "todo",
                "exam": "",
                "pass": "",
                "started": "",
                "actualHours": None,
                "estHoursLow": 140,
                "estHoursHigh": 200,
            }
        ],
        "courses": [
            {
                "code": "D197",
                "name": "Version Control",
                "cu": 1,
                "status": "todo",
                "note": "",
            }
        ],
        "log": [],
        "studyEndpoint": "/api/waypoint/summary",
        "studySummary": None,
        "studySummaryReceivedAt": None,
    }


class StateValidationTests(unittest.TestCase):
    def test_valid_state_is_serialized(self):
        self.assertIn('"aplus"', validate_state(valid_state()))

    def test_rejects_duplicate_cert_ids(self):
        state = valid_state()
        state["certs"].append(dict(state["certs"][0]))
        with self.assertRaises(StateValidationError):
            validate_state(state)

    def test_rejects_invalid_log_hours(self):
        state = valid_state()
        state["log"] = [
            {"id": "1", "date": "2026-07-29", "certId": "aplus", "hours": 25, "note": ""}
        ]
        with self.assertRaises(StateValidationError):
            validate_state(state)


class StateStoreTests(unittest.TestCase):
    def test_revisioned_create_update_and_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WaypointStateStore(Path(tmp) / "waypoint.db")
            self.assertIsNone(store.get())
            first = store.save(valid_state(), 0, migration_id="localstorage-v1")
            self.assertEqual(first["revision"], 1)
            self.assertEqual(first["migration_id"], "localstorage-v1")

            changed = valid_state()
            changed["certs"][0]["status"] = "studying"
            second = store.save(changed, 1)
            self.assertEqual(second["revision"], 2)
            self.assertEqual(second["state"]["certs"][0]["status"], "studying")

            with self.assertRaises(StateConflictError):
                store.save(valid_state(), 1)


if __name__ == "__main__":
    unittest.main()
