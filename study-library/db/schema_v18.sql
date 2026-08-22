-- Schema v18: recoverable removal of guided sessions from study totals.

CREATE INDEX IF NOT EXISTS idx_guided_sessions_visible_history
    ON guided_study_sessions(status, ended_at DESC)
    WHERE deleted_at IS NULL;
