-- Schema v15: immutable provenance for labs launched from governed templates.

CREATE TABLE IF NOT EXISTS lab_template_launches (
    lab_id                 INTEGER PRIMARY KEY REFERENCES hands_on_labs(id) ON DELETE CASCADE,
    template_slug          TEXT NOT NULL,
    catalog_version        TEXT NOT NULL,
    template_snapshot_json TEXT NOT NULL,
    launched_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lab_template_launches_slug
    ON lab_template_launches(template_slug, launched_at DESC);
