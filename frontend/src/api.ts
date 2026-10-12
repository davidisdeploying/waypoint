import {z} from "zod";
import type {
  AdaptivePlan,
  Analytics,
  AnnotationCreate,
  Book,
  CertificationPack,
  CertificationPackBuildState,
  CoachResponse,
  CareerContext,
  DailySessionOverview,
  DailyStudySession,
  DiagnosticAttempt,
  DiagnosticMode,
  DiagnosticScope,
  DiagnosticSubmissionEntry,
  HandsOnLab,
  LabCatalog,
  LabCreate,
  LabUpdate,
  LabsResponse,
  LearningEventType,
  LearningState,
  LibraryJob,
  MasteryMap,
  ExamReadiness,
  ObjectiveDetail,
  ObjectiveDossierSummary,
  PracticeExamAttempt,
  PracticeExamOverview,
  Progress,
  ReaderSection,
  RetentionQueue,
  RetentionRating,
  RetentionState,
  SearchResult,
  SectionDetail,
  StudyAnnotation,
  StudyDashboard,
  StudyGoal,
  StudyNext,
  StudyPlan,
  StudySessionEventType,
  TimelineResponse,
  WaypointState,
  WaypointStateEnvelope,
  LearningProposalEnvelope,
  LearningRequest,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const objectEnvelope = z.object({}).passthrough();
let studyCsrfToken: string | null = null;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers || {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload && typeof payload.error === "string"
      ? payload.error
      : `Request failed with HTTP ${response.status}`;
    throw new ApiError(response.status, message);
  }
  objectEnvelope.parse(payload);
  return payload as T;
}

export async function getWaypointState(): Promise<WaypointStateEnvelope | null> {
  try {
    return await request<WaypointStateEnvelope>("/api/v2/waypoint/state");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function saveWaypointState(state: WaypointState, revision: number) {
  return request<WaypointStateEnvelope>("/api/v2/waypoint/state", {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Waypoint-CSRF": "1"},
    body: JSON.stringify({state, expected_revision: revision}),
  });
}

export function studyGet<T>(path: string): Promise<T> {
  return request<T>(`/api/v2/study/${path.replace(/^\//, "")}`);
}

async function getStudyCsrfToken() {
  if (studyCsrfToken) return studyCsrfToken;
  const payload = await studyGet<{csrf_token: string}>("csrf-token");
  studyCsrfToken = payload.csrf_token;
  return studyCsrfToken;
}

export async function studyPost<T>(path: string, body: unknown, keepalive = false): Promise<T> {
  const token = await getStudyCsrfToken();
  try {
    return await request<T>(`/api/v2/study/${path.replace(/^\//, "")}`, {
      method: "POST",
      keepalive,
      headers: {"Content-Type": "application/json", "X-CSRF-Token": token},
      body: JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) studyCsrfToken = null;
    throw error;
  }
}

export const queries = {
  dashboard: () => studyGet<StudyDashboard>("dashboard"),
  studyNext: () => studyGet<StudyNext>("study-next?limit=6"),
  progress: () => studyGet<Progress>("progress"),
  analytics: () => studyGet<Analytics>("analytics?days=30"),
  timeline: () => studyGet<TimelineResponse>("timeline"),
  masteryMap: (exam = "") =>
    studyGet<MasteryMap>(`mastery-map${exam ? `?exam=${encodeURIComponent(exam)}` : ""}`),
  readiness: (exam = "") =>
    studyGet<ExamReadiness>(`readiness${exam ? `?exam=${encodeURIComponent(exam)}` : ""}`),
  careerContext: (certification = "") =>
    studyGet<CareerContext>(
      `career-context${certification ? `?certification=${encodeURIComponent(certification)}` : ""}`,
    ),
  objective: (objectiveId: number) =>
    studyGet<ObjectiveDetail>(`objectives/${objectiveId}`),
  annotations: (objectiveId: number) =>
    studyGet<{annotations: StudyAnnotation[]}>(`annotations?objective_id=${objectiveId}`),
  createAnnotation: (payload: AnnotationCreate) =>
    studyPost<StudyAnnotation>("annotations", payload),
  updateAnnotation: (
    annotationId: number,
    payload: {note_text?: string; archived?: boolean},
  ) => studyPost<StudyAnnotation>(`annotations/${annotationId}`, payload),
  labs: (objectiveId?: number) =>
    studyGet<LabsResponse>(
      `labs${objectiveId ? `?objective_id=${objectiveId}` : ""}`,
    ),
  labCatalog: () => studyGet<LabCatalog>("lab-catalog"),
  launchLabTemplate: (slug: string, clientKey: string) =>
    studyPost<HandsOnLab>(`lab-catalog/${encodeURIComponent(slug)}/launch`, {
      client_key: clientKey,
    }),
  createLab: (payload: LabCreate) =>
    studyPost<HandsOnLab>("labs", payload),
  updateLab: (labId: number, payload: LabUpdate) =>
    studyPost<HandsOnLab>(`labs/${labId}`, payload),
  practiceExams: () =>
    studyGet<PracticeExamOverview>("practice-exams"),
  practiceExam: (attemptId: number) =>
    studyGet<PracticeExamAttempt>(`practice-exams/${attemptId}`),
  startPracticeExam: (examCode: string) =>
    studyPost<PracticeExamAttempt>("practice-exams/start", {exam_code: examCode}),
  savePracticeExamAnswer: (
    attemptId: number,
    questionId: number,
    selected: number[],
  ) => studyPost<{
    id: number;
    question_id: number;
    selected: number[];
    answered_count: number;
  }>(`practice-exams/${attemptId}/answer`, {
    question_id: questionId,
    selected,
  }),
  submitPracticeExam: (attemptId: number) =>
    studyPost<PracticeExamAttempt>(`practice-exams/${attemptId}/submit`, {}),
  abandonPracticeExam: (attemptId: number) =>
    studyPost<{id: number; state: "abandoned"}>(
      `practice-exams/${attemptId}/abandon`,
      {},
    ),
  adaptive: (minutesPerDay = 45) =>
    studyGet<AdaptivePlan>(`adaptive-curriculum?days=7&minutes_per_day=${minutesPerDay}`),
  retention: (horizonDays = 7) =>
    studyGet<RetentionQueue>(`retention?horizon_days=${horizonDays}`),
  books: () => studyGet<{books: Book[]}>("books"),
  certificationPack: () =>
    studyGet<CertificationPack>("certification-packs/aplus"),
  certificationPackBuilds: () =>
    studyGet<CertificationPackBuildState>("certification-packs/aplus/builds"),
  objectiveDossiers: () =>
    studyGet<ObjectiveDossierSummary>("certification-packs/aplus/dossiers"),
  jobs: () => studyGet<{jobs: LibraryJob[]}>("jobs?limit=10"),
  search: (query: string, book = "", exam = "") => {
    const params = new URLSearchParams({q: query, limit: "20"});
    if (book) params.set("book", book);
    if (exam) params.set("exam", exam);
    return studyGet<{query: string; results: SearchResult[]}>(`search?${params}`);
  },
  section: (stableId: string) => studyGet<SectionDetail>(`sections/${encodeURIComponent(stableId)}`),
  readerSection: (stableId: string) =>
    studyGet<ReaderSection>(`sections/${encodeURIComponent(stableId)}/reader`),
  plan: () => studyGet<StudyPlan>("plan"),
  health: () => studyGet<{status: string; time: string; schema_version: string}>("health"),
  learningRequests: () => studyGet<{learning_requests: LearningRequest[]; evidence_boundary: string}>("learning-requests"),
  importLearningRequests: (payload: LearningProposalEnvelope) =>
    studyPost<{learning_requests: LearningRequest[]; evidence_boundary: string}>("learning-requests", payload),
  coach: (mode: string, question = "") =>
    studyPost<CoachResponse>("coach/ask", {mode, question, provider: "claude"}),
  diagnosticScope: (scopeId: number) =>
    studyGet<DiagnosticScope>(`diagnostics/scopes/${scopeId}`),
  diagnosticAttempt: (attemptId: number) =>
    studyGet<DiagnosticAttempt>(`diagnostics/attempts/${attemptId}`),
  diagnosticResults: (attemptId: number) =>
    studyGet<DiagnosticAttempt>(`diagnostics/attempts/${attemptId}/results`),
  startDiagnostic: (scopeId: number, mode: DiagnosticMode) =>
    studyPost<DiagnosticAttempt>(`diagnostics/scopes/${scopeId}/start`, {mode}),
  submitDiagnostic: (attemptId: number, responses: DiagnosticSubmissionEntry[]) =>
    studyPost<DiagnosticAttempt>(`diagnostics/attempts/${attemptId}/submit`, {responses}),
  abandonDiagnostic: (attemptId: number) =>
    studyPost<DiagnosticAttempt>(`diagnostics/attempts/${attemptId}/abandon`, {}),
  markRemediationReviewed: (itemId: number) =>
    studyPost<{id: number; status: "reviewed"}>(`remediation/${itemId}`, {}),
  dailySession: () => studyGet<DailySessionOverview>("daily-session"),
  dailySessionHistory: () =>
    studyGet<{sessions: DailyStudySession[]}>("daily-session/history?limit=50"),
  studyGoal: () => studyGet<StudyGoal>("study-goal"),
  setStudyGoal: (dailyTargetMinutes: number) =>
    studyPost<StudyGoal>("study-goal", {daily_target_minutes: dailyTargetMinutes}),
  heartbeatDailySession: (sessionId: number) =>
    studyPost<DailyStudySession>(`daily-session/${sessionId}/heartbeat`, {}, true),
  startDailySession: (targetMinutes: number) =>
    studyPost<DailyStudySession>("daily-session/start", {target_minutes: targetMinutes}),
  pauseDailySession: (sessionId: number, occurredAt: string) =>
    studyPost<DailyStudySession>(
      `daily-session/${sessionId}/pause`,
      {occurred_at: occurredAt},
      true,
    ),
  resumeDailySession: (sessionId: number) =>
    studyPost<DailyStudySession>(`daily-session/${sessionId}/resume`, {}),
  finishDailySession: (sessionId: number, notes: string) =>
    studyPost<DailyStudySession>(`daily-session/${sessionId}/finish`, {notes}),
  abandonDailySession: (sessionId: number) =>
    studyPost<DailyStudySession>(`daily-session/${sessionId}/abandon`, {}),
  deleteDailySession: (sessionId: number) =>
    studyPost<{id: number; deleted: true; deleted_at: string}>(
      `daily-session/${sessionId}/delete`,
      {},
    ),
  logSessionEvent: (
    eventType: StudySessionEventType,
    label: string,
    eventKey?: string,
    metadata?: Record<string, unknown>,
  ) => studyPost<DailyStudySession>("daily-session/events", {
    event_type: eventType,
    label,
    event_key: eventKey,
    metadata,
  }),
  logLearningEvent: (
    objectiveId: number,
    eventType: LearningEventType,
    eventKey?: string,
    metadata?: Record<string, unknown>,
  ) => studyPost<LearningState>("learning/events", {
    objective_id: objectiveId,
    event_type: eventType,
    event_key: eventKey,
    metadata,
  }),
  recordRetentionReview: (
    objectiveId: number,
    rating: RetentionRating,
    eventKey?: string,
  ) => studyPost<RetentionState>("retention/reviews", {
    objective_id: objectiveId,
    rating,
    event_key: eventKey,
  }),
};

export function trackStudyEvent(
  eventType: StudySessionEventType,
  label: string,
  eventKey?: string,
  metadata?: Record<string, unknown>,
) {
  void queries.logSessionEvent(eventType, label, eventKey, metadata).catch(() => undefined);
}
