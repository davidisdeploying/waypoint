#!/usr/bin/env python3
"""One-time, fail-closed import of a Waypoint state envelope."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import db, waypoint_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--migration-id", required=True)
    parser.add_argument("--expected-state-sha256", required=True)
    args = parser.parse_args()

    envelope = json.loads(Path(args.source).read_text(encoding="utf-8"))
    canonical = json.dumps(
        envelope.get("state"), sort_keys=True, separators=(",", ":")
    ).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != args.expected_state_sha256:
        raise SystemExit("source state SHA-256 mismatch")

    conn = db.connect()
    db.init_db(conn)
    try:
        result = waypoint_state.import_snapshot(conn, envelope, args.migration_id)
    finally:
        conn.close()
    print(json.dumps({
        "revision": result["revision"],
        "updated_at": result["updated_at"],
        "state_sha256": digest,
        "migration_id": result["migration_id"],
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
