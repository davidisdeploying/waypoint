-- Schema v6: governed, versioned certification knowledge packs.

CREATE TABLE IF NOT EXISTS source_registry (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    certification_id  INTEGER NOT NULL REFERENCES certifications(id) ON DELETE CASCADE,
    book_id           INTEGER REFERENCES books(id) ON DELETE SET NULL,
    source_key        TEXT NOT NULL UNIQUE,
    title             TEXT NOT NULL,
    publisher         TEXT NOT NULL,
    source_type       TEXT NOT NULL CHECK (source_type IN (
                          'official_objectives','official_vendor',
                          'instruction','review','assessment'
                      )),
    authority_tier    INTEGER NOT NULL CHECK (authority_tier BETWEEN 1 AND 4),
    version_label     TEXT NOT NULL,
    exam_codes_json   TEXT NOT NULL,
    source_url        TEXT,
    source_sha256     TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN (
                          'active','quarantined','retired','unavailable'
                      )),
    status_reason     TEXT NOT NULL,
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    verified_at       TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_registry_certification
    ON source_registry(certification_id, status, authority_tier);
CREATE INDEX IF NOT EXISTS idx_source_registry_book
    ON source_registry(book_id);

CREATE TABLE IF NOT EXISTS certification_packs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    certification_id   INTEGER NOT NULL REFERENCES certifications(id) ON DELETE CASCADE,
    pack_version       TEXT NOT NULL,
    exam_version       TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('ready','blocked','superseded')),
    compiler_version   TEXT NOT NULL,
    policy_version     TEXT NOT NULL,
    source_set_sha256  TEXT NOT NULL,
    official_count     INTEGER NOT NULL DEFAULT 0,
    active_source_count INTEGER NOT NULL DEFAULT 0,
    quarantined_count  INTEGER NOT NULL DEFAULT 0,
    objective_count    INTEGER NOT NULL DEFAULT 0,
    covered_count      INTEGER NOT NULL DEFAULT 0,
    conflict_count     INTEGER NOT NULL DEFAULT 0,
    report_json        TEXT NOT NULL,
    compiled_at        TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE(certification_id, pack_version)
);
CREATE INDEX IF NOT EXISTS idx_certification_packs_current
    ON certification_packs(certification_id, status, compiled_at DESC);

CREATE TABLE IF NOT EXISTS certification_pack_sources (
    pack_id        INTEGER NOT NULL REFERENCES certification_packs(id) ON DELETE CASCADE,
    source_id      INTEGER NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    disposition    TEXT NOT NULL CHECK (disposition IN ('active','quarantined','excluded')),
    use_role       TEXT NOT NULL CHECK (use_role IN (
                       'authoritative_scope','fact_validation',
                       'primary_instruction','supplemental_instruction',
                       'assessment_only'
                   )),
    required       INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0,1)),
    reason         TEXT NOT NULL,
    PRIMARY KEY(pack_id, source_id)
);

CREATE TABLE IF NOT EXISTS certification_pack_objectives (
    pack_id             INTEGER NOT NULL REFERENCES certification_packs(id) ON DELETE CASCADE,
    objective_id        INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
    official_source_id  INTEGER NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
    coverage_status     TEXT NOT NULL CHECK (coverage_status IN (
                            'covered','supplemental_only','missing'
                        )),
    primary_source_count INTEGER NOT NULL DEFAULT 0,
    supplemental_source_count INTEGER NOT NULL DEFAULT 0,
    assessment_source_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(pack_id, objective_id)
);
CREATE INDEX IF NOT EXISTS idx_pack_objectives_status
    ON certification_pack_objectives(pack_id, coverage_status);

CREATE TABLE IF NOT EXISTS compiler_findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_id       INTEGER NOT NULL REFERENCES certification_packs(id) ON DELETE CASCADE,
    finding_key   TEXT NOT NULL,
    category      TEXT NOT NULL CHECK (category IN (
                      'version','coverage','conflict','integrity'
                  )),
    severity      TEXT NOT NULL CHECK (severity IN ('info','warning','blocking')),
    exam_code     TEXT,
    objective_code TEXT,
    message       TEXT NOT NULL,
    details_json  TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    UNIQUE(pack_id, finding_key)
);
CREATE INDEX IF NOT EXISTS idx_compiler_findings_pack
    ON compiler_findings(pack_id, severity, category);
