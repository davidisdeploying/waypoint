-- Schema v9: immutable certification-pack previews and explicit promotion.

CREATE TABLE IF NOT EXISTS certification_pack_builds (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    certification_id    INTEGER NOT NULL REFERENCES certifications(id) ON DELETE CASCADE,
    pack_version        TEXT NOT NULL,
    exam_version        TEXT NOT NULL,
    compiler_version    TEXT NOT NULL,
    policy_version      TEXT NOT NULL,
    source_set_sha256   TEXT NOT NULL,
    build_sha256        TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN (
                            'preview','blocked','published','superseded'
                        )),
    report_json         TEXT NOT NULL,
    snapshot_json       TEXT NOT NULL,
    diff_json           TEXT NOT NULL,
    compiled_at         TEXT NOT NULL,
    published_at        TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE(certification_id, build_sha256)
);
CREATE INDEX IF NOT EXISTS idx_pack_builds_certification
    ON certification_pack_builds(certification_id, status, id DESC);

CREATE TRIGGER IF NOT EXISTS certification_pack_builds_immutable
BEFORE UPDATE ON certification_pack_builds
WHEN NEW.certification_id != OLD.certification_id
  OR NEW.pack_version != OLD.pack_version
  OR NEW.exam_version != OLD.exam_version
  OR NEW.compiler_version != OLD.compiler_version
  OR NEW.policy_version != OLD.policy_version
  OR NEW.source_set_sha256 != OLD.source_set_sha256
  OR NEW.build_sha256 != OLD.build_sha256
  OR NEW.report_json != OLD.report_json
  OR NEW.snapshot_json != OLD.snapshot_json
  OR NEW.diff_json != OLD.diff_json
  OR NEW.compiled_at != OLD.compiled_at
  OR NEW.created_at != OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'certification pack build snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS certification_pack_builds_status_transition
BEFORE UPDATE OF status ON certification_pack_builds
WHEN NOT (
    NEW.status = OLD.status
    OR (OLD.status = 'preview' AND NEW.status = 'published')
    OR (OLD.status = 'published' AND NEW.status = 'superseded')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid certification pack build status transition');
END;

CREATE TABLE IF NOT EXISTS certification_pack_active_builds (
    certification_id    INTEGER PRIMARY KEY
                            REFERENCES certifications(id) ON DELETE CASCADE,
    build_id            INTEGER NOT NULL
                            REFERENCES certification_pack_builds(id) ON DELETE RESTRICT,
    promoted_at         TEXT NOT NULL
);
