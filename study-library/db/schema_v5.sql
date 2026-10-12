-- Schema v5: resumable daily study sessions with bounded activity evidence.

CREATE TABLE IF NOT EXISTS guided_study_sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    status           TEXT NOT NULL CHECK (status IN ('active','completed','abandoned')),
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    target_minutes   INTEGER NOT NULL CHECK (target_minutes BETWEEN 5 AND 240),
    duration_minutes INTEGER,
    active_seconds   INTEGER NOT NULL DEFAULT 0 CHECK (active_seconds >= 0),
    tracking_state   TEXT NOT NULL DEFAULT 'paused' CHECK (tracking_state IN ('running','paused')),
    resumed_at       TEXT,
    exam_id          INTEGER REFERENCES exams(id) ON DELETE SET NULL,
    week_id          INTEGER REFERENCES plan_weeks(id) ON DELETE SET NULL,
    task_kind        TEXT,
    task_title       TEXT NOT NULL,
    task_action_json TEXT,
    notes            TEXT,
    recap_json       TEXT,
    history_session_id INTEGER REFERENCES study_sessions(id) ON DELETE SET NULL,
    deleted_at       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_guided_session_one_active
    ON guided_study_sessions(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_guided_sessions_started
    ON guided_study_sessions(started_at DESC);

CREATE TABLE IF NOT EXISTS guided_study_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES guided_study_sessions(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    label       TEXT NOT NULL,
    event_key   TEXT,
    metadata_json TEXT,
    occurred_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_guided_event_dedupe
    ON guided_study_events(session_id, event_key) WHERE event_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_guided_events_session
    ON guided_study_events(session_id, occurred_at);
