"""Manifest-declared v2 source directories ingested into Study Library.

These are treated as immutable input; nothing here writes back to them.
Override for tests via the STUDY_LIBRARY_SOURCES_JSON env var (see tests/).
"""
import json
import os

def get_sources(manifest=None):
    """Ordered book sources to ingest. 'review' is ingested first so it can
    seed domains that the other two books' objectives link against."""
    override = os.environ.get("STUDY_LIBRARY_SOURCES_JSON")
    if override:
        sources = json.loads(override)
    else:
        if manifest is None:
            from lib.compiler import load_manifest
            manifest = load_manifest()
        sources = []
        for source in manifest["sources"]:
            ingest = source.get("ingest")
            if not ingest:
                continue
            sources.append({
                "slug": source["book_slug"],
                "title_hint": ingest.get("title_hint", source["title"]),
                "kind": ingest["kind"],
                "parser": ingest["parser"],
                "dir": ingest["dir"],
            })
    order = {"review": 0, "guide": 1, "practice": 2}
    return sorted(sources, key=lambda s: order.get(s["kind"], 99))
