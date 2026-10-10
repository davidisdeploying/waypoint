-- Schema v10: certification learning activity outside timed study sessions.

CREATE TABLE IF NOT EXISTS learning_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    objective_id    INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL CHECK (event_type IN (
                        'objective_opened',
                        'reading_opened',
                        'lesson_completed',
                        'recall_completed',
                        'coach_used'
                    )),
    event_key       TEXT UNIQUE,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    occurred_at     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_events_objective
    ON learning_events(objective_id, event_type, occurred_at DESC);
