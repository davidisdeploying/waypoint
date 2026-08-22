import unittest

from lib import db, waypoint_state
from lib.api_logic import ApiError


def valid_state():
    return {
        "meta": {
            "name": "David",
            "startDate": "2026-09-01",
            "wguStartDate": "2027-08-01",
        },
        "certs": [{
            "id": "aplus", "order": 1, "name": "CompTIA A+", "kind": "CompTIA",
            "code": "220-1201 / 220-1202", "exam": "", "pass": "",
            "status": "studying", "price": 548, "cu": 8, "wlo": 5, "whi": 6,
            "started": "", "actualHours": None, "estHoursLow": 140, "estHoursHigh": 200,
        }],
        "courses": [],
        "log": [],
        "studyEndpoint": "/api/waypoint/summary",
        "studySummary": None,
        "studySummaryReceivedAt": None,
    }


class TestWaypointState(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_revisioned_save_and_conflict(self):
        first = waypoint_state.save(self.conn, valid_state(), 0)
        self.assertEqual(first["revision"], 1)
        self.assertEqual(waypoint_state.get(self.conn)["state"]["meta"]["name"], "David")
        with self.assertRaises(ApiError) as caught:
            waypoint_state.save(self.conn, valid_state(), 0)
        self.assertEqual(caught.exception.status, 409)

    def test_import_preserves_source_revision_and_is_fail_closed(self):
        source = {
            "revision": 8,
            "updated_at": "2026-07-29T23:03:14Z",
            "state": valid_state(),
        }
        imported = waypoint_state.import_snapshot(
            self.conn, source, "delta-to-study-v1"
        )
        self.assertEqual(imported["revision"], 8)
        self.assertEqual(imported["migration_id"], "delta-to-study-v1")
        with self.assertRaises(ApiError) as caught:
            waypoint_state.import_snapshot(
                self.conn, source, "delta-to-study-v1"
            )
        self.assertEqual(caught.exception.status, 409)

    def test_rejects_invalid_state(self):
        state = valid_state()
        state["certs"][0]["status"] = "invented"
        with self.assertRaises(ApiError) as caught:
            waypoint_state.save(self.conn, state, 0)
        self.assertEqual(caught.exception.status, 400)

    def test_rejects_invalid_wgu_start_date(self):
        state = valid_state()
        state["meta"]["wguStartDate"] = "August 1, 2027"
        with self.assertRaises(ApiError) as caught:
            waypoint_state.save(self.conn, state, 0)
        self.assertEqual(caught.exception.status, 400)


if __name__ == "__main__":
    unittest.main()
