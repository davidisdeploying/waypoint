-- Schema v11: objective-level spaced-retention scheduling and review history.

CREATE TABLE IF NOT EXISTS objective_retention_state (
    objective_id       INTEGER PRIMARY KEY REFERENCES objectives(id) ON DELETE CASCADE,
    stage              INTEGER NOT NULL DEFAULT 0 CHECK (stage >= 0 AND stage <= 8),
    interval_days      INTEGER NOT NULL DEFAULT 1 CHECK (interval_days >= 1 AND interval_days <= 120),
    due_at             TEXT NOT NULL,
    last_reviewed_at   TEXT,
    last_rating        TEXT CHECK (last_rating IS NULL OR last_rating IN (
                           'again', 'hard', 'good', 'easy'
                       )),
    review_count       INTEGER NOT NULL DEFAULT 0 CHECK (review_count >= 0),
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_objective_retention_due
    ON objective_retention_state(due_at, objective_id);

CREATE TABLE IF NOT EXISTS objective_retention_reviews (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    objective_id       INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
    rating             TEXT NOT NULL CHECK (rating IN ('again', 'hard', 'good', 'easy')),
    previous_stage     INTEGER NOT NULL,
    next_stage         INTEGER NOT NULL,
    previous_due_at    TEXT NOT NULL,
    next_due_at        TEXT NOT NULL,
    interval_days      INTEGER NOT NULL,
    event_key          TEXT UNIQUE,
    occurred_at        TEXT NOT NULL,
    created_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_objective_retention_reviews_objective
    ON objective_retention_reviews(objective_id, occurred_at DESC);
