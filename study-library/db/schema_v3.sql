-- Schema v3: Waypoint milestone state joins learning evidence in the one
-- canonical Study database. The JSON remains revisioned and validated so the
-- migration is additive and the existing frontend contract is unchanged.

CREATE TABLE IF NOT EXISTS waypoint_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    migration_id TEXT
);
