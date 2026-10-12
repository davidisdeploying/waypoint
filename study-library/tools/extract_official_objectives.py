#!/usr/bin/env python3
"""Extract governed objective descriptions from a pinned vendor PDF."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber

from lib.official_objectives import parse_layout_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--codes", required=True, help="Comma-separated objective codes")
    args = parser.parse_args()

    observed = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    if observed != args.expected_sha256:
        raise SystemExit(
            f"PDF hash mismatch: expected {args.expected_sha256}, observed {observed}"
        )
    with pdfplumber.open(args.pdf) as pdf:
        text = "\n\f\n".join(
            page.extract_text(layout=True) or "" for page in pdf.pages
        )
    objectives = parse_layout_text(
        text,
        [code.strip() for code in args.codes.split(",") if code.strip()],
    )
    print(json.dumps(objectives, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
