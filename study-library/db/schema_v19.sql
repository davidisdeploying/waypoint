-- Study Library schema v19: Prospect learning proposals.
-- These are planning requests only. They never write learning_events, mastery,
-- attempts, sessions, completion, or credential status.
CREATE TABLE IF NOT EXISTS learning_requests (
  id                     INTEGER PRIMARY KEY,
  source                 TEXT NOT NULL,
  source_audit_id        INTEGER NOT NULL,
  source_listing_id      INTEGER,
  role                   TEXT,
  company                TEXT,
  skill                  TEXT NOT NULL,
  technology             TEXT NOT NULL,
  rationale              TEXT NOT NULL,
  priority               TEXT NOT NULL,
  certification_id       TEXT,
  certification_label    TEXT,
  waypoint_scope_status  TEXT NOT NULL,
  career_claims_hash     TEXT NOT NULL,
  source_requirement_ids TEXT NOT NULL,
  status                 TEXT NOT NULL DEFAULT 'proposed',
  created_at             TEXT NOT NULL,
  UNIQUE(source, source_audit_id, technology)
);
CREATE INDEX IF NOT EXISTS idx_learning_requests_status ON learning_requests(status, created_at DESC);
