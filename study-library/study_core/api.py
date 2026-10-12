"""Typed FastAPI transport for the existing Study Core domain modules.

This application is introduced as a canary beside the current stdlib server.
Both transports use the same tested domain functions and SQLite database.
"""

import os
import secrets
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lib import (
    annotations,
    analytics,
    labs,
    lab_catalog,
    practice_exams,
    api_logic,
    coach,
    daily_sessions,
    db,
    diagnostics,
    jobs,
    learning,
    mastery,
    retention,
    waypoint_state,
)
from lib.api_logic import ApiError


def _read_service_token() -> str:
    path = os.environ.get("STUDY_LIBRARY_SERVICE_TOKEN_FILE", "")
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"cannot read Study Core service token: {path}") from exc


SERVICE_TOKEN = _read_service_token()
CSRF_TOKEN = secrets.token_urlsafe(32)


def connection():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


Connection = Annotated[Any, Depends(connection)]


def require_service_token(
    x_waypoint_service_token: Annotated[str | None, Header()] = None,
) -> None:
    if not SERVICE_TOKEN:
        return
    if x_waypoint_service_token is None or not secrets.compare_digest(
        x_waypoint_service_token, SERVICE_TOKEN
    ):
        raise HTTPException(status_code=401, detail="missing or invalid service credential")


def require_mutation_guard(
    request: Request,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> None:
    require_service_token(request.headers.get("X-Waypoint-Service-Token"))
    trusted_waypoint_mutation = (
        request.url.path == "/api/waypoint/state"
        and request.headers.get("X-Waypoint-Trusted-Mutation") == "1"
    )
    if not trusted_waypoint_mutation and (
        x_csrf_token is None or not secrets.compare_digest(x_csrf_token, CSRF_TOKEN)
    ):
        raise HTTPException(status_code=403, detail="missing or invalid CSRF token")
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.headers.get("Host", ""):
        raise HTTPException(status_code=403, detail="cross-origin request rejected")


class CoachRequest(BaseModel):
    mode: str
    question: str = Field(default="", max_length=1000)
    provider: str = "claude"


class PlanTaskUpdate(BaseModel):
    completed: bool | None = None
    notes: str | None = None


class SessionCreate(BaseModel):
    occurred_at: str | None = None
    duration_minutes: int | None = None
    exam_id: int | None = None
    week_id: int | None = None
    notes: str | None = None


class DailySessionStart(BaseModel):
    target_minutes: int


class DailySessionEvent(BaseModel):
    event_type: str
    label: str
    event_key: str | None = None
    metadata: dict[str, Any] | None = None


class DailySessionFinish(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class DailySessionPause(BaseModel):
    occurred_at: str | None = Field(default=None, max_length=64)


class LearningEventCreate(BaseModel):
    objective_id: int
    event_type: str
    event_key: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] | None = None


class RetentionReviewCreate(BaseModel):
    objective_id: int
    rating: str
    event_key: str | None = Field(default=None, max_length=240)


class AnnotationCreate(BaseModel):
    objective_id: int
    kind: str
    section_stable_id: str | None = None
    quote_text: str | None = Field(default=None, max_length=2000)
    prefix_text: str | None = Field(default=None, max_length=240)
    suffix_text: str | None = Field(default=None, max_length=240)
    note_text: str | None = Field(default=None, max_length=5000)
    content_sha256: str | None = None
    anchor_start: int | None = None
    anchor_end: int | None = None
    client_key: str | None = Field(default=None, max_length=240)


class AnnotationUpdate(BaseModel):
    note_text: str | None = Field(default=None, max_length=5000)
    archived: bool | None = None


class LabCreate(BaseModel):
    objective_id: int
    title: str = Field(max_length=200)
    goal_text: str = Field(max_length=10000)
    environment_text: str | None = Field(default=None, max_length=10000)
    client_key: str | None = Field(default=None, max_length=240)


class LabUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    goal_text: str | None = Field(default=None, max_length=10000)
    environment_text: str | None = Field(default=None, max_length=10000)
    evidence_text: str | None = Field(default=None, max_length=10000)
    reflection_text: str | None = Field(default=None, max_length=10000)
    status: str | None = None
    completion_level: str | None = None
    archived: bool | None = None


class PracticeExamStart(BaseModel):
    exam_code: str


class PracticeExamAnswer(BaseModel):
    question_id: int
    selected: list[int]


class PracticeAttemptCreate(BaseModel):
    exam_id: int | None = None
    score: int | None = None
    total: int | None = None
    occurred_at: str | None = None
    objective_id: int | None = None
    notes: str | None = None
    held_out: bool = False


class DiagnosticStart(BaseModel):
    mode: str = "diagnostic"


class DiagnosticSubmission(BaseModel):
    responses: list[dict[str, Any]]


class WaypointStateUpdate(BaseModel):
    expected_revision: int
    state: dict[str, Any]
    migration_id: str | None = None


class BookJobCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    kind: str
    source_path: str = Field(min_length=1, max_length=2000)
    output_path: str = Field(min_length=1, max_length=2000)
    book_slug: str = Field(min_length=1, max_length=100)
    book_kind: str


app = FastAPI(
    title="Waypoint Study Core",
    version="2.1.0-canary",
    docs_url=None,
    redoc_url=None,
)
api = APIRouter(prefix="/api", dependencies=[Depends(require_service_token)])


@app.exception_handler(ApiError)
def handle_api_error(_request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content={"error": exc.message})


@app.exception_handler(HTTPException)
def handle_http_error(_request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.get("/api/health")
def health(conn: Connection):
    return {
        "status": "ok",
        "time": api_logic.now_iso(),
        "schema_version": db.get_schema_version(conn),
        "service_auth": "required" if SERVICE_TOKEN else "disabled",
        "transport": "fastapi-canary",
    }


@api.get("/csrf-token")
def csrf_token():
    return {"csrf_token": CSRF_TOKEN}


@api.get("/dashboard")
def dashboard(conn: Connection):
    return api_logic.get_dashboard(conn)


@api.get("/study-next")
def study_next(conn: Connection, limit: int | None = None):
    return api_logic.get_study_next(conn, limit=limit)


@api.get("/progress")
def progress(conn: Connection):
    return api_logic.get_progress_summary(conn)


@api.get("/analytics")
def analytics_summary(conn: Connection, days: int = 30):
    return analytics.get_analytics(conn, days=days)


@api.get("/mastery-map")
def mastery_map(conn: Connection, exam: str | None = None):
    return mastery.get_mastery_map(conn, exam=exam)


@api.get("/adaptive-curriculum")
def adaptive_curriculum(
    conn: Connection,
    days: int | None = None,
    minutes_per_day: int | None = None,
):
    return api_logic.get_adaptive_curriculum(
        conn, days=days, minutes_per_day=minutes_per_day
    )


@api.get("/ai/context")
def ai_context(
    conn: Connection,
    q: str | None = None,
    exam: str | None = None,
    limit: int | None = None,
    max_chars: int | None = None,
    days: int | None = None,
    minutes_per_day: int | None = None,
):
    return api_logic.get_ai_context(
        conn,
        query=q,
        exam=exam,
        limit=limit,
        max_chars=max_chars,
        days=days,
        minutes_per_day=minutes_per_day,
    )


@api.post("/coach/ask", dependencies=[Depends(require_mutation_guard)])
def coach_ask(payload: CoachRequest, conn: Connection):
    return coach.ask(conn, payload.model_dump())


@api.get("/books")
def books(conn: Connection):
    return {"books": api_logic.list_books(conn)}


@api.get("/certification-packs/{certification_code}")
def certification_pack(certification_code: str, conn: Connection):
    result = api_logic.get_certification_pack(conn, certification_code)
    if not result:
        raise ApiError(404, "certification pack not found")
    return result


@api.get("/search")
def search(
    conn: Connection,
    q: str,
    book: str | None = None,
    exam: str | None = None,
    limit: int | None = None,
):
    return {
        "query": q,
        "results": api_logic.search_sections(
            conn, q, book=book, exam=exam, limit=limit
        ),
    }


@api.get("/sections/{stable_id}")
def section(stable_id: str, conn: Connection):
    result = api_logic.get_section(conn, stable_id)
    if not result:
        raise ApiError(404, "section not found")
    return result


@api.get("/objectives")
def objectives(conn: Connection, exam: str | None = None):
    return {"objectives": api_logic.list_objectives(conn, exam=exam)}


@api.get("/objectives/{objective_id}")
def objective(objective_id: int, conn: Connection):
    result = api_logic.get_objective(conn, objective_id)
    if not result:
        raise ApiError(404, "objective not found")
    result["mastery"] = mastery.get_objective_mastery(conn, objective_id)
    result["learning"] = learning.get_objective_state(conn, objective_id)
    result["retention"] = retention.get_objective_state(conn, objective_id)
    return result


@api.post("/learning/events", dependencies=[Depends(require_mutation_guard)])
def learning_event(payload: LearningEventCreate, conn: Connection):
    return learning.record_event(
        conn,
        payload.objective_id,
        payload.event_type,
        event_key=payload.event_key,
        metadata=payload.metadata,
    )


@api.get("/annotations")
def annotation_list(conn: Connection, objective_id: int | None = None):
    return {
        "annotations": annotations.list_annotations(conn, objective_id)
    }


@api.post(
    "/annotations",
    status_code=201,
    dependencies=[Depends(require_mutation_guard)],
)
def annotation_create(payload: AnnotationCreate, conn: Connection):
    return annotations.create_annotation(conn, **payload.model_dump())


@api.post(
    "/annotations/{annotation_id}",
    dependencies=[Depends(require_mutation_guard)],
)
def annotation_update(
    annotation_id: int, payload: AnnotationUpdate, conn: Connection
):
    result = annotations.update_annotation(
        conn, annotation_id, **payload.model_dump()
    )
    if result is None:
        raise ApiError(404, "annotation not found")
    return result


@api.get("/labs")
def lab_list(conn: Connection, objective_id: int | None = None):
    return labs.list_labs(conn, objective_id)


@api.get("/lab-catalog")
def lab_template_list(
    conn: Connection,
    exam: str | None = None,
    objective_id: int | None = None,
):
    return lab_catalog.list_templates(conn, exam=exam, objective_id=objective_id)


@api.post(
    "/lab-catalog/{slug}/launch",
    status_code=201,
    dependencies=[Depends(require_mutation_guard)],
)
def lab_template_launch(slug: str, payload: dict[str, Any], conn: Connection):
    return lab_catalog.launch_template(
        conn, slug, client_key=payload.get("client_key")
    )


@api.post(
    "/labs",
    status_code=201,
    dependencies=[Depends(require_mutation_guard)],
)
def lab_create(payload: LabCreate, conn: Connection):
    return labs.create_lab(conn, **payload.model_dump())


@api.post(
    "/labs/{lab_id}",
    dependencies=[Depends(require_mutation_guard)],
)
def lab_update(lab_id: int, payload: LabUpdate, conn: Connection):
    result = labs.update_lab(conn, lab_id, **payload.model_dump())
    if result is None:
        raise ApiError(404, "lab not found")
    return result


@api.get("/practice-exams")
def practice_exam_overview(conn: Connection):
    return practice_exams.overview(conn)


@api.post(
    "/practice-exams/start",
    status_code=201,
    dependencies=[Depends(require_mutation_guard)],
)
def practice_exam_start(payload: PracticeExamStart, conn: Connection):
    return practice_exams.start_attempt(conn, payload.exam_code)


@api.get("/practice-exams/{attempt_id}")
def practice_exam_attempt(attempt_id: int, conn: Connection):
    return practice_exams.get_attempt(conn, attempt_id)


@api.post(
    "/practice-exams/{attempt_id}/answer",
    dependencies=[Depends(require_mutation_guard)],
)
def practice_exam_answer(
    attempt_id: int, payload: PracticeExamAnswer, conn: Connection
):
    return practice_exams.save_answer(
        conn, attempt_id, payload.question_id, payload.selected
    )


@api.post(
    "/practice-exams/{attempt_id}/submit",
    dependencies=[Depends(require_mutation_guard)],
)
def practice_exam_submit(attempt_id: int, conn: Connection):
    return practice_exams.submit_attempt(conn, attempt_id)


@api.post(
    "/practice-exams/{attempt_id}/abandon",
    dependencies=[Depends(require_mutation_guard)],
)
def practice_exam_abandon(attempt_id: int, conn: Connection):
    return practice_exams.abandon_attempt(conn, attempt_id)


@api.get("/retention")
def retention_queue(
    conn: Connection,
    exam: str | None = None,
    horizon_days: int = 7,
    limit: int = 50,
):
    return retention.get_queue(
        conn, exam=exam, horizon_days=horizon_days, limit=limit
    )


@api.post("/retention/reviews", dependencies=[Depends(require_mutation_guard)])
def retention_review(payload: RetentionReviewCreate, conn: Connection):
    return retention.record_review(
        conn,
        payload.objective_id,
        payload.rating,
        event_key=payload.event_key,
    )


@api.get("/plan")
def plan(conn: Connection):
    result = api_logic.get_plan(conn)
    if not result:
        raise ApiError(404, "no study plan seeded")
    return result


@api.post(
    "/plan/tasks/{task_id}",
    dependencies=[Depends(require_mutation_guard)],
)
def update_plan_task(task_id: int, payload: PlanTaskUpdate, conn: Connection):
    result = api_logic.update_plan_task(
        conn, task_id, completed=payload.completed, notes=payload.notes
    )
    if not result:
        raise ApiError(404, "task not found")
    return result


@api.get("/sessions")
def sessions(conn: Connection, limit: int | None = None):
    return {"sessions": api_logic.list_sessions(conn, limit=limit)}


@api.post("/sessions", status_code=201, dependencies=[Depends(require_mutation_guard)])
def create_session(payload: SessionCreate, conn: Connection):
    return api_logic.create_session(conn, **payload.model_dump())


@api.get("/daily-session")
def daily_session(conn: Connection):
    primary = api_logic.get_study_next(conn, limit=1).get("primary")
    return daily_sessions.overview(conn, primary)


@api.get("/daily-session/history")
def daily_session_history(conn: Connection, limit: int | None = None):
    return {"sessions": daily_sessions.history(conn, limit=limit)}


@api.post(
    "/daily-session/start",
    status_code=201,
    dependencies=[Depends(require_mutation_guard)],
)
def start_daily_session(payload: DailySessionStart, conn: Connection):
    primary = api_logic.get_study_next(conn, limit=1).get("primary")
    return daily_sessions.start(conn, payload.target_minutes, primary)


@api.post("/daily-session/events", dependencies=[Depends(require_mutation_guard)])
def log_daily_session_event(payload: DailySessionEvent, conn: Connection):
    return daily_sessions.log_event(conn, **payload.model_dump())


@api.post(
    "/daily-session/{session_id}/pause",
    dependencies=[Depends(require_mutation_guard)],
)
def pause_daily_session(
    session_id: int, payload: DailySessionPause, conn: Connection
):
    return daily_sessions.pause(conn, session_id, occurred_at=payload.occurred_at)


@api.post(
    "/daily-session/{session_id}/resume",
    dependencies=[Depends(require_mutation_guard)],
)
def resume_daily_session(session_id: int, conn: Connection):
    return daily_sessions.resume(conn, session_id)


@api.post(
    "/daily-session/{session_id}/finish",
    dependencies=[Depends(require_mutation_guard)],
)
def finish_daily_session(
    session_id: int, payload: DailySessionFinish, conn: Connection
):
    return daily_sessions.finish(conn, session_id, notes=payload.notes)


@api.post(
    "/daily-session/{session_id}/abandon",
    dependencies=[Depends(require_mutation_guard)],
)
def abandon_daily_session(session_id: int, conn: Connection):
    return daily_sessions.abandon(conn, session_id)


@api.post(
    "/daily-session/{session_id}/delete",
    dependencies=[Depends(require_mutation_guard)],
)
def delete_daily_session(session_id: int, conn: Connection):
    return daily_sessions.delete_recorded(conn, session_id)


@api.get("/attempts")
def attempts(conn: Connection, limit: int | None = None):
    return {"attempts": api_logic.list_attempts(conn, limit=limit)}


@api.post("/attempts", status_code=201, dependencies=[Depends(require_mutation_guard)])
def create_attempt(payload: PracticeAttemptCreate, conn: Connection):
    return api_logic.create_attempt(conn, **payload.model_dump())


@api.get("/diagnostics/scopes")
def diagnostic_scopes(conn: Connection):
    return {"scopes": diagnostics.list_scopes(conn)}


@api.get("/diagnostics/scopes/{scope_id}")
def diagnostic_scope(scope_id: int, conn: Connection):
    return diagnostics.get_scope(conn, scope_id)


@api.post(
    "/diagnostics/scopes/{scope_id}/start",
    status_code=201,
    dependencies=[Depends(require_mutation_guard)],
)
def start_diagnostic(scope_id: int, payload: DiagnosticStart, conn: Connection):
    return diagnostics.start_attempt(conn, scope_id, payload.mode)


@api.get("/diagnostics/attempts/{attempt_id}")
def diagnostic_attempt(attempt_id: int, conn: Connection):
    return diagnostics.get_attempt(conn, attempt_id)


@api.post(
    "/diagnostics/attempts/{attempt_id}/submit",
    dependencies=[Depends(require_mutation_guard)],
)
def submit_diagnostic(
    attempt_id: int, payload: DiagnosticSubmission, conn: Connection
):
    return diagnostics.submit_attempt(conn, attempt_id, payload.responses)


@api.get("/diagnostics/attempts/{attempt_id}/results")
def diagnostic_results(attempt_id: int, conn: Connection):
    return diagnostics.get_attempt_results(conn, attempt_id)


@api.post(
    "/diagnostics/attempts/{attempt_id}/abandon",
    dependencies=[Depends(require_mutation_guard)],
)
def abandon_diagnostic(attempt_id: int, conn: Connection):
    return diagnostics.abandon_attempt(conn, attempt_id)


@api.post("/remediation/{item_id}", dependencies=[Depends(require_mutation_guard)])
def review_remediation(item_id: int, conn: Connection):
    return diagnostics.mark_reviewed(conn, item_id)


def _base_url() -> str:
    host = os.environ.get("STUDY_LIBRARY_HOST", "127.0.0.1")
    port = os.environ.get("STUDY_LIBRARY_FASTAPI_PORT", "8841")
    return f"http://{host}:{port}"


@api.get("/waypoint/summary")
def waypoint_summary(conn: Connection):
    return api_logic.get_waypoint_summary(conn, _base_url())


@api.get("/export")
def export(conn: Connection):
    return api_logic.export_snapshot(conn, _base_url())


@api.get("/waypoint/state")
def get_waypoint_state(conn: Connection):
    result = waypoint_state.get(conn)
    if result is None:
        raise ApiError(404, "Waypoint state is not initialized")
    return result


@api.post("/waypoint/state", dependencies=[Depends(require_mutation_guard)])
def save_waypoint_state(payload: WaypointStateUpdate, conn: Connection):
    return waypoint_state.save(
        conn,
        payload.state,
        payload.expected_revision,
        migration_id=payload.migration_id,
    )


@api.get("/jobs")
def list_jobs(conn: Connection, limit: int = 20):
    return {"jobs": jobs.list_recent(conn, limit=limit)}


@api.get("/jobs/{job_id}")
def get_job(job_id: str, conn: Connection):
    result = jobs.get(conn, job_id)
    if not result:
        raise ApiError(404, "job not found")
    return result


@api.post("/jobs", status_code=201, dependencies=[Depends(require_mutation_guard)])
def create_job(payload: BookJobCreate, conn: Connection):
    return jobs.enqueue(conn, **payload.model_dump())


app.include_router(api)
