#!/usr/bin/env python3
"""Study Library: stdlib-only JSON API + static file server.

Local-only prototype. Binds to 127.0.0.1 by default. Mutation endpoints are
protected with a same-origin check plus a per-process CSRF token (see
README.md "Privacy / auth / deployment boundary" for why this is NOT
sufficient for a real multi-user deployment).
"""
import json
import mimetypes
import os
import re
import secrets
import sys
import traceback
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import db
from lib import api_logic
from lib import annotations
from lib import analytics
from lib import labs
from lib import lab_catalog
from lib import practice_exams
from lib import diagnostics
from lib import coach
from lib import waypoint_state
from lib import jobs
from lib import daily_sessions
from lib import study_goals
from lib import timeline
from lib import certification_spines
from lib import career_context
from lib import learning
from lib import mastery
from lib import retention
from lib import readiness
from lib import study_clock
from lib import epub_reader
from lib import learning_requests
from lib.api_logic import ApiError

REPO_ROOT = Path(__file__).resolve().parent
STATIC_DIR = REPO_ROOT / "static"
MAX_BODY_BYTES = 1_000_000

CSRF_TOKEN = secrets.token_urlsafe(32)


def _read_service_token():
    path = os.environ.get("STUDY_LIBRARY_SERVICE_TOKEN_FILE", "")
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"cannot read Study Library service token: {path}") from exc


SERVICE_TOKEN = _read_service_token()


def json_bytes(obj):
    return json.dumps(obj, default=str).encode("utf-8")


class Route:
    def __init__(self, method, pattern, handler, mutation=False):
        self.method = method
        self.regex = re.compile(pattern)
        self.handler = handler
        self.mutation = mutation


class BinaryResponse:
    def __init__(self, body, content_type, cache_control="private, max-age=86400"):
        self.body = body
        self.content_type = content_type
        self.cache_control = cache_control


class Handler(BaseHTTPRequestHandler):
    server_version = "StudyLibrary/1"
    routes = []  # populated below

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # --- helpers ---------------------------------------------------------

    def _send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_binary(self, status, payload):
        self.send_response(status)
        self.send_header("Content-Type", payload.content_type)
        self.send_header("Content-Length", str(len(payload.body)))
        self.send_header("Cache-Control", payload.cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.end_headers()
        self.wfile.write(payload.body)

    def _error(self, status, message):
        self._send_json(status, {"error": message})

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "request body too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "invalid JSON body")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON body must be an object")
        return data

    def _same_origin_ok(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if not origin:
            return True  # no Origin header: not a browser cross-site request
        origin_host = urlsplit(origin).netloc
        return origin_host == host

    def _csrf_ok(self):
        if (
            urlsplit(self.path).path == "/api/waypoint/state"
            and self.headers.get("X-Waypoint-Trusted-Mutation") == "1"
            and self._service_auth_ok()
        ):
            return True
        token = self.headers.get("X-Csrf-Token") or self.headers.get("X-CSRF-Token")
        return token is not None and secrets.compare_digest(token, CSRF_TOKEN)

    def _service_auth_ok(self):
        if not SERVICE_TOKEN:
            return True
        token = self.headers.get("X-Waypoint-Service-Token")
        return token is not None and secrets.compare_digest(token, SERVICE_TOKEN)

    def _dispatch(self, method):
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query)
        if path.startswith("/api/") and path != "/api/health" and not self._service_auth_ok():
            self._error(401, "missing or invalid service credential")
            return
        conn = db.connect()
        try:
            for route in self.routes:
                if route.method != method:
                    continue
                m = route.regex.match(path)
                if not m:
                    continue
                if route.mutation:
                    if not self._same_origin_ok():
                        self._error(403, "cross-origin request rejected")
                        return
                    if not self._csrf_ok():
                        self._error(403, "missing or invalid CSRF token")
                        return
                body = self._read_json_body() if method in ("POST", "PUT", "PATCH") else None
                status, payload = route.handler(self, conn, m.groupdict(), query, body)
                if isinstance(payload, BinaryResponse):
                    self._send_binary(status, payload)
                else:
                    self._send_json(status, payload)
                return
            if method == "GET":
                self._serve_static(path)
                return
            self._error(404, "not found")
        except ApiError as exc:
            self._error(exc.status, exc.message)
        except Exception:
            traceback.print_exc()
            self._error(500, "internal server error")
        finally:
            conn.close()

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        rel = path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR:
            self._error(403, "forbidden")
            return
        if not target.is_file():
            self._error(404, "not found")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


# --- Route handlers ---------------------------------------------------------

def h_health(handler, conn, params, query, body):
    return 200, {
        "status": "ok",
        "time": api_logic.now_iso(),
        "schema_version": db.get_schema_version(conn),
        "service_auth": "required" if SERVICE_TOKEN else "disabled",
    }


def h_csrf_token(handler, conn, params, query, body):
    return 200, {"csrf_token": CSRF_TOKEN}


def h_dashboard(handler, conn, params, query, body):
    return 200, api_logic.get_dashboard(conn)


def h_study_next(handler, conn, params, query, body):
    limit = (query.get("limit") or [None])[0]
    return 200, api_logic.get_study_next(conn, limit=limit)


def h_progress(handler, conn, params, query, body):
    return 200, api_logic.get_progress_summary(conn)


def h_analytics(handler, conn, params, query, body):
    return 200, analytics.get_analytics(conn, days=(query.get("days") or [30])[0])


def h_hours_since(handler, conn, params, query, body):
    since = (query.get("since") or [None])[0]
    if not since:
        raise ApiError(400, "since is required")
    return 200, {"since": since, "hours": api_logic.hours_since(conn, since=since)}


def h_mastery_map(handler, conn, params, query, body):
    exam = (query.get("exam") or [None])[0]
    return 200, mastery.get_mastery_map(conn, exam=exam)


def h_readiness(handler, conn, params, query, body):
    exam = (query.get("exam") or [None])[0]
    return 200, readiness.get_exam_readiness(conn, exam_code=exam)


def h_adaptive_curriculum(handler, conn, params, query, body):
    days = (query.get("days") or [None])[0]
    minutes_per_day = (query.get("minutes_per_day") or [None])[0]
    return 200, api_logic.get_adaptive_curriculum(
        conn, days=days, minutes_per_day=minutes_per_day
    )


def h_ai_context(handler, conn, params, query, body):
    return 200, api_logic.get_ai_context(
        conn,
        query=(query.get("q") or [None])[0],
        exam=(query.get("exam") or [None])[0],
        limit=(query.get("limit") or [None])[0],
        max_chars=(query.get("max_chars") or [None])[0],
        days=(query.get("days") or [None])[0],
        minutes_per_day=(query.get("minutes_per_day") or [None])[0],
    )


def h_coach_ask(handler, conn, params, query, body):
    return 200, coach.ask(conn, body)


def h_books(handler, conn, params, query, body):
    return 200, {"books": api_logic.list_books(conn)}


def h_certification_pack(handler, conn, params, query, body):
    result = api_logic.get_certification_pack(
        conn, unquote(params["certification_code"])
    )
    if not result:
        raise ApiError(404, "certification pack not found")
    return 200, result


def h_certification_spines(handler, conn, params, query, body):
    return 200, certification_spines.registry_summary()


def h_certification_spine(handler, conn, params, query, body):
    result = certification_spines.get_spine(unquote(params["certification_id"]))
    if not result:
        raise ApiError(404, "certification spine not found")
    return 200, result


def h_career_context(handler, conn, params, query, body):
    certification_id = (query.get("certification") or [None])[0]
    return 200, career_context.get_context(certification_id)


def h_certification_pack_builds(handler, conn, params, query, body):
    result = api_logic.get_certification_pack_builds(
        conn, unquote(params["certification_code"])
    )
    if not result:
        raise ApiError(404, "certification pack build history not found")
    return 200, result


def h_objective_dossiers(handler, conn, params, query, body):
    result = api_logic.get_objective_dossier_summary(
        conn, unquote(params["certification_code"])
    )
    if not result:
        raise ApiError(404, "objective dossiers not found")
    return 200, result


def h_objective_dossier(handler, conn, params, query, body):
    certification_code = (query.get("certification") or ["aplus"])[0]
    result = api_logic.get_objective_dossier(
        conn, int(params["id"]), certification_code
    )
    if not result:
        raise ApiError(404, "objective dossier not found")
    return 200, result


def h_search(handler, conn, params, query, body):
    q = (query.get("q") or [None])[0]
    book = (query.get("book") or [None])[0]
    exam = (query.get("exam") or [None])[0]
    limit = (query.get("limit") or [None])[0]
    results = api_logic.search_sections(conn, q, book=book, exam=exam, limit=limit)
    return 200, {"query": q, "results": results}


def h_section(handler, conn, params, query, body):
    section = api_logic.get_section(conn, unquote(params["stable_id"]))
    if not section:
        raise ApiError(404, "section not found")
    return 200, section


def h_reader_section(handler, conn, params, query, body):
    section = epub_reader.get_reader_section(conn, unquote(params["stable_id"]))
    if not section:
        raise ApiError(404, "section not found")
    return 200, section


def h_reader_asset(handler, conn, params, query, body):
    try:
        data, content_type = epub_reader.get_reader_asset(
            conn,
            unquote(params["stable_id"]),
            unquote(params["member"]),
        )
    except epub_reader.EpubUnavailable:
        raise ApiError(404, "EPUB image not found")
    return 200, BinaryResponse(data, content_type)


def h_objectives(handler, conn, params, query, body):
    exam = (query.get("exam") or [None])[0]
    return 200, {"objectives": api_logic.list_objectives(conn, exam=exam)}


def h_objective(handler, conn, params, query, body):
    obj = api_logic.get_objective(conn, int(params["id"]))
    if not obj:
        raise ApiError(404, "objective not found")
    obj["mastery"] = mastery.get_objective_mastery(conn, int(params["id"]))
    obj["learning"] = learning.get_objective_state(conn, int(params["id"]))
    obj["retention"] = retention.get_objective_state(conn, int(params["id"]))
    return 200, obj


def h_learning_event(handler, conn, params, query, body):
    return 200, learning.record_event(
        conn,
        body.get("objective_id"),
        body.get("event_type"),
        event_key=body.get("event_key"),
        metadata=body.get("metadata"),
    )


def h_annotations_get(handler, conn, params, query, body):
    objective_id = (query.get("objective_id") or [None])[0]
    return 200, {
        "annotations": annotations.list_annotations(
            conn, int(objective_id) if objective_id is not None else None
        )
    }


def h_annotations_create(handler, conn, params, query, body):
    return 201, annotations.create_annotation(
        conn,
        body.get("objective_id"),
        body.get("kind"),
        section_stable_id=body.get("section_stable_id"),
        quote_text=body.get("quote_text"),
        prefix_text=body.get("prefix_text"),
        suffix_text=body.get("suffix_text"),
        note_text=body.get("note_text"),
        content_sha256=body.get("content_sha256"),
        anchor_start=body.get("anchor_start"),
        anchor_end=body.get("anchor_end"),
        client_key=body.get("client_key"),
    )


def h_annotations_update(handler, conn, params, query, body):
    result = annotations.update_annotation(
        conn,
        int(params["id"]),
        note_text=body.get("note_text"),
        archived=body.get("archived"),
    )
    if result is None:
        raise ApiError(404, "annotation not found")
    return 200, result


def h_labs_get(handler, conn, params, query, body):
    objective_id = (query.get("objective_id") or [None])[0]
    return 200, labs.list_labs(
        conn, int(objective_id) if objective_id is not None else None
    )


def h_lab_catalog_get(handler, conn, params, query, body):
    return 200, lab_catalog.list_templates(
        conn,
        exam=(query.get("exam") or [None])[0],
        objective_id=(query.get("objective_id") or [None])[0],
    )


def h_lab_catalog_launch(handler, conn, params, query, body):
    return 201, lab_catalog.launch_template(
        conn, params["slug"], client_key=body.get("client_key")
    )


def h_labs_create(handler, conn, params, query, body):
    return 201, labs.create_lab(
        conn,
        body.get("objective_id"),
        body.get("title"),
        body.get("goal_text"),
        environment_text=body.get("environment_text"),
        client_key=body.get("client_key"),
    )


def h_labs_update(handler, conn, params, query, body):
    result = labs.update_lab(
        conn,
        int(params["id"]),
        title=body.get("title"),
        goal_text=body.get("goal_text"),
        environment_text=body.get("environment_text"),
        evidence_text=body.get("evidence_text"),
        reflection_text=body.get("reflection_text"),
        status=body.get("status"),
        completion_level=body.get("completion_level"),
        archived=body.get("archived"),
    )
    if result is None:
        raise ApiError(404, "lab not found")
    return 200, result


def h_practice_exams_get(handler, conn, params, query, body):
    return 200, practice_exams.overview(conn)


def h_practice_exams_start(handler, conn, params, query, body):
    return 201, practice_exams.start_attempt(conn, body.get("exam_code"))


def h_practice_exam_get(handler, conn, params, query, body):
    return 200, practice_exams.get_attempt(conn, int(params["id"]))


def h_practice_exam_answer(handler, conn, params, query, body):
    return 200, practice_exams.save_answer(
        conn,
        int(params["id"]),
        body.get("question_id"),
        body.get("selected"),
    )


def h_practice_exam_submit(handler, conn, params, query, body):
    return 200, practice_exams.submit_attempt(conn, int(params["id"]))


def h_practice_exam_abandon(handler, conn, params, query, body):
    return 200, practice_exams.abandon_attempt(conn, int(params["id"]))


def h_retention_queue(handler, conn, params, query, body):
    return 200, retention.get_queue(
        conn,
        exam=(query.get("exam") or [None])[0],
        horizon_days=(query.get("horizon_days") or [7])[0],
        limit=(query.get("limit") or [50])[0],
    )


def h_retention_review(handler, conn, params, query, body):
    return 200, retention.record_review(
        conn,
        body.get("objective_id"),
        body.get("rating"),
        event_key=body.get("event_key"),
    )


def h_plan(handler, conn, params, query, body):
    plan = api_logic.get_plan(conn)
    if not plan:
        raise ApiError(404, "no study plan seeded")
    return 200, plan


def h_plan_task_update(handler, conn, params, query, body):
    task = api_logic.update_plan_task(
        conn, int(params["id"]),
        completed=body.get("completed"),
        notes=body.get("notes"),
    )
    if not task:
        raise ApiError(404, "task not found")
    return 200, task


def h_sessions_get(handler, conn, params, query, body):
    limit = (query.get("limit") or [None])[0]
    return 200, {"sessions": api_logic.list_sessions(conn, limit=limit)}


def h_sessions_post(handler, conn, params, query, body):
    session = api_logic.create_session(
        conn,
        occurred_at=body.get("occurred_at"),
        duration_minutes=body.get("duration_minutes"),
        exam_id=body.get("exam_id"),
        week_id=body.get("week_id"),
        notes=body.get("notes"),
    )
    return 201, session


def h_daily_session_get(handler, conn, params, query, body):
    primary = api_logic.get_study_next(conn, limit=1).get("primary")
    return 200, daily_sessions.overview(conn, primary)


def h_daily_session_history(handler, conn, params, query, body):
    limit = (query.get("limit") or [None])[0]
    return 200, {"sessions": daily_sessions.history(conn, limit=limit)}


def h_daily_session_start(handler, conn, params, query, body):
    primary = api_logic.get_study_next(conn, limit=1).get("primary")
    return 201, daily_sessions.start(
        conn, body.get("target_minutes"), primary
    )


def h_daily_session_event(handler, conn, params, query, body):
    return 200, daily_sessions.log_event(
        conn,
        body.get("event_type"),
        body.get("label"),
        event_key=body.get("event_key"),
        metadata=body.get("metadata"),
    )


def h_daily_session_pause(handler, conn, params, query, body):
    return 200, daily_sessions.pause(
        conn, int(params["id"]), occurred_at=(body or {}).get("occurred_at")
    )


def h_daily_session_resume(handler, conn, params, query, body):
    return 200, daily_sessions.resume(conn, int(params["id"]))


def h_daily_session_heartbeat(handler, conn, params, query, body):
    return 200, daily_sessions.heartbeat(conn, int(params["id"]))


def h_study_goal_get(handler, conn, params, query, body):
    return 200, study_goals.get_goal(
        conn,
        effective_seconds=daily_sessions._effective_seconds,
        now_utc=daily_sessions._utcnow().isoformat(),
    )


def h_study_goal_set(handler, conn, params, query, body):
    return 200, study_goals.set_goal(conn, body.get("daily_target_minutes"))


def h_daily_session_finish(handler, conn, params, query, body):
    return 200, daily_sessions.finish(
        conn, int(params["id"]), notes=body.get("notes")
    )


def h_daily_session_abandon(handler, conn, params, query, body):
    return 200, daily_sessions.abandon(conn, int(params["id"]))


def h_daily_session_delete(handler, conn, params, query, body):
    return 200, daily_sessions.delete_recorded(conn, int(params["id"]))


def h_attempts_get(handler, conn, params, query, body):
    limit = (query.get("limit") or [None])[0]
    return 200, {"attempts": api_logic.list_attempts(conn, limit=limit)}


def h_attempts_post(handler, conn, params, query, body):
    attempt = api_logic.create_attempt(
        conn,
        exam_id=body.get("exam_id"),
        score=body.get("score"),
        total=body.get("total"),
        occurred_at=body.get("occurred_at"),
        objective_id=body.get("objective_id"),
        notes=body.get("notes"),
        held_out=bool(body.get("held_out", False)),
    )
    return 201, attempt


def h_diag_scopes(handler, conn, params, query, body):
    return 200, {"scopes": diagnostics.list_scopes(conn)}


def h_diag_scope(handler, conn, params, query, body):
    return 200, diagnostics.get_scope(conn, int(params["id"]))


def h_diag_scope_start(handler, conn, params, query, body):
    mode = (body or {}).get("mode", "diagnostic")
    attempt = diagnostics.start_attempt(conn, int(params["id"]), mode)
    return 201, attempt


def h_diag_attempt(handler, conn, params, query, body):
    return 200, diagnostics.get_attempt(conn, int(params["id"]))


def h_diag_attempt_submit(handler, conn, params, query, body):
    responses = (body or {}).get("responses")
    result = diagnostics.submit_attempt(conn, int(params["id"]), responses)
    return 200, result


def h_diag_attempt_results(handler, conn, params, query, body):
    return 200, diagnostics.get_attempt_results(conn, int(params["id"]))


def h_diag_attempt_abandon(handler, conn, params, query, body):
    return 200, diagnostics.abandon_attempt(conn, int(params["id"]))


def h_remediation_reviewed(handler, conn, params, query, body):
    item = diagnostics.mark_reviewed(conn, int(params["id"]))
    return 200, item


def h_waypoint_summary(handler, conn, params, query, body):
    host = os.environ.get("STUDY_LIBRARY_HOST", "127.0.0.1")
    port = os.environ.get("STUDY_LIBRARY_PORT", "8840")
    base_url = f"http://{host}:{port}"
    return 200, api_logic.get_waypoint_summary(conn, base_url)


def h_export(handler, conn, params, query, body):
    host = os.environ.get("STUDY_LIBRARY_HOST", "127.0.0.1")
    port = os.environ.get("STUDY_LIBRARY_PORT", "8840")
    base_url = f"http://{host}:{port}"
    return 200, api_logic.export_snapshot(conn, base_url)


def h_waypoint_state_get(handler, conn, params, query, body):
    state = waypoint_state.get(conn)
    if state is None:
        raise ApiError(404, "Waypoint state is not initialized")
    return 200, state


def h_waypoint_state_post(handler, conn, params, query, body):
    return 200, waypoint_state.save(
        conn,
        body.get("state"),
        body.get("expected_revision"),
        migration_id=body.get("migration_id"),
    )


def _parse_date(value):
    return date.fromisoformat(value) if value else None


def _real_weeks(plan, start_date, finish_date):
    """A cert's real ingested plan_weeks, with task-completion progress and interpolated dates."""
    plan_weeks = plan["weeks"]
    dates = timeline.evenly_spaced_dates(len(plan_weeks), start_date, finish_date)
    weeks = []
    for week, iso_date in zip(plan_weeks, dates):
        tasks = week.get("tasks") or []
        done = sum(1 for t in tasks if t.get("completed") or t.get("exemption_reason"))
        weeks.append({
            "week_number": week["week_number"],
            "topic": week.get("focus") or week.get("title"),
            "date": iso_date,
            "progress_percent": round(done / len(tasks) * 100) if tasks else 0,
            "source": "real",
        })
    return weeks


def h_timeline_get(handler, conn, params, query, body):
    stored = waypoint_state.get(conn)
    certs = ((stored or {}).get("state") or {}).get("certs", [])
    active = next((cert for cert in certs if cert.get("status") == "studying"), None)
    hours_since_active_started = 0.0
    if active and active.get("started"):
        hours_since_active_started = api_logic.hours_since(conn, since=active["started"])
    study_goal = study_goals.get_goal(
        conn,
        effective_seconds=daily_sessions._effective_seconds,
        now_utc=daily_sessions._utcnow().isoformat(),
    )
    analytics_trailing = analytics.get_analytics(conn, days=28)
    pace = timeline.current_pace_hours_per_week(study_goal, analytics_trailing)
    entries = timeline.compute_timeline(
        certs, pace, hours_since_active_started, today=study_clock.today()
    )
    spine_registry = certification_spines.load_registry()
    spines_by_id = {item["id"]: item for item in spine_registry["certifications"]}

    # Only certs with real ingested content (today: just A+) get a real week-by-week plan;
    # everything else gets a domain-only projection. Matched by exam code, not a hardcoded
    # cert id, so a second cert's real plan (WAYPOINT-CERT-PORTABILITY-1) picks this up for
    # free once it exists.
    real_plan = api_logic.get_plan(conn)
    real_plan_exam_codes = (
        {w["exam_code"] for w in real_plan["weeks"] if w.get("exam_code")} if real_plan else set()
    )
    for entry in entries:
        spine = spines_by_id.get(entry["id"])
        entry["spine"] = {
            "registry_version": spine_registry["registry_version"],
            "scope_status": spine["scope_status"] if spine else "missing",
            "exam_sittings": spine["exam_sittings"] if spine else None,
            "official_source_status": (
                "hash_verified"
                if spine and all(
                    exam["official_source"]["verification_status"] == "hash_verified"
                    for exam in spine["exams"]
                )
                else "review_required"
            ),
        }
        start = _parse_date(entry.get("started") or entry.get("projectedStart"))
        finish = _parse_date(entry.get("finished") or entry.get("projectedFinish"))
        has_real_plan = real_plan and any(
            code and code in entry.get("code", "") for code in real_plan_exam_codes
        )
        if has_real_plan:
            entry["weeks"] = _real_weeks(real_plan, start, finish)
        else:
            domains = certification_spines.projected_domains(entry["id"])
            entry["weeks"] = timeline.synthesize_weeks(domains, start, finish) if domains else []

    target_date = _parse_date(((stored or {}).get("state") or {}).get("meta", {}).get("wguStartDate"))
    projected = _parse_date(entries[-1].get("projectedFinish")) if entries else None
    remaining_hours = sum(
        max(0.0, (entry["estHoursLow"] + entry["estHoursHigh"]) / 2 - (entry.get("actualHours") or 0))
        for entry in entries if entry["status"] != "passed"
    )
    days_to_target = max(1, (target_date - study_clock.today()).days) if target_date else None
    required_pace = remaining_hours / (days_to_target / 7) if days_to_target else None
    buffer_days = 28
    buffer_target = target_date - timedelta(days=buffer_days) if target_date else None
    days_to_buffer = max(1, (buffer_target - study_clock.today()).days) if buffer_target else None
    required_buffer_pace = remaining_hours / (days_to_buffer / 7) if days_to_buffer else None
    return 200, {
        "entries": entries,
        "pace_hours_per_week": round(pace, 2),
        "target_date": target_date.isoformat() if target_date else None,
        "projected_all_complete": projected.isoformat() if projected else None,
        "schedule_delta_days": (projected - target_date).days if projected and target_date else None,
        "required_pace_hours_per_week": round(required_pace, 2) if required_pace else None,
        "completion_buffer_days": buffer_days,
        "buffer_target_date": buffer_target.isoformat() if buffer_target else None,
        "buffer_schedule_delta_days": (
            (projected - buffer_target).days if projected and buffer_target else None
        ),
        "required_buffer_pace_hours_per_week": (
            round(required_buffer_pace, 2) if required_buffer_pace else None
        ),
        "registry": {
            "version": spine_registry["registry_version"],
            "sha256": spine_registry["registry_sha256"],
        },
    }


def h_jobs(handler, conn, params, query, body):
    limit = (query.get("limit") or [20])[0]
    return 200, {"jobs": jobs.list_recent(conn, limit=limit)}


def h_job(handler, conn, params, query, body):
    job = jobs.get(conn, params["id"])
    if not job:
        raise ApiError(404, "job not found")
    return 200, job


def h_job_create(handler, conn, params, query, body):
    return 201, jobs.enqueue(
        conn,
        idempotency_key=body.get("idempotency_key"),
        kind=body.get("kind"),
        source_path=body.get("source_path"),
        output_path=body.get("output_path"),
        book_slug=body.get("book_slug"),
        book_kind=body.get("book_kind"),
    )


def h_learning_requests(handler, conn, params, query, body):
    return 200, learning_requests.list_requests(conn)


def h_learning_requests_create(handler, conn, params, query, body):
    return 201, learning_requests.create_many(conn, body)


Handler.routes = [
    Route("GET", r"^/api/health$", h_health),
    Route("GET", r"^/api/csrf-token$", h_csrf_token),
    Route("GET", r"^/api/dashboard$", h_dashboard),
    Route("GET", r"^/api/study-next$", h_study_next),
    Route("GET", r"^/api/progress$", h_progress),
    Route("GET", r"^/api/analytics$", h_analytics),
    Route("GET", r"^/api/hours-since$", h_hours_since),
    Route("GET", r"^/api/mastery-map$", h_mastery_map),
    Route("GET", r"^/api/readiness$", h_readiness),
    Route(
        "GET",
        r"^/api/certification-packs/(?P<certification_code>[^/]+)$",
        h_certification_pack,
    ),
    Route(
        "GET",
        r"^/api/certification-packs/(?P<certification_code>[^/]+)/dossiers$",
        h_objective_dossiers,
    ),
    Route(
        "GET",
        r"^/api/certification-packs/(?P<certification_code>[^/]+)/builds$",
        h_certification_pack_builds,
    ),
    Route(
        "GET",
        r"^/api/objective-dossiers/(?P<id>\d+)$",
        h_objective_dossier,
    ),
    Route("GET", r"^/api/adaptive-curriculum$", h_adaptive_curriculum),
    Route("GET", r"^/api/ai/context$", h_ai_context),
    Route("POST", r"^/api/coach/ask$", h_coach_ask, mutation=True),
    Route("GET", r"^/api/books$", h_books),
    Route("GET", r"^/api/certification-spines$", h_certification_spines),
    Route(
        "GET",
        r"^/api/certification-spines/(?P<certification_id>[^/]+)$",
        h_certification_spine,
    ),
    Route("GET", r"^/api/career-context$", h_career_context),
    Route("GET", r"^/api/search$", h_search),
    Route(
        "GET",
        r"^/api/sections/(?P<stable_id>[^/]+)/reader$",
        h_reader_section,
    ),
    Route(
        "GET",
        r"^/api/sections/(?P<stable_id>[^/]+)/epub-assets/(?P<member>.+)$",
        h_reader_asset,
    ),
    Route("GET", r"^/api/sections/(?P<stable_id>[^/]+)$", h_section),
    Route("GET", r"^/api/objectives$", h_objectives),
    Route("GET", r"^/api/objectives/(?P<id>\d+)$", h_objective),
    Route("POST", r"^/api/learning/events$", h_learning_event, mutation=True),
    Route("GET", r"^/api/annotations$", h_annotations_get),
    Route("POST", r"^/api/annotations$", h_annotations_create, mutation=True),
    Route(
        "POST",
        r"^/api/annotations/(?P<id>\d+)$",
        h_annotations_update,
        mutation=True,
    ),
    Route("GET", r"^/api/labs$", h_labs_get),
    Route("GET", r"^/api/lab-catalog$", h_lab_catalog_get),
    Route(
        "POST",
        r"^/api/lab-catalog/(?P<slug>[^/]+)/launch$",
        h_lab_catalog_launch,
        mutation=True,
    ),
    Route("POST", r"^/api/labs$", h_labs_create, mutation=True),
    Route(
        "POST",
        r"^/api/labs/(?P<id>\d+)$",
        h_labs_update,
        mutation=True,
    ),
    Route("GET", r"^/api/practice-exams$", h_practice_exams_get),
    Route("POST", r"^/api/practice-exams/start$", h_practice_exams_start, mutation=True),
    Route("GET", r"^/api/practice-exams/(?P<id>\d+)$", h_practice_exam_get),
    Route(
        "POST",
        r"^/api/practice-exams/(?P<id>\d+)/answer$",
        h_practice_exam_answer,
        mutation=True,
    ),
    Route(
        "POST",
        r"^/api/practice-exams/(?P<id>\d+)/submit$",
        h_practice_exam_submit,
        mutation=True,
    ),
    Route(
        "POST",
        r"^/api/practice-exams/(?P<id>\d+)/abandon$",
        h_practice_exam_abandon,
        mutation=True,
    ),
    Route("GET", r"^/api/retention$", h_retention_queue),
    Route("POST", r"^/api/retention/reviews$", h_retention_review, mutation=True),
    Route("GET", r"^/api/plan$", h_plan),
    Route("POST", r"^/api/plan/tasks/(?P<id>\d+)$", h_plan_task_update, mutation=True),
    Route("GET", r"^/api/sessions$", h_sessions_get),
    Route("POST", r"^/api/sessions$", h_sessions_post, mutation=True),
    Route("GET", r"^/api/study-goal$", h_study_goal_get),
    Route("POST", r"^/api/study-goal$", h_study_goal_set, mutation=True),
    Route("GET", r"^/api/daily-session$", h_daily_session_get),
    Route("GET", r"^/api/daily-session/history$", h_daily_session_history),
    Route("POST", r"^/api/daily-session/start$", h_daily_session_start, mutation=True),
    Route("POST", r"^/api/daily-session/events$", h_daily_session_event, mutation=True),
    Route("POST", r"^/api/daily-session/(?P<id>\d+)/pause$", h_daily_session_pause, mutation=True),
    Route("POST", r"^/api/daily-session/(?P<id>\d+)/resume$", h_daily_session_resume, mutation=True),
    Route("POST", r"^/api/daily-session/(?P<id>\d+)/heartbeat$", h_daily_session_heartbeat, mutation=True),
    Route("POST", r"^/api/daily-session/(?P<id>\d+)/finish$", h_daily_session_finish, mutation=True),
    Route("POST", r"^/api/daily-session/(?P<id>\d+)/abandon$", h_daily_session_abandon, mutation=True),
    Route("POST", r"^/api/daily-session/(?P<id>\d+)/delete$", h_daily_session_delete, mutation=True),
    Route("GET", r"^/api/attempts$", h_attempts_get),
    Route("POST", r"^/api/attempts$", h_attempts_post, mutation=True),
    Route("GET", r"^/api/waypoint/summary$", h_waypoint_summary),
    Route("GET", r"^/api/export$", h_export),
    Route("GET", r"^/api/waypoint/state$", h_waypoint_state_get),
    Route("POST", r"^/api/waypoint/state$", h_waypoint_state_post, mutation=True),
    Route("GET", r"^/api/timeline$", h_timeline_get),
    Route("GET", r"^/api/jobs$", h_jobs),
    Route("POST", r"^/api/jobs$", h_job_create, mutation=True),
    Route("GET", r"^/api/learning-requests$", h_learning_requests),
    Route("POST", r"^/api/learning-requests$", h_learning_requests_create, mutation=True),
    Route("GET", r"^/api/jobs/(?P<id>[0-9a-f-]+)$", h_job),
    Route("GET", r"^/api/diagnostics/scopes$", h_diag_scopes),
    Route("GET", r"^/api/diagnostics/scopes/(?P<id>\d+)$", h_diag_scope),
    Route("POST", r"^/api/diagnostics/scopes/(?P<id>\d+)/start$", h_diag_scope_start, mutation=True),
    Route("GET", r"^/api/diagnostics/attempts/(?P<id>\d+)$", h_diag_attempt),
    Route("POST", r"^/api/diagnostics/attempts/(?P<id>\d+)/submit$", h_diag_attempt_submit, mutation=True),
    Route("GET", r"^/api/diagnostics/attempts/(?P<id>\d+)/results$", h_diag_attempt_results),
    Route("POST", r"^/api/diagnostics/attempts/(?P<id>\d+)/abandon$", h_diag_attempt_abandon, mutation=True),
    Route("POST", r"^/api/remediation/(?P<id>\d+)$", h_remediation_reviewed, mutation=True),
]


def main():
    host = os.environ.get("STUDY_LIBRARY_HOST", "127.0.0.1")
    port = int(os.environ.get("STUDY_LIBRARY_PORT", "8840"))
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Study Library serving on http://{host}:{port} (CSRF token: {CSRF_TOKEN[:8]}...)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
