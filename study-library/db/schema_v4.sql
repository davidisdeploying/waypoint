-- Schema v4: durable, observable book conversion/indexing jobs.

CREATE TABLE IF NOT EXISTS library_jobs (
    id              TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    kind            TEXT NOT NULL CHECK (kind IN ('convert_index','reindex')),
    status          TEXT NOT NULL CHECK (
                        status IN ('queued','converting','indexing','succeeded','failed')
                    ),
    source_path     TEXT NOT NULL,
    output_path     TEXT NOT NULL,
    book_slug       TEXT NOT NULL,
    book_kind       TEXT NOT NULL CHECK (
                        book_kind IN ('guide','review','practice','supplemental')
                    ),
    phase           TEXT NOT NULL,
    message         TEXT NOT NULL,
    error           TEXT,
    result_json     TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_jobs_status_created
    ON library_jobs(status, created_at);
