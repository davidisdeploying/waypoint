CREATE TABLE IF NOT EXISTS hands_on_labs (
    id INTEGER PRIMARY KEY,
    objective_id INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    goal_text TEXT NOT NULL,
    environment_text TEXT,
    evidence_text TEXT,
    reflection_text TEXT,
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK(status IN ('planned', 'in_progress', 'completed')),
    completion_level TEXT
        CHECK(completion_level IS NULL OR completion_level IN ('guided', 'referenced', 'unaided')),
    client_key TEXT UNIQUE,
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hands_on_labs_objective_status
    ON hands_on_labs(objective_id, archived, status, updated_at DESC);
