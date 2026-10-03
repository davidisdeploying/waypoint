import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.timeline import compute_timeline, current_pace_hours_per_week, synthesize_weeks


def _cert(id_, order, status, low, high, started="", pass_="", actual=None):
    return {
        "id": id_, "order": order, "name": id_, "status": status,
        "started": started, "pass": pass_, "actualHours": actual,
        "estHoursLow": low, "estHoursHigh": high,
    }


def _analytics(days_with_minutes):
    """days_with_minutes: list of per-day study_minutes values, oldest first."""
    return {"timeline": [{"date": "irrelevant", "study_minutes": m} for m in days_with_minutes]}


class TestCurrentPace(unittest.TestCase):
    def test_uses_stated_goal_when_no_analytics(self):
        pace = current_pace_hours_per_week({"daily_target_minutes": 60}, None)
        self.assertAlmostEqual(pace, 7.0)

    def test_zero_when_no_signal_at_all(self):
        self.assertEqual(current_pace_hours_per_week(None, None), 0.0)

    def test_prefers_trailing_actual_once_enough_active_days_exist(self):
        # 10 active days of 60 minutes each over a 28-day window; goal says something else entirely.
        analytics = _analytics([60] * 10 + [0] * 18)
        pace = current_pace_hours_per_week({"daily_target_minutes": 999}, analytics)
        # total = 600 min = 10 hours, over 28/7 = 4 weeks -> 2.5 hrs/week
        self.assertAlmostEqual(pace, 2.5)

    def test_falls_back_to_goal_when_too_few_active_days(self):
        analytics = _analytics([60, 60, 60] + [0] * 25)  # only 3 active days
        pace = current_pace_hours_per_week({"daily_target_minutes": 60}, analytics)
        self.assertAlmostEqual(pace, 7.0)


class TestComputeTimeline(unittest.TestCase):
    def test_sequential_projection_across_passed_studying_and_todo(self):
        today = date(2026, 3, 1)
        certs = [
            _cert("aplus", 1, "passed", 80, 120, started="2026-01-01", pass_="2026-02-01", actual=100),
            _cert("netplus", 2, "studying", 60, 100, started="2026-02-01"),
            _cert("secplus", 3, "todo", 40, 60),
        ]
        entries = compute_timeline(certs, pace_hours_per_week=10.0, hours_since_active_started=20.0, today=today)
        by_id = {e["id"]: e for e in entries}

        passed = by_id["aplus"]
        self.assertEqual(passed["started"], "2026-01-01")
        self.assertEqual(passed["finished"], "2026-02-01")
        self.assertEqual(passed["actualHours"], 100)
        self.assertIsNone(passed["projectedStart"])
        self.assertIsNone(passed["projectedFinish"])

        studying = by_id["netplus"]
        # mid estimate 80, minus 20 banked = 60 remaining / 10 hrs/week = 6 weeks = 42 days
        expected_finish = today + timedelta(days=42)
        self.assertEqual(studying["projectedStart"], "2026-02-01")
        self.assertEqual(studying["projectedFinish"], expected_finish.isoformat())
        self.assertEqual(studying["actualHours"], 20.0)

        todo = by_id["secplus"]
        # chains from netplus's projected finish; mid estimate 50 / 10 hrs/week = 5 weeks = 35 days
        expected_start = expected_finish
        expected_todo_finish = expected_start + timedelta(days=35)
        self.assertEqual(todo["projectedStart"], expected_start.isoformat())
        self.assertEqual(todo["projectedFinish"], expected_todo_finish.isoformat())
        self.assertIsNone(todo["started"])

    def test_zero_pace_yields_no_projection_but_does_not_crash(self):
        certs = [_cert("aplus", 1, "todo", 80, 120)]
        entries = compute_timeline(certs, pace_hours_per_week=0.0, hours_since_active_started=0.0)
        self.assertIsNone(entries[0]["projectedFinish"])
        self.assertIsNotNone(entries[0]["projectedStart"])

    def test_studying_cert_with_hours_already_exceeding_estimate_shows_zero_remaining(self):
        certs = [_cert("aplus", 1, "studying", 80, 120, started="2026-01-01")]
        entries = compute_timeline(certs, pace_hours_per_week=10.0, hours_since_active_started=500.0, today=date(2026, 3, 1))
        self.assertEqual(entries[0]["projectedFinish"], date(2026, 3, 1).isoformat())


class TestSynthesizeWeeks(unittest.TestCase):
    def test_distributes_proportional_to_weight_and_sums_exactly(self):
        domains = [("Big", 60), ("Medium", 30), ("Small", 10)]
        # 20-week span -> plenty of weeks to see real proportional distribution.
        weeks = synthesize_weeks(domains, date(2026, 1, 1), date(2026, 1, 1) + timedelta(weeks=20))
        self.assertEqual(len(weeks), 20)
        counts = {}
        for week in weeks:
            counts[week["topic"]] = counts.get(week["topic"], 0) + 1
        self.assertEqual(sum(counts.values()), 20)
        self.assertGreater(counts["Big"], counts["Medium"])
        self.assertGreater(counts["Medium"], counts["Small"])

    def test_every_domain_gets_at_least_one_week_even_when_span_is_short(self):
        # 6 domains, a span that would round to fewer than 6 weeks on hour math alone.
        domains = [(f"Domain {i}", 100 // 6) for i in range(6)]
        weeks = synthesize_weeks(domains, date(2026, 1, 1), date(2026, 1, 1) + timedelta(weeks=3))
        topics = {week["topic"] for week in weeks}
        self.assertEqual(len(topics), 6)  # every domain represented at least once
        self.assertEqual(len(weeks), 6)   # floored up to one-per-domain, not truncated

    def test_every_week_is_marked_projected_with_zero_progress(self):
        domains = [("Only Domain", 100)]
        weeks = synthesize_weeks(domains, date(2026, 1, 1), date(2026, 2, 1))
        self.assertTrue(all(w["source"] == "projected" for w in weeks))
        self.assertTrue(all(w["progress_percent"] == 0 for w in weeks))

    def test_dates_are_spaced_across_the_span_and_start_at_start_date(self):
        domains = [("A", 50), ("B", 50)]
        start = date(2026, 1, 1)
        finish = start + timedelta(weeks=10)
        weeks = synthesize_weeks(domains, start, finish)
        self.assertEqual(weeks[0]["date"], start.isoformat())
        dates = [w["date"] for w in weeks]
        self.assertEqual(dates, sorted(dates))  # strictly non-decreasing chronological order

    def test_empty_domains_or_missing_dates_returns_empty(self):
        self.assertEqual(synthesize_weeks([], date(2026, 1, 1), date(2026, 2, 1)), [])
        self.assertEqual(synthesize_weeks([("A", 100)], None, date(2026, 2, 1)), [])
        self.assertEqual(synthesize_weeks([("A", 100)], date(2026, 1, 1), None), [])


if __name__ == "__main__":
    unittest.main()
