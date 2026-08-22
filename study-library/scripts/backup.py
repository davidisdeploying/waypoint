#!/usr/bin/env python3
"""Create and verify an online SQLite backup for Study Library."""

import argparse
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def verify(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("books", "sections", "diagnostic_scopes", "question_bank")
        }
    finally:
        conn.close()
    if quick_check != "ok" or foreign_keys:
        raise RuntimeError(
            f"backup verification failed: quick_check={quick_check!r}, "
            f"foreign_key_violations={len(foreign_keys)}"
        )
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        default=os.environ.get(
            "STUDY_LIBRARY_DB",
            str(Path(__file__).resolve().parent.parent / "data" / "study_library.db"),
        ),
    )
    parser.add_argument(
        "--backup-dir",
        default=os.environ.get(
            "STUDY_LIBRARY_BACKUP_DIR",
            str(Path(__file__).resolve().parent.parent / "data" / "backups"),
        ),
    )
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()

    source_path = Path(args.database).resolve()
    backup_dir = Path(args.backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_path = backup_dir / f"study_library-{stamp}.db"

    fd, temp_name = tempfile.mkstemp(
        prefix=".study-library-backup-", suffix=".db", dir=backup_dir
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        source = sqlite3.connect(str(source_path))
        destination = sqlite3.connect(str(temp_path))
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        counts = verify(temp_path)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, final_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    backups = sorted(backup_dir.glob("study_library-*.db"), reverse=True)
    for old_path in backups[max(args.keep, 1):]:
        old_path.unlink()

    print(
        json.dumps(
            {
                "status": "ok",
                "backup": str(final_path),
                "quick_check": "ok",
                "foreign_key_violations": 0,
                "counts": counts,
                "retained": min(len(backups), max(args.keep, 1)),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
