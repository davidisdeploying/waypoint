-- Study Library schema v2 (additive). Adaptive knowledge checks + retrieval-backed
-- remediation. Every statement is CREATE-IF-NOT-EXISTS: this file is safe to run
-- against both a fresh database and the existing v1 database, and is idempotent.
PRAGMA foreign_keys = ON;

-- A checkable unit of knowledge: usually one curriculum week's domain, sometimes
-- a review-week composite. Domain-level evidence only (objective_id stays NULL
-- upstream in question_bank) -- see README/DESIGN for why exact-objective mapping
-- is not attempted from this source.
CREATE TABLE IF NOT EXISTS diagnostic_scopes (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                        TEXT NOT NULL UNIQUE,
    name                        TEXT NOT NULL,
    scope_type                  TEXT NOT NULL CHECK (scope_type IN ('domain','exam_composite')),
    plan_week_id                INTEGER REFERENCES plan_weeks(id) ON DELETE SET NULL,
    exam_id                     INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    domain_id                   INTEGER REFERENCES domains(id) ON DELETE SET NULL,
    question_target             INTEGER NOT NULL DEFAULT 20,
    min_valid_questions         INTEGER NOT NULL DEFAULT 10,
    raw_pass_threshold_pct       REAL NOT NULL DEFAULT 85.0,
    effective_pass_threshold_pct REAL NOT NULL DEFAULT 80.0,
    retention_interval_days      INTEGER NOT NULL DEFAULT 14,
    provenance                  TEXT NOT NULL,
    enabled                     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    coverage_metadata_json       TEXT NOT NULL DEFAULT '{}',
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diag_scopes_week ON diagnostic_scopes(plan_week_id);
CREATE INDEX IF NOT EXISTS idx_diag_scopes_exam ON diagnostic_scopes(exam_id);

-- One imported practice-test question. objective_id is always NULL for imported
-- rows (mapping_granularity='domain'); the column exists for future manual
-- objective curation (see DESIGN "Next phases").
CREATE TABLE IF NOT EXISTS question_bank (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_id               TEXT NOT NULL UNIQUE,
    exam_id                 INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    domain_id               INTEGER REFERENCES domains(id) ON DELETE SET NULL,
    objective_id            INTEGER REFERENCES objectives(id) ON DELETE SET NULL,
    mapping_granularity     TEXT NOT NULL DEFAULT 'domain' CHECK (mapping_granularity IN ('domain','objective')),
    question_book_slug      TEXT NOT NULL,
    question_section_id     INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    question_number         INTEGER NOT NULL,
    answer_book_slug        TEXT NOT NULL,
    answer_section_id       INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    prompt                  TEXT NOT NULL,
    options_json            TEXT NOT NULL,
    correct_answers_json    TEXT NOT NULL,
    explanation             TEXT NOT NULL,
    provenance              TEXT NOT NULL,
    content_hash            TEXT NOT NULL,
    requires_figure         INTEGER NOT NULL DEFAULT 0 CHECK (requires_figure IN (0,1)),
    critical                INTEGER NOT NULL DEFAULT 0 CHECK (critical IN (0,1)),
    active                  INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qbank_exam_domain_active ON question_bank(exam_id, domain_id, active);
CREATE INDEX IF NOT EXISTS idx_qbank_book_chapter ON question_bank(question_book_slug, question_number);

CREATE TABLE IF NOT EXISTS diagnostic_attempts (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_id                 INTEGER NOT NULL REFERENCES diagnostic_scopes(id) ON DELETE CASCADE,
    mode                     TEXT NOT NULL CHECK (mode IN ('diagnostic','retest','retention')),
    state                    TEXT NOT NULL DEFAULT 'in_progress' CHECK (state IN ('in_progress','submitted','abandoned')),
    started_at               TEXT NOT NULL,
    submitted_at             TEXT,
    question_ids_json        TEXT NOT NULL,
    reused_question_ids_json TEXT NOT NULL DEFAULT '[]',
    selection_disclosure     TEXT NOT NULL DEFAULT '',
    raw_score_pct            REAL,
    effective_score_pct      REAL,
    passed                   INTEGER CHECK (passed IN (0,1)),
    bucket_result            TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diag_attempts_scope ON diagnostic_attempts(scope_id, started_at);
CREATE INDEX IF NOT EXISTS idx_diag_attempts_state ON diagnostic_attempts(state);

-- Snapshots the question/options/correct-answers at attempt time so a later
-- question_bank edit can never retroactively change a past attempt's grading.
CREATE TABLE IF NOT EXISTS diagnostic_responses (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id                  INTEGER NOT NULL REFERENCES diagnostic_attempts(id) ON DELETE CASCADE,
    question_id                 INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE RESTRICT,
    position                    INTEGER NOT NULL,
    prompt_snapshot              TEXT NOT NULL,
    options_snapshot_json        TEXT NOT NULL,
    correct_answers_snapshot_json TEXT NOT NULL,
    submitted_answer_json        TEXT,
    confidence                  TEXT CHECK (confidence IN ('high','medium','low')),
    is_correct                  INTEGER CHECK (is_correct IN (0,1)),
    effective_score              REAL,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL,
    UNIQUE(attempt_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_diag_responses_attempt ON diagnostic_responses(attempt_id, position);

CREATE TABLE IF NOT EXISTS remediation_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id    INTEGER NOT NULL REFERENCES diagnostic_attempts(id) ON DELETE CASCADE,
    response_id   INTEGER NOT NULL UNIQUE REFERENCES diagnostic_responses(id) ON DELETE CASCADE,
    scope_id      INTEGER NOT NULL REFERENCES diagnostic_scopes(id) ON DELETE CASCADE,
    gap_reason    TEXT NOT NULL CHECK (gap_reason IN ('incorrect','correct_low_confidence')),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','reviewed')),
    recall_prompt TEXT NOT NULL,
    lab_scaffold  TEXT NOT NULL,
    reviewed_at   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_remediation_scope_status ON remediation_items(scope_id, status);
CREATE INDEX IF NOT EXISTS idx_remediation_attempt ON remediation_items(attempt_id);

CREATE TABLE IF NOT EXISTS remediation_readings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    remediation_item_id INTEGER NOT NULL REFERENCES remediation_items(id) ON DELETE CASCADE,
    rank                INTEGER NOT NULL,
    book_slug           TEXT NOT NULL,
    book_title          TEXT NOT NULL,
    section_stable_id   TEXT NOT NULL,
    section_title       TEXT NOT NULL,
    snippet             TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    retrieval_basis     TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE(remediation_item_id, rank)
);

CREATE TABLE IF NOT EXISTS scope_mastery (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_id         INTEGER NOT NULL UNIQUE REFERENCES diagnostic_scopes(id) ON DELETE CASCADE,
    status           TEXT NOT NULL DEFAULT 'unassessed'
                     CHECK (status IN ('unassessed','provisional_mastery','needs_remediation',
                                        'mastered_after_remediation','retention_due')),
    last_attempt_id  INTEGER REFERENCES diagnostic_attempts(id) ON DELETE SET NULL,
    best_attempt_id  INTEGER REFERENCES diagnostic_attempts(id) ON DELETE SET NULL,
    retention_due_at TEXT,
    updated_at       TEXT NOT NULL
);

-- Audit trail for "passing the diagnostic exempted these broad plan tasks" --
-- exemption is disclosed here, never faked as plan_tasks.completed=1.
CREATE TABLE IF NOT EXISTS plan_task_exemptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_task_id INTEGER NOT NULL UNIQUE REFERENCES plan_tasks(id) ON DELETE CASCADE,
    scope_id     INTEGER NOT NULL REFERENCES diagnostic_scopes(id) ON DELETE CASCADE,
    attempt_id   INTEGER NOT NULL REFERENCES diagnostic_attempts(id) ON DELETE CASCADE,
    exempted_at  TEXT NOT NULL,
    reason       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_task_exemptions_scope ON plan_task_exemptions(scope_id);
