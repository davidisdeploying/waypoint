#!/usr/bin/env python3
"""Create and verify a bounded online backup of Waypoint's SQLite state."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--retain", type=int, default=14)
    args = parser.parse_args()

    if not args.database.is_file():
        print("Waypoint database does not exist yet; nothing to back up.")
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = args.output_dir / f"waypoint-{timestamp}.db"

    with sqlite3.connect(args.database) as source, sqlite3.connect(destination) as target:
        source.backup(target)
        quick_check = target.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RuntimeError(f"backup quick_check failed: {quick_check}")
        row_count = target.execute("SELECT COUNT(*) FROM waypoint_state").fetchone()[0]

    backups = sorted(args.output_dir.glob("waypoint-*.db"), reverse=True)
    for old_backup in backups[max(args.retain, 1) :]:
        old_backup.unlink()

    print(
        f"backup={destination} sha256={sha256(destination)} "
        f"state_rows={row_count} quick_check=ok"
    )


if __name__ == "__main__":
    main()
