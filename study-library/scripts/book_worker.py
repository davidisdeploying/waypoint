#!/usr/bin/env python3
"""Run durable book conversion/indexing jobs serially."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.ingest import ingest_book, seed_certification_and_exams
from lib import db, jobs

DEFAULT_CONVERTER = (
    "/home/david/Vaults/career-vault/files/2026/2026-07-29/"
    "codex-epub-converter-v2/epub_to_ai_markdown.py"
)


def _inside(path, root):
    resolved = Path(path).resolve()
    allowed = Path(root).resolve()
    if resolved == allowed or allowed not in resolved.parents:
        raise ValueError(f"path is outside allowed root: {allowed}")
    return resolved


def run_job(conn, job):
    input_root = os.environ.get("BOOK_JOB_INPUT_ROOT", "/home/david/Vaults/career-vault/files")
    output_root = os.environ.get("BOOK_JOB_OUTPUT_ROOT", input_root)
    converter = Path(os.environ.get("BOOK_CONVERTER_PATH", DEFAULT_CONVERTER)).resolve()
    source = _inside(job["source_path"], input_root)
    output = _inside(job["output_path"], output_root)
    if job["kind"] == "convert_index":
        if source.suffix.lower() != ".epub" or not source.is_file():
            raise ValueError("source must be an existing EPUB")
        if output.exists():
            raise ValueError("output path already exists")
        subprocess.run(
            [
                sys.executable, str(converter), "--input", str(source),
                "--output", str(output), "--token", job["id"],
            ],
            check=True,
            timeout=3600,
        )
    elif not output.is_dir():
        raise ValueError("reindex output_path must be an existing conversion directory")

    jobs.transition(
        conn, job["id"], "indexing", "indexing",
        "Loading verified Markdown into SQLite FTS5.",
    )
    _cert_id, exam_ids = seed_certification_and_exams(conn)
    result = ingest_book(
        conn,
        {
            "slug": job["book_slug"],
            "title_hint": job["book_slug"],
            "kind": job["book_kind"],
            "dir": str(output),
        },
        exam_ids,
    )
    return jobs.transition(
        conn, job["id"], "succeeded", "ready",
        "Conversion and search indexing completed.", result=result,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5)
    args = parser.parse_args()
    conn = db.connect()
    db.init_db(conn)
    try:
        while True:
            job = jobs.claim_next(conn)
            if job:
                try:
                    run_job(conn, job)
                except Exception as exc:
                    jobs.transition(
                        conn, job["id"], "failed", "failed",
                        "The book job failed; source data was not deleted.",
                        error=f"{type(exc).__name__}: {exc}",
                    )
            if args.once:
                break
            time.sleep(max(1, args.poll_seconds))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
