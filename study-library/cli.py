#!/usr/bin/env python3
"""Study Library CLI: init, ingest, rebuild, stats."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import compiler, db, diagnostics, source_verifier
from lib.api_logic import (
    get_adaptive_curriculum,
    get_ai_context,
    get_progress_summary,
    get_waypoint_summary,
)
from ingest.ingest import ingest_all
from ingest.plan import seed_plan
from ingest.sources import get_sources
from ingest.diagnostics_importer import import_questions, seed_diagnostic_scopes


def cmd_init(args):
    conn = db.connect()
    db.init_db(conn)
    print(f"Initialized schema (version {db.get_schema_version(conn)}) at {db.db_path()}")
    conn.close()


def cmd_ingest(args):
    conn = db.connect()
    db.init_db(conn)
    manifest = compiler.load_manifest(args.manifest)
    active_build = conn.execute(
        "SELECT b.id FROM certification_pack_active_builds a "
        "JOIN certification_pack_builds b ON b.id = a.build_id "
        "JOIN certifications c ON c.id = a.certification_id "
        "WHERE c.code = ?",
        (manifest["certification_code"],),
    ).fetchone()
    if active_build:
        conn.close()
        raise SystemExit(
            "refusing to mutate sources for a certification with a published "
            "pack; rehearse ingestion in a database copy and create a new "
            "revisioned-source migration"
        )
    results = ingest_all(conn, get_sources(manifest), manifest)
    for r in results:
        print(f"  {r['slug']}: {r['sections']} sections, {r['objectives']} objective hits, "
              f"{r['links']} links, {r['domains']} domains touched")
    if manifest["certification_code"] == "aplus":
        plan_stats = seed_plan(conn)
        print(f"  study plan: {plan_stats['weeks']} weeks, {plan_stats['tasks']} tasks created")
        q_stats = import_questions(conn)
        print(f"  diagnostics questions: {q_stats['imported']} imported, "
              f"{q_stats['requires_figure']} figure-dependent (excluded), "
              f"{q_stats['skipped']} total skipped, reasons={q_stats['skip_reasons']}")
        scope_stats = seed_diagnostic_scopes(conn)
        print(f"  diagnostic scopes: {scope_stats['domain_scopes']} domain, "
              f"{scope_stats['composite_scopes']} composite")
    else:
        print("  study plan and diagnostic seeders: not configured for this certification")
    pack = compiler.compile_pack(conn, args.manifest)
    print(
        f"  certification pack: {pack['pack_version']} {pack['status']}, "
        f"{pack['covered_objectives']}/{pack['objectives']} objectives covered, "
        f"{pack['quarantined_sources']} sources quarantined"
    )
    conn.close()


def cmd_rebuild(args):
    path = db.db_path()
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    print(f"Removed {path} (and WAL/SHM sidecars if present).")
    cmd_init(args)
    cmd_ingest(args)


def cmd_stats(args):
    conn = db.connect()
    tables = [
        "books", "sections", "certifications", "exams", "domains", "objectives",
        "objective_chunk_links", "study_plans", "plan_weeks", "plan_tasks",
        "study_sessions", "practice_attempts", "objective_mastery",
        "diagnostic_scopes", "question_bank", "diagnostic_attempts",
        "diagnostic_responses", "remediation_items", "remediation_readings",
        "scope_mastery", "plan_task_exemptions", "objective_dossiers",
        "certification_pack_builds", "certification_pack_active_builds",
    ]
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        print(f"  {t}: {n}")
    conn.close()


def cmd_waypoint_summary(args):
    conn = db.connect()
    db.init_db(conn)
    summary = get_waypoint_summary(conn, args.base_url)
    conn.close()
    payload = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if not args.output:
        print(payload, end="")
        return
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(output)
    print(f"Wrote Waypoint summary schema {summary['schema_version']} to {output}")


def _print_json(payload):
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_progress(args):
    conn = db.connect()
    db.init_db(conn)
    payload = get_progress_summary(conn)
    conn.close()
    _print_json(payload)


def cmd_adaptive_plan(args):
    conn = db.connect()
    db.init_db(conn)
    payload = get_adaptive_curriculum(
        conn, days=args.days, minutes_per_day=args.minutes_per_day
    )
    conn.close()
    _print_json(payload)


def cmd_ai_context(args):
    conn = db.connect()
    db.init_db(conn)
    payload = get_ai_context(
        conn,
        query=args.query,
        exam=args.exam,
        limit=args.limit,
        max_chars=args.max_chars,
        days=args.days,
        minutes_per_day=args.minutes_per_day,
    )
    conn.close()
    _print_json(payload)


def cmd_refresh_remediation(args):
    conn = db.connect()
    db.init_db(conn)
    payload = diagnostics.refresh_remediation_readings(
        conn, attempt_id=args.attempt, open_only=not args.include_reviewed
    )
    conn.close()
    _print_json(payload)


def cmd_compile_pack(args):
    conn = db.connect()
    db.init_db(conn)
    payload = compiler.preview_pack(conn, args.manifest)
    conn.close()
    _print_json(payload)


def cmd_publish_pack(args):
    conn = db.connect()
    db.init_db(conn)
    payload = compiler.publish_pack(conn, args.build_id, args.manifest)
    conn.close()
    _print_json(payload)


def cmd_verify_sources(args):
    conn = db.connect()
    db.init_db(conn)
    payload = source_verifier.verify_official_sources(
        conn, args.manifest, timeout=args.timeout
    )
    conn.close()
    _print_json(payload)
    return 0 if payload["status"] == "match" else 2


def cmd_verify_spines(args):
    payload = source_verifier.verify_spine_sources(
        certification_id=args.certification, timeout=args.timeout
    )
    _print_json(payload)
    return 0 if payload["status"] == "match" else 2


def main():
    parser = argparse.ArgumentParser(description="Study Library CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize the schema").set_defaults(func=cmd_init)
    ingest = sub.add_parser(
        "ingest", help="Ingest books declared by a certification manifest"
    )
    ingest.add_argument("--manifest", help="Certification manifest JSON")
    ingest.set_defaults(func=cmd_ingest)
    rebuild = sub.add_parser(
        "rebuild", help="Delete and recreate the DB, then ingest a manifest"
    )
    rebuild.add_argument("--manifest", help="Certification manifest JSON")
    rebuild.set_defaults(func=cmd_rebuild)
    sub.add_parser("stats", help="Print row counts per table").set_defaults(func=cmd_stats)
    waypoint = sub.add_parser(
        "waypoint-summary",
        help="Print or atomically write the versioned Waypoint summary JSON",
    )
    waypoint.add_argument(
        "--base-url",
        default="http://127.0.0.1:8840",
        help="Study Library URL placed in the summary (default: %(default)s)",
    )
    waypoint.add_argument(
        "--output",
        help="Destination JSON file; omit to print the summary to stdout",
    )
    waypoint.set_defaults(func=cmd_waypoint_summary)
    sub.add_parser(
        "progress",
        help="Print the canonical progress evidence used by Waypoint",
    ).set_defaults(func=cmd_progress)
    adaptive = sub.add_parser(
        "adaptive-plan",
        help="Print a short-horizon curriculum derived from current evidence",
    )
    adaptive.add_argument("--days", type=int, default=7)
    adaptive.add_argument("--minutes-per-day", type=int, default=45)
    adaptive.set_defaults(func=cmd_adaptive_plan)
    ai_context = sub.add_parser(
        "ai-context",
        help="Print a bounded, cited context packet for Codex or Claude",
    )
    ai_context.add_argument("--query", help="Optional FTS query for cited book excerpts")
    ai_context.add_argument("--exam", help="Optional exam code filter")
    ai_context.add_argument("--limit", type=int, default=5)
    ai_context.add_argument("--max-chars", type=int, default=12000)
    ai_context.add_argument("--days", type=int, default=7)
    ai_context.add_argument("--minutes-per-day", type=int, default=45)
    ai_context.set_defaults(func=cmd_ai_context)
    refresh = sub.add_parser(
        "refresh-remediation",
        help="Rebuild stored book citations with the current deterministic retriever",
    )
    refresh.add_argument("--attempt", type=int, help="Limit refresh to one attempt")
    refresh.add_argument(
        "--include-reviewed",
        action="store_true",
        help="Refresh reviewed gaps as well as open gaps",
    )
    refresh.set_defaults(func=cmd_refresh_remediation)
    compile_pack = sub.add_parser(
        "compile-pack",
        help="Create an immutable certification-pack preview without changing production",
    )
    compile_pack.add_argument(
        "--manifest",
        help="Certification manifest JSON (defaults to the current A+ V15 manifest)",
    )
    compile_pack.set_defaults(func=cmd_compile_pack)
    publish_pack = sub.add_parser(
        "publish-pack",
        help="Explicitly promote an unchanged reviewed pack preview",
    )
    publish_pack.add_argument("build_id", type=int)
    publish_pack.add_argument(
        "--manifest",
        help="Certification manifest JSON (defaults to the current A+ V15 manifest)",
    )
    publish_pack.set_defaults(func=cmd_publish_pack)
    verify_sources = sub.add_parser(
        "verify-sources",
        help="Hash live official vendor sources without changing trusted pins",
    )
    verify_sources.add_argument(
        "--manifest",
        help="Certification manifest JSON (defaults to the current A+ V15 manifest)",
    )
    verify_sources.add_argument("--timeout", type=int, default=30)
    verify_sources.set_defaults(func=cmd_verify_sources)
    verify_spines = sub.add_parser(
        "verify-spines",
        help="Hash pinned vendor documents in the shared certification registry",
    )
    verify_spines.add_argument(
        "--certification", help="Limit verification to one certification ID"
    )
    verify_spines.add_argument("--timeout", type=int, default=30)
    verify_spines.set_defaults(func=cmd_verify_spines)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
