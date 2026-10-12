-- Schema v8: materialized, cited objective dossiers for pack inspection.

CREATE TABLE IF NOT EXISTS objective_dossiers (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_id                    INTEGER NOT NULL REFERENCES certification_packs(id) ON DELETE CASCADE,
    objective_id               INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
    official_source_id         INTEGER NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
    status                     TEXT NOT NULL CHECK (status IN (
                                   'complete','thin','conflicted','missing'
                               )),
    quality_score              INTEGER NOT NULL CHECK (quality_score BETWEEN 0 AND 100),
    primary_section_id         INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    primary_source_count       INTEGER NOT NULL DEFAULT 0,
    supplemental_source_count  INTEGER NOT NULL DEFAULT 0,
    assessment_source_count    INTEGER NOT NULL DEFAULT 0,
    direct_question_count      INTEGER NOT NULL DEFAULT 0,
    domain_question_count      INTEGER NOT NULL DEFAULT 0,
    dossier_json               TEXT NOT NULL,
    compiled_at                TEXT NOT NULL,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL,
    UNIQUE(pack_id, objective_id)
);
CREATE INDEX IF NOT EXISTS idx_objective_dossiers_pack_status
    ON objective_dossiers(pack_id, status, quality_score);
CREATE INDEX IF NOT EXISTS idx_objective_dossiers_objective
    ON objective_dossiers(objective_id, pack_id);
