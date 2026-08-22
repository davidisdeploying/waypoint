# Design notes / boundaries / future work

## What this is

A single-user, local-only reference implementation of "book conversions →
searchable study database → study plan + progress tracking", scoped to the
three A+ v2 markdown exports available today. The architecture (ingest →
SQLite+FTS5 → stdlib HTTP API → static UI) is meant to generalize to future
EPUB conversions and certifications (Network+, Security+, Cloud+, CCNA
Automation, ISC2 CCSP), not just A+.

## Deliberate scope boundaries (out of this build)

- **No image/diagram extraction.** Source markdown already collapses images
  to `[Image: ...]` alt-text-style descriptions; this app ingests that text
  as-is and does not attempt OCR, image storage, or diagram parsing.
- **No structured table capture.** Tables in the source markdown are ingested
  as plain body text like everything else; there is no special table model.
- **No official objective import.** Objective codes/descriptions are extracted
  from the books' own inline markers (see README "Ingest"), not from
  CompTIA's published exam objectives PDF. Confidence scores and
  `provenance` strings on `objectives`/`domains` make this explicit everywhere
  it surfaces (API and UI).
- **No cross-book dedupe/conflict resolution beyond upsert-by-key.** If two
  books describe the same objective code slightly differently, the ingest
  upsert keeps the *higher-confidence* description and links sections from
  *both* books as evidence — it does not attempt semantic merging.
- **No held-out question *generation*.** The `held_out` boolean on
  `practice_attempts` is a user-supplied marker (e.g. "I hadn't seen these
  questions before") used only to exclude that attempt from the recent-average
  and weak-objectives metrics; nothing in this app generates novel questions.
  The separate adaptive-diagnostics `question_bank` (below) is entirely
  *imported*, never generated, for the same reason.
- **No labs/PBQs content.** Plan weeks seed a generic "hands-on" task
  scaffold per domain; there is no lab content, VM orchestration, or
  performance-based-question engine.
- **No embeddings / MCP / semantic search.** Search is SQLite FTS5
  (porter+unicode61 tokenizer, bm25 ranking) — good recall for exact/stemmed
  terms, no semantic nearest-neighbor search.
- **No multi-user auth, no TLS, no remote exposure** — see README "Privacy /
  auth / deployment boundary".

## Adaptive knowledge checks: design boundaries

- **Domain-level evidence only, by construction.** `question_bank.objective_id`
  is `NULL` and `mapping_granularity` is `'domain'` for every imported row —
  not a display-layer choice but a schema-level fact, because the practice-
  test book supports reliable chapter→domain mapping (each question chapter
  pairs 1:1 with a named domain-titled explanation chapter) but *not* reliable
  question→exact-CompTIA-objective mapping. A domain "pass" is never copied
  onto individual objectives. The Objective Mastery Map shows it only as a
  separate domain signal. Individual objective status changes only from
  objective-linked practice, completed linked tasks, or opened cited sections.
- **Structural parsing invariant over heuristic punctuation.** The importer
  (`ingest/diagnostics_importer.py`) hard-codes "every question has exactly 4
  numbered options" because that was verified against the *entire* real
  corpus (1,379 questions, zero structural anomalies) before being trusted —
  it does not guess stem-vs-option boundaries from punctuation (many stems
  don't end in `?`, ruling out that heuristic outright).
- **Two-pass answer matching, not lockstep sequential scanning.** Explanation
  paragraphs are indexed by their own captured number (first occurrence that
  carries a letter grade wins), rather than scanned in strict "expect N next"
  order. A lockstep scan is vulnerable to a short numbered how-to list
  embedded in one explanation's prose coincidentally carrying the same number
  as a later question's genuinely-unparseable answer — verified as a real
  defect during this build (an early version of the importer mis-flagged 9
  real answers as unparseable in chapter 7 alone due to exactly this
  collision; the two-pass rewrite recovered all 9).
- **Exclusion over guessing.** Figure-dependent questions (detected via
  stem/option phrase matching: "shown here", "following image", etc.) and
  questions whose answer paragraph has no parseable letter grade are
  imported as inactive audit rows, never surfaced in a real attempt. This
  book's markdown conversion drops the images entirely (no alt-text even),
  so there is no safe way to answer these without the source figure.
- **Exemption is not completion.** A passed check writes to the separate
  `plan_task_exemptions` audit table; it never sets `plan_tasks.completed`.
  This distinction is load-bearing for the export snapshot and dashboard —
  both must be able to tell "the user did this" from "a diagnostic said they
  already know this" without conflating the two.
- **No LLM anywhere in the diagnostics path.** Remediation packets
  (`lib/remediation.py`) use FTS5 retrieval plus fixed string templates for
  the recall prompt and lab-scaffold suggestion — deterministic and fully
  auditable, consistent with the rest of this app's no-network-calls stance.

## Why these choices

- **stdlib-only.** The task requires this to run without any downloads: no
  pip installs, no Flask/FastAPI, no ORM, no JS framework/bundler. `http.server`
  + vanilla JS keeps the whole stack auditable and dependency-free.
- **SQLite as the sole runtime derivative.** The ingested markdown/JSON stays
  untouched on disk; `data/study_library.db` is fully rebuildable from it via
  `cli.py rebuild`. Corpus content is never copied into the git repo.
- **Stable IDs over row IDs for citations.** `sections.stable_id` (e.g.
  `aplus-core-guide:0014`) is deterministic from `(book slug, position)`, so
  citations in search results / Waypoint summaries stay meaningful even if the
  DB is rebuilt (row `id` values would not).
- **Confidence-scored, provenance-carrying objectives/domains** rather than a
  single boolean "is this objective real" — because the underlying extraction
  genuinely has two different reliability tiers (self-labeled vs.
  divider-inferred), collapsing that distinction would overstate certainty.
- **A labeled heuristic instead of a single "AI confidence" number** for
  readiness — the task explicitly calls out not to fabricate a fake single
  confidence score; showing the three contributing percentages next to the
  label lets the user judge for themselves rather than trusting an opaque
  number.

## Next phases (not built here)

1. Official CompTIA objectives-document import as a second, higher-confidence
   objective source, reconciled against the current book-derived rows.
2. Table/diagram-aware ingestion once the converter emits structured table
   data instead of prose descriptions.
3. A real lab/PBQ content model instead of the generic scaffold task.
4. ~~Held-out practice-question banks with actual question content and answer
   tracking~~ — done for the adaptive-diagnostics `question_bank` (per-
   question detail, confidence, correctness all tracked in
   `diagnostic_responses`). `practice_attempts` (the older, manually-logged
   score/total metric) is intentionally left as-is; unifying the two would be
   a separate, larger migration.
   Remaining future work in this area: official CompTIA objectives-document
   import to upgrade `question_bank.mapping_granularity` from `'domain'` to
   `'objective'` for at least some questions (see item 1 below, same
   dependency), and a real PBQ/lab validation path distinct from this
   multiple-choice diagnostic — passing a knowledge check here should never
   be conflated with hands-on-verified readiness.
5. Optional local embeddings index (still no network calls) to complement
   FTS5 for "find conceptually similar sections" search.
6. Extending `ingest/sources.py` to additional certifications once their v2
   exports exist, reusing the same schema (it is already certification-
   agnostic aside from the A+-specific seed data in `ingest/ingest.py` and
   `ingest/plan.py`).
7. A real auth/reverse-proxy layer if this ever needs to be reachable from
   more than one device.
