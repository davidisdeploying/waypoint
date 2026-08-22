CREATE TABLE IF NOT EXISTS practice_exam_question_pool (
    question_id INTEGER PRIMARY KEY REFERENCES question_bank(id) ON DELETE CASCADE,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    pool_version TEXT NOT NULL,
    reserved_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_practice_exam_pool_exam
    ON practice_exam_question_pool(exam_id, question_id);

CREATE TABLE IF NOT EXISTS practice_exam_attempts (
    id INTEGER PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'in_progress'
        CHECK(state IN ('in_progress', 'submitted', 'abandoned')),
    question_target INTEGER NOT NULL,
    duration_minutes INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    submitted_at TEXT,
    question_ids_json TEXT NOT NULL,
    reused_question_ids_json TEXT NOT NULL DEFAULT '[]',
    selection_disclosure TEXT NOT NULL,
    raw_score_pct REAL,
    readiness_band TEXT
        CHECK(readiness_band IS NULL OR readiness_band IN ('review_needed', 'approaching', 'strong_signal')),
    timed_out INTEGER CHECK(timed_out IS NULL OR timed_out IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_practice_exam_attempts_exam_state
    ON practice_exam_attempts(exam_id, state, started_at DESC);

CREATE TABLE IF NOT EXISTS practice_exam_responses (
    id INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES practice_exam_attempts(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    domain_id INTEGER REFERENCES domains(id) ON DELETE SET NULL,
    objective_id INTEGER REFERENCES objectives(id) ON DELETE SET NULL,
    mapping_granularity TEXT NOT NULL CHECK(mapping_granularity IN ('domain', 'objective')),
    prompt_snapshot TEXT NOT NULL,
    options_snapshot_json TEXT NOT NULL,
    correct_answers_snapshot_json TEXT NOT NULL,
    submitted_answer_json TEXT,
    is_correct INTEGER CHECK(is_correct IS NULL OR is_correct IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(attempt_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_practice_exam_responses_attempt
    ON practice_exam_responses(attempt_id, position);
