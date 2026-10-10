"""Heartbeat clamping, local-time bucketing, and the weekly study goal."""

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import daily_sessions, db, study_clock, study_goals
from lib.api_logic import ApiError

START = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)  # Monday, 10:00 Central


def _session(conn, started=START):
    with patch("lib.daily_sessions._utcnow", return_value=started):
        return daily_sessions.start(conn, 25, {"title": "Study"})


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()


class TestRunningHorizon(_Base):
    def test_a_silent_client_stops_being_credited(self):
        # The browser was killed: no pause, no further heartbeat. Four hours
        # later the session must not have banked four hours.
        active = _session(self.conn)
        with patch("lib.daily_sessions._utcnow", return_value=START + timedelta(hours=4)):
            row = self.conn.execute(
                "SELECT * FROM guided_study_sessions WHERE id = ?", (active["id"],)
            ).fetchone()
            seconds = daily_sessions._effective_seconds(row)
        self.assertEqual(seconds, daily_sessions.HEARTBEAT_GRACE_SECONDS)

    def test_heartbeats_extend_the_credited_window(self):
        active = _session(self.conn)
        for minute in range(1, 6):
            with patch("lib.daily_sessions._utcnow", return_value=START + timedelta(minutes=minute)):
                daily_sessions.heartbeat(self.conn, active["id"])
        with patch("lib.daily_sessions._utcnow", return_value=START + timedelta(minutes=5, seconds=30)):
            row = self.conn.execute(
                "SELECT * FROM guided_study_sessions WHERE id = ?", (active["id"],)
            ).fetchone()
            seconds = daily_sessions._effective_seconds(row)
        self.assertEqual(seconds, 330)

    def test_stale_session_is_paused_at_its_last_proof_of_life(self):
        active = _session(self.conn)
        with patch("lib.daily_sessions._utcnow", return_value=START + timedelta(hours=6)):
            overview = daily_sessions.overview(self.conn, {"title": "Study"})
        self.assertEqual(overview["active"]["tracking_state"], "paused")
        self.assertEqual(
            overview["active"]["active_seconds"], daily_sessions.HEARTBEAT_GRACE_SECONDS
        )

    def test_a_live_session_is_not_reconciled(self):
        active = _session(self.conn)
        with patch("lib.daily_sessions._utcnow", return_value=START + timedelta(seconds=30)):
            daily_sessions.heartbeat(self.conn, active["id"])
            overview = daily_sessions.overview(self.conn, {"title": "Study"})
        self.assertEqual(overview["active"]["tracking_state"], "running")


class TestLocalDayBoundaries(_Base):
    def test_week_starts_on_local_monday(self):
        # Sunday evening Central is still last week, though it is Monday in UTC.
        sunday_night = datetime(2026, 8, 16, 3, 0, tzinfo=timezone.utc)  # Sun 22:00 CDT
        self.assertEqual(study_clock.week_start(now=sunday_night), date(2026, 8, 10))

    def test_evening_session_counts_as_today_not_tomorrow(self):
        evening = datetime(2026, 8, 10, 23, 30, tzinfo=timezone.utc)  # Mon 18:30 CDT
        self.assertEqual(study_clock.local_date(evening.isoformat()), date(2026, 8, 10))

    def test_day_bounds_cover_the_local_day(self):
        begin, end = study_clock.day_bounds_utc(date(2026, 8, 10))
        self.assertEqual(begin, "2026-08-10T05:00:00+00:00")
        self.assertEqual(end, "2026-08-11T05:00:00+00:00")


class TestWeeklyGoal(_Base):
    def test_weekly_target_is_the_daily_rate_times_seven(self):
        goal = study_goals.set_goal(self.conn, 45, week_start=date(2026, 8, 10))
        self.assertEqual(goal["daily_target_minutes"], 45)
        self.assertEqual(goal["weekly_target_minutes"], 315)

    def test_unset_week_asks_for_a_selection(self):
        goal = study_goals.get_goal(self.conn, week_start=date(2026, 8, 10))
        self.assertTrue(goal["needs_selection"])
        self.assertIsNone(goal["percent"])

    def test_completed_sessions_fill_the_bar(self):
        study_goals.set_goal(self.conn, 30, week_start=date(2026, 8, 10))
        self.conn.execute(
            "INSERT INTO guided_study_sessions(status, started_at, ended_at, target_minutes, "
            "duration_minutes, active_seconds, tracking_state, task_title, created_at, updated_at) "
            "VALUES ('completed', ?, ?, 25, 42, 2520, 'paused', 'Study', ?, ?)",
            (START.isoformat(), START.isoformat(), START.isoformat(), START.isoformat()),
        )
        self.conn.commit()
        goal = study_goals.get_goal(self.conn, week_start=date(2026, 8, 10))
        self.assertEqual(goal["completed_minutes"], 42)
        self.assertEqual(goal["percent"], 20)  # 42 of 210
        self.assertEqual(goal["minutes_remaining"], 168)

    def test_the_running_session_counts_live(self):
        study_goals.set_goal(self.conn, 30, week_start=date(2026, 8, 10))
        active = _session(self.conn)
        checked_at = START + timedelta(minutes=10)
        with patch("lib.daily_sessions._utcnow", return_value=checked_at):
            daily_sessions.heartbeat(self.conn, active["id"])
            goal = study_goals.get_goal(
                self.conn,
                week_start=date(2026, 8, 10),
                effective_seconds=lambda row: daily_sessions._effective_seconds(row),
                now_utc=checked_at.isoformat(),
            )
        self.assertEqual(goal["live_minutes"], 10)
        self.assertEqual(goal["minutes_done"], 10)

    def test_a_boundary_spanning_session_credits_the_week_it_is_running_in(self):
        # Started Sunday night Central (last week) and still running past the
        # Monday-00:00 Central boundary. It must show live minutes for the week
        # it is running in *now* -- not disappear because started_at belongs to
        # last week -- and last week must not also claim it.
        study_goals.set_goal(self.conn, 30, week_start=date(2026, 8, 3))
        study_goals.set_goal(self.conn, 30, week_start=date(2026, 8, 10))
        boundary_start = datetime(2026, 8, 10, 4, 50, tzinfo=timezone.utc)  # Sun 23:50 CDT
        active = _session(self.conn, started=boundary_start)
        after_boundary = boundary_start + timedelta(minutes=20)  # Mon 00:10 CDT
        with patch("lib.daily_sessions._utcnow", return_value=after_boundary):
            daily_sessions.heartbeat(self.conn, active["id"])
            this_week = study_goals.get_goal(
                self.conn,
                week_start=date(2026, 8, 10),
                effective_seconds=lambda row: daily_sessions._effective_seconds(row),
                now_utc=after_boundary.isoformat(),
            )
            last_week = study_goals.get_goal(
                self.conn,
                week_start=date(2026, 8, 3),
                effective_seconds=lambda row: daily_sessions._effective_seconds(row),
                now_utc=after_boundary.isoformat(),
            )
        self.assertEqual(this_week["live_minutes"], 20)
        self.assertEqual(last_week["live_minutes"], 0)

    def test_completed_minutes_land_in_the_week_the_session_ended(self):
        # The chosen rule: a session's whole duration belongs to the week (and
        # day) it ended in, never split across the boundary. A session that
        # started Sunday (last week) but ended Monday (this week) must show up
        # entirely in this week's completed minutes, not last week's.
        study_goals.set_goal(self.conn, 30, week_start=date(2026, 8, 3))
        study_goals.set_goal(self.conn, 30, week_start=date(2026, 8, 10))
        started = datetime(2026, 8, 10, 4, 50, tzinfo=timezone.utc)  # Sun 23:50 CDT
        ended = datetime(2026, 8, 10, 5, 12, tzinfo=timezone.utc)  # Mon 00:12 CDT
        self.conn.execute(
            "INSERT INTO guided_study_sessions(status, started_at, ended_at, target_minutes, "
            "duration_minutes, active_seconds, tracking_state, task_title, created_at, updated_at) "
            "VALUES ('completed', ?, ?, 25, 22, 1320, 'paused', 'Study', ?, ?)",
            (started.isoformat(), ended.isoformat(), started.isoformat(), ended.isoformat()),
        )
        self.conn.commit()
        this_week = study_goals.get_goal(self.conn, week_start=date(2026, 8, 10))
        last_week = study_goals.get_goal(self.conn, week_start=date(2026, 8, 3))
        self.assertEqual(this_week["completed_minutes"], 22)
        self.assertEqual(last_week["completed_minutes"], 0)

    def test_percent_is_capped_but_minutes_are_not(self):
        study_goals.set_goal(self.conn, 30, week_start=date(2026, 8, 10))
        self.conn.execute(
            "INSERT INTO guided_study_sessions(status, started_at, ended_at, target_minutes, "
            "duration_minutes, active_seconds, tracking_state, task_title, created_at, updated_at) "
            "VALUES ('completed', ?, ?, 25, 400, 24000, 'paused', 'Study', ?, ?)",
            (START.isoformat(), START.isoformat(), START.isoformat(), START.isoformat()),
        )
        self.conn.commit()
        goal = study_goals.get_goal(self.conn, week_start=date(2026, 8, 10))
        self.assertEqual(goal["percent"], 100)
        self.assertEqual(goal["minutes_done"], 400)  # honest, not clipped to the target

    def test_rejects_an_out_of_range_rate(self):
        with self.assertRaises(ApiError):
            study_goals.set_goal(self.conn, 0)
        with self.assertRaises(ApiError):
            study_goals.set_goal(self.conn, 999)
        with self.assertRaises(ApiError):
            study_goals.set_goal(self.conn, "45")


if __name__ == "__main__":
    unittest.main()
