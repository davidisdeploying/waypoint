"""SQLite connection + schema init helpers for Study Library."""
import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"
SCHEMA_V2_PATH = REPO_ROOT / "db" / "schema_v2.sql"
SCHEMA_V3_PATH = REPO_ROOT / "db" / "schema_v3.sql"
SCHEMA_V4_PATH = REPO_ROOT / "db" / "schema_v4.sql"
SCHEMA_V5_PATH = REPO_ROOT / "db" / "schema_v5.sql"
SCHEMA_V6_PATH = REPO_ROOT / "db" / "schema_v6.sql"
SCHEMA_V7_PATH = REPO_ROOT / "db" / "schema_v7.sql"
SCHEMA_V8_PATH = REPO_ROOT / "db" / "schema_v8.sql"
SCHEMA_V9_PATH = REPO_ROOT / "db" / "schema_v9.sql"
SCHEMA_V10_PATH = REPO_ROOT / "db" / "schema_v10.sql"
SCHEMA_V11_PATH = REPO_ROOT / "db" / "schema_v11.sql"
SCHEMA_V12_PATH = REPO_ROOT / "db" / "schema_v12.sql"
SCHEMA_V13_PATH = REPO_ROOT / "db" / "schema_v13.sql"
SCHEMA_V14_PATH = REPO_ROOT / "db" / "schema_v14.sql"
SCHEMA_V15_PATH = REPO_ROOT / "db" / "schema_v15.sql"
SCHEMA_V16_PATH = REPO_ROOT / "db" / "schema_v16.sql"
SCHEMA_V17_PATH = REPO_ROOT / "db" / "schema_v17.sql"
SCHEMA_V18_PATH = REPO_ROOT / "db" / "schema_v18.sql"
SCHEMA_V19_PATH = REPO_ROOT / "db" / "schema_v19.sql"
DEFAULT_DB_PATH = REPO_ROOT / "data" / "study_library.db"

SCHEMA_VERSION = "19"


def db_path():
    override = os.environ.get("STUDY_LIBRARY_DB")
    return Path(override) if override else DEFAULT_DB_PATH


def connect(path=None):
    path = Path(path) if path else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_column(conn, table, column, declaration):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in columns:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    return True


def init_db(conn):
    """Apply the base schema, then the additive v2 schema. Both files are
    CREATE-IF-NOT-EXISTS throughout, so running this against a fresh DB or an
    existing v1 DB is equally safe and idempotent -- no destructive ALTERs."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V2_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V3_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V4_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V5_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V6_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V7_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V8_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V9_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V10_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V11_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V12_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V13_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V14_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V15_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V16_PATH.read_text(encoding="utf-8"))
    _ensure_column(conn, "books", "source_epub_path", "TEXT")
    conn.executescript(SCHEMA_V17_PATH.read_text(encoding="utf-8"))
    added_active_seconds = _ensure_column(
        conn,
        "guided_study_sessions",
        "active_seconds",
        "INTEGER NOT NULL DEFAULT 0 CHECK (active_seconds >= 0)",
    )
    _ensure_column(
        conn,
        "guided_study_sessions",
        "tracking_state",
        "TEXT NOT NULL DEFAULT 'paused' CHECK (tracking_state IN ('running','paused'))",
    )
    _ensure_column(conn, "guided_study_sessions", "resumed_at", "TEXT")
    _ensure_column(
        conn,
        "guided_study_sessions",
        "history_session_id",
        "INTEGER REFERENCES study_sessions(id) ON DELETE SET NULL",
    )
    _ensure_column(conn, "guided_study_sessions", "deleted_at", "TEXT")
    # EPUB member path of the figure a practice question depends on. NULL means
    # the question needs no picture, or that its picture could not be resolved.
    _ensure_column(conn, "question_bank", "figure_member", "TEXT")
    # Last proof the client was alive while a session was running. An open
    # running segment is credited only up to this plus a grace window, so a
    # browser killed before it can pause cannot accrue wall-clock time.
    _ensure_column(conn, "guided_study_sessions", "last_seen_at", "TEXT")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS study_week_goals ("
        "  week_start           TEXT PRIMARY KEY,"
        "  daily_target_minutes INTEGER NOT NULL CHECK (daily_target_minutes BETWEEN 5 AND 240),"
        "  created_at           TEXT NOT NULL,"
        "  updated_at           TEXT NOT NULL"
        ")"
    )
    conn.executescript(SCHEMA_V18_PATH.read_text(encoding="utf-8"))
    conn.executescript(SCHEMA_V19_PATH.read_text(encoding="utf-8"))
    conn.execute(
        "UPDATE guided_study_sessions AS guided SET history_session_id = ("
        "SELECT history.id FROM study_sessions AS history "
        "WHERE history.occurred_at = guided.started_at "
        "AND history.duration_minutes = guided.duration_minutes "
        "ORDER BY history.id DESC LIMIT 1"
        ") WHERE guided.status = 'completed' AND guided.history_session_id IS NULL"
    )
    if added_active_seconds:
        # Freeze a pre-v16 active session at its latest supported activity.
        # This prevents migration time spent away from Waypoint from becoming
        # synthetic study evidence while preserving work already observed.
        conn.execute(
            "UPDATE guided_study_sessions SET active_seconds = MAX(0, CAST(("
            "julianday(updated_at) - julianday(started_at)) * 86400 AS INTEGER)), "
            "tracking_state = 'paused', resumed_at = NULL "
            "WHERE status = 'active'"
        )
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def get_schema_version(conn):
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return row["value"] if row else None
