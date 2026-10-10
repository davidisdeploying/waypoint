#!/usr/bin/env python3
"""Link admitted Markdown books to immutable EPUB files by SHA-256."""

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import db


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"EPUB root is not a directory: {root}")
    conn = db.connect(args.database)
    db.init_db(conn)
    needed = {
        row["source_epub_sha256"]: (row["id"], row["slug"])
        for row in conn.execute(
            "SELECT id, slug, source_epub_sha256 FROM books WHERE source_epub_sha256 IS NOT NULL"
        )
    }
    linked = set()
    for path in sorted(root.rglob("*.epub")):
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        digest = sha256_file(resolved)
        match = needed.get(digest)
        if not match:
            continue
        book_id, slug = match
        conn.execute(
            "UPDATE books SET source_epub_path = ?, updated_at = updated_at WHERE id = ?",
            (str(resolved), book_id),
        )
        linked.add(digest)
        print(f"linked {slug} sha256={digest[:12]} path={resolved}")
    conn.commit()
    missing = sorted(set(needed) - linked)
    conn.close()
    if missing:
        print("unresolved EPUB hashes: " + ", ".join(value[:12] for value in missing), file=sys.stderr)
        return 1
    print(f"linked_books={len(linked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
