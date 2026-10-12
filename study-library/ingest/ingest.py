"""Deterministic, idempotent ingest of the Localworker v2 markdown book exports.

Re-running ingest_all() over unchanged sources must not duplicate or drift any
row: books/sections are upserted on stable natural keys (slug, book+position),
objectives are upserted on (exam, code) and only gain confidence/domain info,
never lose it, and the study plan is seeded once (idempotent by slug).
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ingest.adapters import build_parser_adapter
from lib import parsing


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def seed_certification_and_exams(conn, manifest):
    """Seed the certification spine declared by a governed manifest."""
    ts = now_iso()
    certification_code = manifest["certification_code"]
    certification_name = manifest["certification_name"]
    conn.execute(
        "INSERT INTO certifications(code, name, sequence_order, created_at, updated_at) "
        "VALUES (?, ?, 1, ?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at",
        (certification_code, certification_name, ts, ts),
    )
    cert_id = conn.execute(
        "SELECT id FROM certifications WHERE code = ?", (certification_code,)
    ).fetchone()["id"]

    exam_ids = {}
    for sequence_order, exam in enumerate(manifest["exams"], start=1):
        conn.execute(
            "INSERT INTO exams(certification_id, code, name, sequence_order, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(certification_id, code) DO UPDATE SET "
            "name = excluded.name, sequence_order = excluded.sequence_order, updated_at = excluded.updated_at",
            (
                cert_id,
                exam["code"],
                exam["name"],
                exam.get("sequence_order", sequence_order),
                ts,
                ts,
            ),
        )
        exam_ids[exam["code"]] = conn.execute(
            "SELECT id FROM exams WHERE certification_id = ? AND code = ?",
            (cert_id, exam["code"]),
        ).fetchone()["id"]
    conn.commit()
    return cert_id, exam_ids


def _upsert_domain(conn, exam_id, code, name, provenance, confidence):
    ts = now_iso()
    conn.execute(
        "INSERT INTO domains(exam_id, code, name, provenance, confidence, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(exam_id, code) DO UPDATE SET "
        "  name = CASE WHEN excluded.confidence > domains.confidence THEN excluded.name ELSE domains.name END, "
        "  provenance = CASE WHEN excluded.confidence > domains.confidence THEN excluded.provenance ELSE domains.provenance END, "
        "  confidence = MAX(domains.confidence, excluded.confidence), "
        "  updated_at = excluded.updated_at",
        (exam_id, code, name, provenance, confidence, ts, ts),
    )
    return conn.execute(
        "SELECT id FROM domains WHERE exam_id = ? AND code = ?", (exam_id, code)
    ).fetchone()["id"]


def _upsert_objective(conn, exam_id, code, description, provenance, confidence, domain_id=None):
    ts = now_iso()
    conn.execute(
        "INSERT INTO objectives(exam_id, domain_id, code, description, provenance, confidence, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(exam_id, code) DO UPDATE SET "
        "  description = CASE WHEN excluded.confidence > objectives.confidence THEN excluded.description ELSE objectives.description END, "
        "  provenance = CASE WHEN excluded.confidence > objectives.confidence THEN excluded.provenance ELSE objectives.provenance END, "
        "  confidence = MAX(objectives.confidence, excluded.confidence), "
        "  domain_id = COALESCE(objectives.domain_id, excluded.domain_id), "
        "  updated_at = excluded.updated_at",
        (exam_id, domain_id, code, description, provenance, confidence, ts, ts),
    )
    return conn.execute(
        "SELECT id FROM objectives WHERE exam_id = ? AND code = ?", (exam_id, code)
    ).fetchone()["id"]


def _link_objective_to_section(conn, objective_id, section_id, book_id, snippet):
    ts = now_iso()
    conn.execute(
        "INSERT INTO objective_chunk_links(objective_id, section_id, book_id, snippet, created_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(objective_id, section_id) DO UPDATE SET snippet = excluded.snippet",
        (objective_id, section_id, book_id, snippet[:400], ts),
    )


def ingest_book(conn, source, exam_ids):
    """Ingest one v2 book directory. Returns a stats dict."""
    src_dir = Path(source["dir"])
    index_path = src_dir / "INDEX.md"
    report_path = src_dir / "conversion-report.json"
    if not index_path.is_file() or not report_path.is_file():
        raise FileNotFoundError(f"missing INDEX.md/conversion-report.json under {src_dir}")

    index_meta, _ = parsing.parse_frontmatter(index_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    sections = sorted(report["sections"], key=lambda s: s["position"])

    ts = now_iso()
    slug = source["slug"]
    title = index_meta.get("title") or report.get("title") or source.get("title_hint", slug)
    corpus_sha256 = sha256_bytes(
        "|".join(s.get("sha256", "") for s in sections).encode("utf-8")
    )

    conn.execute(
        "INSERT INTO books(slug, title, creator, language, source_dir, source_epub_sha256, "
        "converter_version, generated_by, section_count, total_words, corpus_sha256, "
        "ingested_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(slug) DO UPDATE SET "
        "  title=excluded.title, creator=excluded.creator, language=excluded.language, "
        "  source_dir=excluded.source_dir, source_epub_sha256=excluded.source_epub_sha256, "
        "  converter_version=excluded.converter_version, generated_by=excluded.generated_by, "
        "  section_count=excluded.section_count, total_words=excluded.total_words, "
        "  corpus_sha256=excluded.corpus_sha256, ingested_at=excluded.ingested_at, "
        "  updated_at=excluded.updated_at",
        (
            slug, title, index_meta.get("creator"), index_meta.get("language"),
            str(src_dir), index_meta.get("source_epub_sha256"),
            index_meta.get("converter_version"), index_meta.get("generated_by"),
            len(sections), report.get("total_words", 0), corpus_sha256,
            ts, ts, ts,
        ),
    )
    book_id = conn.execute("SELECT id FROM books WHERE slug = ?", (slug,)).fetchone()["id"]

    adapter = build_parser_adapter(
        source["parser"], slug, tuple(exam_ids)
    )
    domain_ids_by_code = {}
    stats = {"sections": 0, "objectives": 0, "links": 0, "domains": 0}

    for sec in sections:
        file_path = src_dir / sec["file"]
        raw = file_path.read_bytes()
        text = raw.decode("utf-8")
        _meta, body = parsing.parse_frontmatter(text)
        content_sha256 = sha256_bytes(raw)
        stable_id = f"{slug}:{sec['position']:04d}"

        conn.execute(
            "INSERT INTO sections(stable_id, book_id, position, source_position, part, part_count, "
            "title, source_item, source_path, word_count, content, content_sha256, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(book_id, position) DO UPDATE SET "
            "  stable_id=excluded.stable_id, title=excluded.title, source_item=excluded.source_item, "
            "  source_path=excluded.source_path, word_count=excluded.word_count, content=excluded.content, "
            "  content_sha256=excluded.content_sha256, updated_at=excluded.updated_at",
            (
                stable_id, book_id, sec["position"], sec.get("source_position"),
                sec.get("part"), sec.get("part_count"), sec["title"], sec.get("source_item"),
                sec["file"], sec.get("words", 0), body, content_sha256, ts, ts,
            ),
        )
        section_id = conn.execute(
            "SELECT id FROM sections WHERE book_id = ? AND position = ?", (book_id, sec["position"])
        ).fetchone()["id"]
        stats["sections"] += 1

        parsed = adapter.consume(sec["title"], body)
        for domain in parsed.domains:
            exam_id = exam_ids.get(domain.exam_code)
            if not exam_id:
                continue
            key = (domain.exam_code, domain.code)
            if key not in domain_ids_by_code:
                domain_ids_by_code[key] = _upsert_domain(
                    conn, exam_id, domain.code, domain.name,
                    domain.provenance, domain.confidence,
                )
                stats["domains"] += 1

        for hit in parsed.objectives:
            exam_id = exam_ids.get(hit.exam_code)
            if not exam_id:
                continue
            major = hit.code.split(".")[0]
            domain_id = domain_ids_by_code.get((hit.exam_code, major))
            objective_id = _upsert_objective(
                conn, exam_id, hit.code, hit.description,
                hit.provenance, hit.confidence, domain_id,
            )
            _link_objective_to_section(
                conn, objective_id, section_id, book_id, hit.description
            )
            stats["objectives"] += 1
            stats["links"] += 1

    conn.commit()
    return {
        "book_id": book_id,
        "slug": slug,
        "parser": source["parser"],
        **stats,
    }


def ingest_all(conn, sources, manifest=None):
    if manifest is None:
        from lib.compiler import load_manifest
        manifest = load_manifest()
    _cert_id, exam_ids = seed_certification_and_exams(conn, manifest)
    results = []
    for source in sources:
        results.append(ingest_book(conn, source, exam_ids))
    return results
