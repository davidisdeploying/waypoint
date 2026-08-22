-- Study Library schema. SQLite 3 + FTS5.
-- Runtime derivative only: source markdown/report files remain the source of truth on disk.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                TEXT NOT NULL UNIQUE,
    title               TEXT NOT NULL,
    creator             TEXT,
    language            TEXT,
    source_dir          TEXT NOT NULL,
    source_epub_sha256  TEXT,
    converter_version   INTEGER,
    generated_by        TEXT,
    section_count       INTEGER NOT NULL DEFAULT 0,
    total_words         INTEGER NOT NULL DEFAULT 0,
    corpus_sha256       TEXT,
    ingested_at         TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_id        TEXT NOT NULL UNIQUE,
    book_id          INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    position         INTEGER NOT NULL,
    source_position  INTEGER,
    part             INTEGER,
    part_count       INTEGER,
    title            TEXT NOT NULL,
    source_item      TEXT,
    source_path      TEXT NOT NULL,
    word_count       INTEGER NOT NULL DEFAULT 0,
    content          TEXT NOT NULL,
    content_sha256   TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE(book_id, position)
);
CREATE INDEX IF NOT EXISTS idx_sections_book ON sections(book_id, position);

-- External-content FTS5 index over sections. Kept in sync via triggers.
CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    title,
    content,
    content='sections',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS sections_ai AFTER INSERT ON sections BEGIN
    INSERT INTO sections_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS sections_ad AFTER DELETE ON sections BEGIN
    INSERT INTO sections_fts(sections_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS sections_au AFTER UPDATE ON sections BEGIN
    INSERT INTO sections_fts(sections_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
    INSERT INTO sections_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;

CREATE TABLE IF NOT EXISTS certifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    sequence_order INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exams (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    certification_id  INTEGER NOT NULL REFERENCES certifications(id) ON DELETE CASCADE,
    code              TEXT NOT NULL,
    name              TEXT NOT NULL,
    sequence_order    INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(certification_id, code)
);

CREATE TABLE IF NOT EXISTS domains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id     INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    provenance  TEXT,
    confidence  REAL NOT NULL DEFAULT 0.5,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(exam_id, code)
);

CREATE TABLE IF NOT EXISTS objectives (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id     INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    domain_id   INTEGER REFERENCES domains(id) ON DELETE SET NULL,
    code        TEXT NOT NULL,
    description TEXT NOT NULL,
    provenance  TEXT,
    confidence  REAL NOT NULL DEFAULT 0.5,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(exam_id, code)
);

CREATE TABLE IF NOT EXISTS objective_chunk_links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    objective_id INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
    section_id   INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    book_id      INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    snippet      TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE(objective_id, section_id)
);
CREATE INDEX IF NOT EXISTS idx_ocl_objective ON objective_chunk_links(objective_id);
CREATE INDEX IF NOT EXISTS idx_ocl_section ON objective_chunk_links(section_id);

CREATE TABLE IF NOT EXISTS study_plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    certification_id INTEGER NOT NULL REFERENCES certifications(id) ON DELETE CASCADE,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_weeks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
    week_number INTEGER NOT NULL,
    exam_id     INTEGER REFERENCES exams(id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    focus       TEXT,
    goals_json  TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(plan_id, week_number)
);

CREATE TABLE IF NOT EXISTS plan_tasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id             INTEGER NOT NULL REFERENCES plan_weeks(id) ON DELETE CASCADE,
    position            INTEGER NOT NULL DEFAULT 0,
    type                TEXT NOT NULL CHECK (type IN ('reading','lab','recall','practice')),
    title               TEXT NOT NULL,
    description         TEXT,
    related_section_id  INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    related_objective_id INTEGER REFERENCES objectives(id) ON DELETE SET NULL,
    completed           INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0,1)),
    completed_at        TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_tasks_week ON plan_tasks(week_id, position);

CREATE TABLE IF NOT EXISTS study_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at     TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    exam_id         INTEGER REFERENCES exams(id) ON DELETE SET NULL,
    week_id         INTEGER REFERENCES plan_weeks(id) ON DELETE SET NULL,
    notes           TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_occurred ON study_sessions(occurred_at);

CREATE TABLE IF NOT EXISTS practice_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id       INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    objective_id  INTEGER REFERENCES objectives(id) ON DELETE SET NULL,
    score         INTEGER NOT NULL CHECK (score >= 0),
    total         INTEGER NOT NULL CHECK (total > 0),
    occurred_at   TEXT NOT NULL,
    notes         TEXT,
    held_out      INTEGER NOT NULL DEFAULT 0 CHECK (held_out IN (0,1)),
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_occurred ON practice_attempts(occurred_at);
CREATE INDEX IF NOT EXISTS idx_attempts_exam ON practice_attempts(exam_id);

CREATE TABLE IF NOT EXISTS objective_mastery (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    objective_id   INTEGER NOT NULL UNIQUE REFERENCES objectives(id) ON DELETE CASCADE,
    evidence_json  TEXT NOT NULL DEFAULT '{}',
    mastery_score  REAL,
    status         TEXT NOT NULL DEFAULT 'not_started' CHECK (status IN ('not_started','in_progress','practiced','reviewed')),
    updated_at     TEXT NOT NULL
);
