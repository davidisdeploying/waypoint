"""Project sequential start/finish dates for the certification track.

David studies one certification at a time, never in parallel. That makes hour
attribution exact rather than approximate: total study hours banked between a
cert's `started` stamp and now (or its `pass` stamp, for a completed one) IS
the time spent on that cert -- no need to attribute individual sessions to a
specific exam.

Pure projection math lives here, separate from the HTTP handler in app.py, so
it can be tested without a live server or database.
"""

from __future__ import annotations

from datetime import date, timedelta

MIN_ACTIVE_DAYS_FOR_TRAILING_PACE = 5


def current_pace_hours_per_week(study_goal, analytics_trailing):
    """Prefer a real trailing rate once enough recent activity exists.

    `study_goal` is the parsed result of study_goals.get_goal() (or None).
    `analytics_trailing` is the parsed result of analytics.get_analytics(days=28)
    (or None). Falls back to the stated weekly goal, then to 0 if neither
    source is available.
    """
    if analytics_trailing:
        timeline = analytics_trailing.get("timeline") or []
        active_days = [day for day in timeline if (day.get("study_minutes") or 0) > 0]
        if len(active_days) >= MIN_ACTIVE_DAYS_FOR_TRAILING_PACE:
            total_minutes = sum(day.get("study_minutes") or 0 for day in timeline)
            weeks = len(timeline) / 7.0
            if weeks > 0:
                return (total_minutes / 60.0) / weeks
    if study_goal and study_goal.get("daily_target_minutes"):
        return study_goal["daily_target_minutes"] * 7 / 60.0
    return 0.0


def _mid_hours(cert):
    return (cert["estHoursLow"] + cert["estHoursHigh"]) / 2


def compute_timeline(certs, pace_hours_per_week, hours_since_active_started, today=None):
    """Project each cert's start/finish date, walked in `order`.

    A `passed` cert reports its real history (started/pass/actualHours) and
    contributes nothing further to the projection. The one `studying` cert's
    remaining hours are estimate-minus-actual, projected from today. Every
    `todo`/`scheduled` cert chains from the previous cert's projected finish.
    """
    today = today or date.today()
    cursor = today
    entries = []
    for cert in sorted(certs, key=lambda c: c["order"]):
        status = cert["status"]
        base = {
            "id": cert["id"],
            "order": cert["order"],
            "kind": cert.get("kind", ""),
            "code": cert.get("code", ""),
            "name": cert["name"],
            "status": status,
            "estHoursLow": cert["estHoursLow"],
            "estHoursHigh": cert["estHoursHigh"],
        }
        if status == "passed":
            entries.append({
                **base,
                "started": cert.get("started") or None,
                "finished": cert.get("pass") or None,
                "actualHours": cert.get("actualHours"),
                "projectedStart": None,
                "projectedFinish": None,
            })
            continue

        if status == "studying":
            remaining = max(0.0, _mid_hours(cert) - hours_since_active_started)
            finish = _project(cursor, remaining, pace_hours_per_week)
            entries.append({
                **base,
                "started": cert.get("started") or None,
                "finished": None,
                "actualHours": round(hours_since_active_started, 1),
                "projectedStart": cert.get("started") or today.isoformat(),
                "projectedFinish": finish.isoformat() if finish else None,
            })
            if finish:
                cursor = finish
            continue

        # todo / scheduled: not started yet, chained from the previous cert.
        start = cursor
        finish = _project(start, _mid_hours(cert), pace_hours_per_week)
        entries.append({
            **base,
            "started": None,
            "finished": None,
            "actualHours": None,
            "projectedStart": start.isoformat(),
            "projectedFinish": finish.isoformat() if finish else None,
        })
        if finish:
            cursor = finish
    return entries


def _project(start, hours, pace_hours_per_week):
    if pace_hours_per_week <= 0:
        return None
    weeks = hours / pace_hours_per_week
    return start + timedelta(days=round(weeks * 7))


def evenly_spaced_dates(count, start_date, finish_date):
    """`count` ISO dates spaced evenly across [start_date, finish_date], starting at start_date.

    Shared by synthesize_weeks() and the real-plan week wiring in app.py, so both a
    projected (domain-only) week list and a real (ingested-content) week list place their
    calendar dates the same way.
    """
    if not count or start_date is None or finish_date is None:
        return []
    span_days = max(0, (finish_date - start_date).days)
    days_per = span_days / count
    return [(start_date + timedelta(days=round(i * days_per))).isoformat() for i in range(count)]


def synthesize_weeks(domains, start_date, finish_date):
    """Distribute weeks across a cert's official exam domains, one topic label per week.

    Used only for certs with no real ingested content yet (see lib/cert_domains.py). Every
    domain gets at least one week regardless of how the raw hour math would round it --
    skipping a whole exam domain isn't a real study plan, even a projected one. Weeks beyond
    one-per-domain are handed out proportional to domain weight via largest-remainder
    rounding, so the total always matches the projected week-span exactly. Every returned
    week's `source` is `"projected"` and `progress_percent` is 0 -- there is no real evidence
    behind these yet.

    Intended upgrade path (not yet built): once real books are ingested for one of these
    certs, that cert's weeks should switch to the real-plan path in app.py's h_timeline_get
    (the same one A+ already uses), with each week's supporting chapters/excerpts surfaced
    in support of that week's domain -- these domain labels are exactly what such an
    ingestion would key its content plan against, so the topic names here are not throwaway.
    """
    if not domains or finish_date is None or start_date is None:
        return []
    span_days = max(0, (finish_date - start_date).days)
    total_weeks = max(len(domains), round(span_days / 7) or 1)

    extra = total_weeks - len(domains)
    total_weight = sum(weight for _, weight in domains)
    ideal_extra = [extra * weight / total_weight for _, weight in domains]
    floor_extra = [int(value) for value in ideal_extra]
    remainder = extra - sum(floor_extra)
    by_fraction = sorted(
        range(len(domains)), key=lambda i: ideal_extra[i] - floor_extra[i], reverse=True
    )
    for i in by_fraction[:remainder]:
        floor_extra[i] += 1
    counts = [1 + n for n in floor_extra]

    dates = evenly_spaced_dates(total_weeks, start_date, finish_date)
    weeks = []
    week_number = 1
    for (topic, _weight), count in zip(domains, counts):
        for _ in range(count):
            weeks.append({
                "week_number": week_number,
                "topic": topic,
                "date": dates[week_number - 1],
                "progress_percent": 0,
                "source": "projected",
            })
            week_number += 1
    return weeks
