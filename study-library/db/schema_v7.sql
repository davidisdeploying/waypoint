-- Schema v7: append-only verification history for pinned official sources.

CREATE TABLE IF NOT EXISTS source_verification_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id         INTEGER NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    expected_sha256   TEXT NOT NULL,
    observed_sha256   TEXT,
    requested_url     TEXT NOT NULL,
    final_url         TEXT,
    status            TEXT NOT NULL CHECK (status IN ('match','drift','error')),
    http_etag         TEXT,
    http_last_modified TEXT,
    content_length    INTEGER,
    checked_at        TEXT NOT NULL,
    error             TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_verification_latest
    ON source_verification_runs(source_id, checked_at DESC, id DESC);
