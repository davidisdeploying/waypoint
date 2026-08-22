-- Schema v12: private learner notes, highlights, and bookmarks.

CREATE TABLE IF NOT EXISTS study_annotations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    objective_id        INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
    section_stable_id   TEXT REFERENCES sections(stable_id) ON DELETE CASCADE,
    kind                TEXT NOT NULL CHECK (kind IN ('highlight', 'note', 'bookmark')),
    quote_text          TEXT,
    prefix_text         TEXT,
    suffix_text         TEXT,
    note_text           TEXT,
    content_sha256      TEXT,
    anchor_start        INTEGER,
    anchor_end          INTEGER,
    client_key          TEXT UNIQUE,
    archived            INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    CHECK (anchor_start IS NULL OR anchor_start >= 0),
    CHECK (anchor_end IS NULL OR anchor_end >= anchor_start)
);

CREATE INDEX IF NOT EXISTS idx_study_annotations_objective
    ON study_annotations(objective_id, archived, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_study_annotations_section
    ON study_annotations(section_stable_id, archived, created_at DESC);
