export type CredentialStatus = "todo" | "studying" | "scheduled" | "passed";

export interface TimelineWeek {
  week_number: number;
  topic: string;
  date: string;
  progress_percent: number;
  source: "real" | "projected";
}

export interface TimelineEntry {
  id: string;
  order: number;
  kind: string;
  code: string;
  name: string;
  status: CredentialStatus;
  estHoursLow: number;
  estHoursHigh: number;
  started: string | null;
  finished: string | null;
  actualHours: number | null;
  projectedStart: string | null;
  projectedFinish: string | null;
  weeks: TimelineWeek[];
  spine: {
    registry_version: string;
    scope_status: "published_pack" | "domain_scaffold" | "missing";
    exam_sittings: number | null;
    official_source_status: "hash_verified" | "review_required";
  };
}

export interface TimelineResponse {
  entries: TimelineEntry[];
  pace_hours_per_week: number;
  target_date: string | null;
  projected_all_complete: string | null;
  schedule_delta_days: number | null;
  required_pace_hours_per_week: number | null;
  completion_buffer_days: number;
  buffer_target_date: string | null;
  buffer_schedule_delta_days: number | null;
  required_buffer_pace_hours_per_week: number | null;
  registry: {version: string; sha256: string};
}

export interface Credential {
  id: string;
  order: number;
  name: string;
  kind: string;
  code: string;
  clears?: string;
  exam: string;
  pass: string;
  status: CredentialStatus;
  price: number;
  cu: number;
  wlo: number;
  whi: number;
  started: string;
  actualHours: number | null;
  estHoursLow: number;
  estHoursHigh: number;
}

export interface Course {
  code: string;
  name: string;
  note: string;
  cu: number;
  status: "todo" | "in_progress" | "done";
}

export interface StudyLogEntry {
  id: string;
  date: string;
  certId: string;
  hours: number;
  note: string;
}

export interface WaypointState {
  meta: {name: string; startDate: string; wguStartDate: string};
  certs: Credential[];
  courses: Course[];
  log: StudyLogEntry[];
  studyEndpoint: string;
  studySummary: Record<string, unknown> | null;
  studySummaryReceivedAt: string | null;
}

export interface WaypointStateEnvelope {
  schema_version: number;
  revision: number;
  state: WaypointState;
  updated_at: string;
  migration_id: string | null;
}

export interface LearningProposal {
  skill: string;
  priority: "high" | "medium" | "low";
  technology: string;
  evidence_building_method: string;
  certification_id: string | null;
  certification_label: string | null;
  waypoint_scope_status: "published_pack" | "domain_scaffold" | "missing" | "unmapped";
  source_requirement_ids: string[];
}

export interface LearningProposalEnvelope {
  schema_version: 1;
  source: "prospect_job_listing_audit";
  source_audit_id: number;
  source_listing_id: number;
  role: string | null;
  company: string | null;
  career_claims_hash: string;
  proposals: LearningProposal[];
}

export interface LearningRequest extends LearningProposal {
  id: number;
  source: string;
  source_audit_id: number;
  source_listing_id: number | null;
  role: string | null;
  company: string | null;
  rationale: string;
  status: "proposed";
  created_at: string;
}

export interface StudyAction {
  type: string;
  scope_id?: number;
  objective_id?: number;
  mode?: string;
  task_id?: number;
  view?: string;
}

export interface StudyItem {
  id: string;
  kind: string;
  eyebrow: string;
  title: string;
  description: string;
  reason: string;
  due_at: string | null;
  action: StudyAction;
  estimated_minutes?: number;
  conditional_on?: string | null;
}

export interface StudyDashboard {
  generated_at: string;
  current_exam: string;
  current_week: number;
  week_title: string;
  next_task: StudyItem | null;
  total_hours: number;
  hours_last_7_days: number;
  completed_tasks: number;
  total_tasks: number;
  objective_coverage: number;
  practice_average_recent: number | null;
  readiness_label: string;
  diagnostics: {
    diagnostic_checks_passed: number;
    diagnostic_checks_available: number;
    current_gap_count: number;
    retention_due_count: number;
    domain_mastery_pct: number;
  };
}

export interface StudyNext {
  current_exam: string;
  current_week: number;
  week_title: string;
  primary: StudyItem | null;
  items: StudyItem[];
  counts: {
    retention_due: number;
    objective_retention_due: number;
    open_gaps: number;
    unfinished_lessons: number;
    incomplete_current_week_tasks: number;
  };
}

export type StudySessionEventType =
  | "reading_opened"
  | "gap_reviewed"
  | "knowledge_check_completed"
  | "task_completed"
  | "coach_used";

export interface StudySessionEvent {
  id: number;
  session_id: number;
  event_type: StudySessionEventType;
  label: string;
  event_key: string | null;
  metadata: Record<string, unknown>;
  occurred_at: string;
}

export interface DailyStudySession {
  id: number;
  status: "active" | "completed" | "abandoned";
  started_at: string;
  ended_at: string | null;
  target_minutes: number;
  duration_minutes: number | null;
  elapsed_minutes?: number;
  elapsed_seconds: number;
  active_seconds: number;
  tracking_state: "running" | "paused";
  resumed_at: string | null;
  exam_id: number | null;
  week_id: number | null;
  task_kind: string | null;
  task_title: string;
  task_action: StudyAction | null;
  notes: string | null;
  recap: {
    counts: Record<StudySessionEventType, number>;
    lines: string[];
  } | null;
  events: StudySessionEvent[];
}

export interface DailySessionOverview {
  active: DailyStudySession | null;
  suggested: StudyItem | null;
  today: {minutes: number; sessions: number};
  recent: DailyStudySession[];
}

export interface Progress {
  current_exam: string;
  current_week: number;
  week_title: string;
  current_week_tasks: {total: number; completed: number; exempted: number; remaining: number};
  study_minutes_last_7_days: number;
  current_streak_days: number;
  domains_mastered: number;
  domains_available: number;
  evidence_note: string;
}

export type ObjectiveStatus =
  | "not_assessed"
  | "studied"
  | "practiced"
  | "strong_signal"
  | "needs_work";

export interface ObjectiveEvidence {
  objective_assessments: number;
  latest_assessment_pct: number | null;
  average_assessment_pct: number | null;
  latest_assessment_at: string | null;
  completed_tasks: number;
  cited_sections_opened: number;
  lessons_completed: number;
  recall_completed: number;
  source_sections_available: number;
}

export interface MasteryObjective {
  id: number;
  code: string;
  description: string;
  status: ObjectiveStatus;
  status_rank: number;
  mastery_score: number | null;
  evidence: ObjectiveEvidence;
}

export interface DomainSignal {
  scope_id: number | null;
  scope_name: string | null;
  status: string;
  retention_due_at: string | null;
  latest_raw_score_pct: number | null;
  latest_effective_score_pct: number | null;
  latest_attempt_at: string | null;
  open_gap_count: number;
}

export interface MasteryDomain {
  id: number;
  code: string;
  name: string;
  signal: DomainSignal;
  summary: Record<ObjectiveStatus | "total", number>;
  objectives: MasteryObjective[];
}

export interface MasteryMap {
  generated_at: string;
  exam_filter: string | null;
  totals: {
    objectives: number;
    strong_signal: number;
    practiced: number;
    studied: number;
    needs_work: number;
    not_assessed: number;
    objectives_with_direct_assessment: number;
    objectives_started: number;
    lessons_completed: number;
    recall_completed: number;
    evidence_coverage_pct: number;
  };
  exams: Array<{
    id: number;
    code: string;
    name: string;
    domains: MasteryDomain[];
  }>;
  evidence_note: string;
  mapping_note: string;
}

export interface ObjectiveDetail {
  id: number;
  code: string;
  description: string;
  exam_code: string;
  exam_name: string;
  domain_code: string;
  domain_name: string;
  evidence: Array<{
    stable_id: string;
    title: string;
    book_slug: string;
    book_title: string;
    snippet: string;
    focused_excerpt: string;
    content_sha256: string;
    source_role?: "primary_instruction" | "supplemental_instruction";
  }>;
  recent_attempts: Array<{
    id: number;
    score: number;
    total: number;
    occurred_at: string;
    held_out: number;
  }>;
  mastery: MasteryObjective & {
    domain_signal: DomainSignal;
    domain: {id: number; code: string; name: string};
  };
  learning: LearningState;
  retention: RetentionState | null;
  navigation: {
    previous: ObjectiveNavigation | null;
    next: ObjectiveNavigation | null;
  };
}

export type AnnotationKind = "highlight" | "note" | "bookmark";

export interface StudyAnnotation {
  id: number;
  objective_id: number;
  objective_code: string;
  exam_code: string;
  section_stable_id: string | null;
  section_title: string | null;
  book_title: string | null;
  kind: AnnotationKind;
  quote_text: string | null;
  prefix_text: string | null;
  suffix_text: string | null;
  note_text: string | null;
  content_sha256: string | null;
  current_content_sha256: string | null;
  anchor_start: number | null;
  anchor_end: number | null;
  anchor_status: "objective" | "exact" | "relocated" | "unresolved";
  client_key: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface AnnotationCreate {
  objective_id: number;
  kind: AnnotationKind;
  section_stable_id?: string;
  quote_text?: string;
  prefix_text?: string;
  suffix_text?: string;
  note_text?: string;
  content_sha256?: string;
  anchor_start?: number;
  anchor_end?: number;
  client_key?: string;
}

export type LabStatus = "planned" | "in_progress" | "completed";
export type LabCompletionLevel = "guided" | "referenced" | "unaided";

export interface LabTemplateSnapshot {
  slug: string;
  exam_code: string;
  objective_code: string;
  title: string;
  summary: string;
  difficulty: "beginner" | "intermediate" | "advanced";
  estimated_minutes: number;
  prerequisites: string[];
  equipment: string[];
  safety_notes: string[];
  steps: string[];
  success_checks: string[];
  evidence_prompts: string[];
}

export interface LabTemplate extends LabTemplateSnapshot {
  objective_id: number;
  objective_description: string;
  domain_name: string;
  history: {launched: number; completed: number; unaided: number};
}

export interface LabCatalog {
  catalog_version: string;
  certification_code: string;
  templates: LabTemplate[];
  summary: {
    available: number;
    beginner: number;
    intermediate: number;
    launched: number;
    completed: number;
    unresolved: number;
  };
  unresolved_objectives: string[];
  policy: string;
}

export interface HandsOnLab {
  id: number;
  objective_id: number;
  objective_code: string;
  objective_description: string;
  exam_code: string;
  domain_name: string;
  title: string;
  goal_text: string;
  environment_text: string | null;
  evidence_text: string | null;
  reflection_text: string | null;
  status: LabStatus;
  completion_level: LabCompletionLevel | null;
  client_key: string | null;
  archived: boolean;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  template_slug: string | null;
  catalog_version: string | null;
  template: LabTemplateSnapshot | null;
}

export interface LabsResponse {
  labs: HandsOnLab[];
  summary: {
    total: number;
    planned: number;
    in_progress: number;
    completed: number;
    unaided: number;
  };
  evidence_note: string;
}

export interface LabCreate {
  objective_id: number;
  title: string;
  goal_text: string;
  environment_text?: string;
  client_key?: string;
}

export interface LabUpdate {
  title?: string;
  goal_text?: string;
  environment_text?: string;
  evidence_text?: string;
  reflection_text?: string;
  status?: LabStatus;
  completion_level?: LabCompletionLevel;
  archived?: boolean;
}

export interface ObjectiveNavigation {
  id: number;
  code: string;
  description: string;
  exam_code: string;
}

export type LearningEventType =
  | "objective_opened"
  | "reading_opened"
  | "lesson_completed"
  | "recall_completed"
  | "coach_used";

export interface LearningState {
  objective_id: number;
  started: boolean;
  lesson_completed: boolean;
  recall_completed: boolean;
  counts: Record<LearningEventType, number>;
  last_activity_at: string | null;
  recent_events: Array<{
    id: number;
    objective_id: number;
    event_type: LearningEventType;
    event_key: string | null;
    metadata: Record<string, unknown>;
    occurred_at: string;
  }>;
  evidence_note: string;
}

export type RetentionRating = "again" | "hard" | "good" | "easy";

export interface RetentionState {
  objective_id: number;
  stage: number;
  interval_days: number;
  due_at: string;
  due: boolean;
  last_reviewed_at: string | null;
  last_rating: RetentionRating | null;
  review_count: number;
  evidence_note: string;
}

export interface RetentionQueue {
  generated_at: string;
  horizon_days: number;
  due_count: number;
  upcoming_count: number;
  next_due_at: string | null;
  items: Array<RetentionState & {
    code: string;
    description: string;
    exam_code: string;
    domain_code: string;
    domain_name: string;
  }>;
  evidence_note: string;
}

export interface ReadinessGate {
  key: string;
  label: string;
  passed: boolean;
  observed: unknown;
  required: unknown;
  rationale: string;
  action: {type: string; href: string};
}

export interface ExamReadiness {
  schema_version: number;
  generated_at: string;
  exam: {
    id: number;
    code: string;
    name: string;
    certification_id: string;
    certification_name: string;
  } | null;
  status: "unavailable" | "content_not_ready" | "building_evidence" | "ready_to_schedule";
  label: string;
  ready_to_schedule: boolean;
  gates: ReadinessGate[];
  passed_gate_count: number;
  total_gate_count: number;
  next_gate: ReadinessGate | null;
  evidence_note: string;
}

export interface CareerContext {
  schema_version: number;
  context_version: string;
  canonical_source: {
    status: "verified" | "changed_review_required" | "unavailable";
    path: string;
    expected_sha256: string;
    observed_sha256: string | null;
    last_verified: string;
  };
  certification_id: string | null;
  alignment: {
    relevance: "direct" | "supporting";
    claim_ids: string[];
    job_families: string[];
    note?: string;
  } | null;
  available_certifications: string[];
}

export interface AdaptivePlan {
  schema_version: string;
  days: number;
  minutes_per_day: number;
  provisional: boolean;
  replan_after_item_id: string | null;
  retention: {
    due: number;
    upcoming: number;
    next_due_at: string | null;
  };
  unscheduled_item_count: number;
  readiness: ExamReadiness;
  career_context: CareerContext;
  schedule: Array<{
    day: number;
    date: string;
    target_minutes: number;
    planned_minutes: number;
    items: StudyItem[];
    note: string;
  }>;
}

export interface Book {
  id: number;
  slug: string;
  title: string;
  creator: string;
  section_count: number;
  total_words: number;
  converter_version: number;
}

export interface CertificationPackSource {
  source_key: string;
  title: string;
  publisher: string;
  source_type: string;
  authority_tier: number;
  version_label: string;
  exam_codes: string[];
  source_url: string | null;
  source_sha256: string;
  status: "active" | "quarantined" | "retired" | "unavailable";
  status_reason: string;
  verified_at: string | null;
  refresh_status?: "match" | "drift" | "error" | null;
  observed_sha256?: string | null;
  last_checked_at?: string | null;
  last_checked_url?: string | null;
  refresh_error?: string | null;
  disposition: "active" | "quarantined" | "excluded";
  use_role: string;
  required: boolean;
}

export interface CertificationPack {
  id: number;
  certification_code: string;
  certification_name: string;
  pack_version: string;
  exam_version: string;
  status: "ready" | "blocked" | "superseded";
  compiler_version: string;
  policy_version: string;
  source_set_sha256: string;
  official_count: number;
  active_source_count: number;
  quarantined_count: number;
  objective_count: number;
  covered_count: number;
  conflict_count: number;
  compiled_at: string;
  report: {
    coverage_percent: number;
    blocking_findings: number;
    warnings: number;
    official_objective_text_count: number;
    runtime_policy: {
      open_web: string;
      assessment_sources_for_teaching: string;
      ai_authority: string;
      retrieval_requires_active_pack_source: boolean;
    };
  };
  sources: CertificationPackSource[];
  findings: Array<{
    category: string;
    severity: string;
    exam_code: string | null;
    objective_code: string | null;
    message: string;
  }>;
  coverage_by_exam: Array<{
    exam_code: string;
    objective_count: number;
    covered_count: number;
    missing_count: number;
    supplemental_only_count: number;
  }>;
}

export interface CertificationPackBuild {
  id: number;
  pack_version: string;
  exam_version: string;
  compiler_version: string;
  policy_version: string;
  source_set_sha256: string;
  build_sha256: string;
  status: "preview" | "blocked" | "published" | "superseded";
  compiled_at: string;
  published_at: string | null;
  report: {
    status: "ready" | "blocked";
    objectives: number;
    covered_objectives: number;
    official_objective_text_count: number;
    blocking_findings: number;
    warnings: number;
  };
  diff: {
    baseline: "none" | "published";
    changed: boolean;
    summary: {
      sources_added: number;
      sources_removed: number;
      sources_changed: number;
      objectives_added: number;
      objectives_removed: number;
      objectives_changed: number;
      official_descriptions_changed: number;
    };
    changes: Array<{
      kind: string;
      key: string;
      before?: string;
      after?: string;
    }>;
  };
}

export interface CertificationPackBuildState {
  certification_code: string;
  certification_name: string;
  active: CertificationPackBuild | null;
  latest: CertificationPackBuild | null;
  has_pending_preview: boolean;
}

export interface ObjectiveDossierSummaryItem {
  objective_id: number;
  status: "complete" | "thin" | "conflicted" | "missing";
  quality_score: number;
  primary_source_count: number;
  supplemental_source_count: number;
  assessment_source_count: number;
  direct_question_count: number;
  domain_question_count: number;
  code: string;
  description: string;
  exam_code: string;
  domain_code: string | null;
  domain_name: string | null;
}

export interface ObjectiveDossierSummary {
  id: number;
  pack_version: string;
  exam_version: string;
  status: "ready" | "blocked" | "superseded";
  compiler_version: string;
  certification_code: string;
  certification_name: string;
  total: number;
  counts: {
    complete: number;
    thin: number;
    conflicted: number;
    missing: number;
  };
  objectives: ObjectiveDossierSummaryItem[];
}

export interface LibraryJob {
  id: string;
  kind: string;
  status: "queued" | "converting" | "indexing" | "succeeded" | "failed";
  book_slug: string;
  phase: string;
  message: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SearchResult {
  stable_id: string;
  book_slug: string;
  title: string;
  snippet: string;
}

export interface SectionDetail {
  stable_id: string;
  title: string;
  book_title: string;
  content: string;
  objectives: Array<{exam_code: string; code: string}>;
}

export interface ReaderSection {
  stable_id: string;
  title: string;
  book_title: string;
  reader_format: "epub" | "markdown";
  html: string | null;
  content: string | null;
  locator: string | null;
}

export interface PlanTask {
  id: number;
  type: string;
  title: string;
  description: string;
  completed: number;
  exemption_reason: string | null;
}

export interface PlanWeek {
  id: number;
  week_number: number;
  title: string;
  focus: string;
  exam_code: string;
  tasks: PlanTask[];
  diagnostic_scope: {
    id: number;
    mastery_status: string;
    open_gap_count: number;
  } | null;
}

export interface StudyPlan {
  id: number;
  name: string;
  description: string;
  weeks: PlanWeek[];
}

export interface CoachResponse {
  provider_label: string;
  duration_ms: number;
  answer: {
    title: string;
    summary: string;
    steps: string[];
    check_yourself: string[];
    citations: Array<{
      citation_id: string;
      book_title: string;
      section_title: string;
    }>;
    caveat: string;
  };
}

export interface StudyGoalDay {
  date: string;
  minutes: number;
  met_target: boolean;
}

export interface StudyGoal {
  week_start: string;
  week_begin_utc: string;
  week_end_utc: string;
  timezone: string;
  daily_target_minutes: number | null;
  weekly_target_minutes: number | null;
  minutes_done: number;
  completed_minutes: number;
  live_minutes: number;
  sessions: number;
  percent: number | null;
  minutes_remaining: number | null;
  needs_selection: boolean;
  presets: number[];
  days: StudyGoalDay[];
}

export type DiagnosticMode = "diagnostic" | "retest" | "retention";
export type Confidence = "high" | "medium" | "low";

export interface QuestionFigure {
  member: string;
  url: string;
}

export interface DiagnosticResponse {
  id: number;
  question_id: number;
  position: number;
  prompt_snapshot: string;
  options: string[];
  submitted_answer: number[] | null;
  confidence: Confidence | null;
  is_correct: number | null;
  effective_score: number | null;
  correct_answers?: number[];
  submitted_answer_text?: string[];
  correct_answer_text?: string[];
  explanation?: string;
  figure?: QuestionFigure | null;
}

export interface DiagnosticAttemptSummary {
  id: number;
  mode: DiagnosticMode;
  state: "in_progress" | "submitted" | "abandoned";
  started_at: string;
  submitted_at: string | null;
  raw_score_pct: number | null;
  effective_score_pct: number | null;
  passed: number | null;
  bucket_result: string | null;
}

export interface DiagnosticAttempt extends DiagnosticAttemptSummary {
  scope_id: number;
  selection_disclosure: string;
  answers_redacted: boolean;
  responses: DiagnosticResponse[];
  reused_question_ids?: number[];
  gaps?: RemediationGap[];
}

export interface DiagnosticScope {
  id: number;
  slug: string;
  name: string;
  scope_type: string;
  exam_id: number;
  domain_id: number | null;
  question_target: number;
  min_valid_questions: number;
  raw_pass_threshold_pct: number;
  effective_pass_threshold_pct: number;
  enabled: number;
  mastery: {
    status: string;
    retention_due_at: string | null;
    last_attempt_id: number | null;
    best_attempt_id: number | null;
  } | null;
  available_question_count: number;
  insufficient_questions: boolean;
  remediation_items: Array<{
    id: number;
    status: "open" | "reviewed";
  }>;
  retest_available: boolean;
  recent_attempts: DiagnosticAttemptSummary[];
}

export interface RemediationReading {
  rank: number;
  book_slug: string;
  book_title: string;
  section_stable_id: string;
  section_title: string;
  snippet: string;
  content_hash: string;
  retrieval_basis: string;
}

export interface RemediationGap {
  remediation_id: number;
  gap_reason: "incorrect" | "correct_low_confidence";
  status: "open" | "reviewed";
  recall_prompt: string;
  lab_scaffold: string;
  question_id: number;
  prompt_snapshot: string;
  submitted_answer: number[];
  correct_answers: number[];
  submitted_answer_text: string[];
  correct_answer_text: string[];
  explanation: string;
  figure?: QuestionFigure | null;
  readings: RemediationReading[];
}

export interface DiagnosticSubmissionEntry {
  question_id: number;
  selected: number[];
  confidence: Confidence;
}

export type PracticeExamState = "in_progress" | "submitted" | "abandoned";
export type PracticeReadinessBand = "review_needed" | "approaching" | "strong_signal";

export interface PracticeExamResponse {
  id: number;
  question_id: number;
  position: number;
  domain_code: string | null;
  domain_name: string | null;
  objective_code: string | null;
  mapping_granularity: "domain" | "objective";
  prompt_snapshot: string;
  options: string[];
  submitted_answer: number[];
  is_correct?: number | null;
  correct_answers?: number[];
  explanation?: string;
  figure?: QuestionFigure | null;
}

export interface PracticeExamAttempt {
  id: number;
  exam_id: number;
  exam_code: string;
  exam_name: string;
  state: PracticeExamState;
  question_target: number;
  duration_minutes: number;
  started_at: string;
  expires_at: string;
  submitted_at: string | null;
  selection_disclosure: string;
  raw_score_pct: number | null;
  readiness_band: PracticeReadinessBand | null;
  timed_out: number | null;
  answers_redacted: boolean;
  answered_count: number;
  remaining_seconds: number;
  responses: PracticeExamResponse[];
  breakdown?: {
    domains: Array<{
      domain_code: string;
      domain_name: string;
      total: number;
      correct: number;
      score_pct: number;
    }>;
    objectives: Array<{
      objective_code: string;
      total: number;
      correct: number;
      score_pct: number;
    }>;
    mapping_note: string;
  };
}

export interface PracticeExamOverview {
  exams: Array<{
    id: number;
    code: string;
    name: string;
    available_questions: number;
    reserved_questions: number;
    in_progress: {
      id: number;
      started_at: string;
      expires_at: string;
    } | null;
    recent_attempts: Array<{
      id: number;
      state: PracticeExamState;
      started_at: string;
      submitted_at: string | null;
      raw_score_pct: number | null;
      readiness_band: PracticeReadinessBand | null;
      timed_out: number | null;
    }>;
  }>;
  question_target: number;
  duration_minutes: number;
  evidence_note: string;
  pool_note: string;
}

export interface AnalyticsScoreRow {
  id: number;
  exam_code: string;
  occurred_at: string;
  score_pct: number;
  scope_name?: string;
  mode?: string;
  passed?: number;
  readiness_band?: PracticeReadinessBand;
  timed_out?: number;
}

export interface Analytics {
  generated_at: string;
  window_days: number;
  current_state: {
    open_gaps: number;
    retention_due: number;
    lessons_started: number;
    lessons_completed: number;
    annotations: number;
    labs_planned: number;
    labs_in_progress: number;
    labs_completed: number;
    labs_unaided: number;
    diagnostic_attempts: number;
    full_exam_attempts: number;
  };
  assessment: {
    diagnostic: {
      submitted: number;
      latest_score_pct: number | null;
      best_score_pct: number | null;
      recent: AnalyticsScoreRow[];
    };
    full_exams: {
      submitted: number;
      latest_score_pct: number | null;
      best_score_pct: number | null;
      recent: AnalyticsScoreRow[];
      latest_domain_breakdown: Array<{
        domain_code: string;
        domain_name: string;
        total: number;
        correct: number;
        score_pct: number;
      }>;
      mapping_note: string;
    };
  };
  learning: {
    objectives_started: number;
    objective_opened: number;
    readings_opened: number;
    lessons_completed: number;
    recall_completed: number;
    coach_uses: number;
  };
  retention: {
    scheduled: number;
    due: number;
    reviews: number;
    ratings: Record<"again" | "hard" | "good" | "easy", number>;
  };
  notebook: {
    total: number;
    highlights: number;
    notes: number;
    bookmarks: number;
    objectives_with_annotations: number;
  };
  labs: {
    total: number;
    planned: number;
    in_progress: number;
    completed: number;
    unaided: number;
  };
  timeline: Array<{
    date: string;
    study_minutes: number;
    learning_events: number;
    assessments: number;
    retention_reviews: number;
    annotations: number;
    lab_completions: number;
  }>;
  next_action: {kind: string; title: string; reason: string; href: string};
  evidence_note: string;
  no_composite_note: string;
}
