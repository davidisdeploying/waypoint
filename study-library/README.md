# Study Library

A private, local-only learning system for a six-certification journey. A+ Core
1 and Core 2 are the first published curriculum; Network+, Security+, Cloud+,
CCNA Automation, and CCSP remain clearly labeled official-domain projections
until their governed content packs are compiled and published. See
`docs/LEARNING-ARCHITECTURE.md` for the five-engine contract.

This is a private single-user application. Study Library binds only to
Charlie's Tailscale address. Production Waypoint proxies it through the same
private Cloudflare Access boundary at
`https://waypoint.example.com/api/v2/study/`. Study Library remains the
only detailed progress database; Waypoint reads its summary and never
double-writes learning evidence.

## Architecture

```
study-library/
  app.py              rollback-compatible stdlib JSON API + static UI
  study_core/api.py   typed FastAPI transport (canary on port 8841)
  cli.py              init / ingest / rebuild / stats CLI
  mcp_server.py       read-only MCP stdio tools for Codex / Claude
  lib/
    db.py             SQLite connection + additive schema initialization
    parsing.py         frontmatter + objective-marker parsing
    api_logic.py        all read/write query logic (used by app.py and tests)
    diagnostics.py       adaptive knowledge-check assessment engine
    remediation.py       retrieval-backed gap-remediation packet builder
    daily_sessions.py    resumable session lifecycle, activity events, and recaps
  ingest/
    sources.py          the 3 configured v2 source directories
    ingest.py            idempotent ingest of books/sections/objectives
    plan.py              seeds the 12-week study plan scaffold
    diagnostics_importer.py  parses the practice-test question bank + seeds scopes
  db/
    schema.sql            base SQLite schema (FTS5 for full-text search)
    schema_v2.sql          additive schema for diagnostics (question bank, attempts, etc.)
    schema_v3.sql          canonical Waypoint milestone state
    schema_v4.sql          durable book-conversion jobs
    schema_v5.sql          daily sessions and bounded activity evidence
  static/                index.html, css/, js/ (no external assets)
  tests/                 unittest suite (schema, ingest, api_logic, diagnostics, remediation)
  scripts/smoke.py       starts the real server on an ephemeral port and hits it
  scripts/book_worker.py serial durable EPUB conversion + FTS5 indexing worker
  data/                  runtime SQLite DB (gitignored, created on first run)
```

Runtime data lives in `data/study_library.db` (WAL mode). The ingested
markdown/JSON source directories are **never modified** — the database is a
derived artifact that can always be rebuilt from them.

The default first view is **Study Next**, a derived queue that orders due
retention checks, focused remediation gaps, the current section's optional
knowledge check, and incomplete curriculum tasks. It creates no competing
progress state; every item is computed from the canonical SQLite evidence.

The same evidence also feeds a read-only adaptive curriculum and a bounded AI
context packet. These interfaces are deterministic retrieval infrastructure:
they do not call a model, generate unsupported facts, or modify study state.

Daily Study Sessions add a resumable active-session layer without replacing
the existing progress record. Supported Waypoint actions emit deduplicated
activity events while a session is active. Finishing the session writes a
human-readable recap and one ordinary `study_sessions` row, so the existing
streak and seven-day metrics continue to use a single source of truth.

## Setup / run

The converter, CLI, domain logic, and rollback transport require only Python
3.11+ stdlib. The FastAPI canary has a small pinned virtual environment:

```bash
cd ~/study-library
python3 -m venv .venv-api
.venv-api/bin/pip install -r requirements-api.txt
python3 cli.py init      # create the schema
python3 cli.py ingest    # ingest the 3 configured v2 book directories + seed the plan
python3 app.py           # serve on http://127.0.0.1:8840 (override via env, see below)
.venv-api/bin/uvicorn study_core.api:app --host 127.0.0.1 --port 8841
```

Then open `http://127.0.0.1:8840/` in a browser.

Environment variables (all optional):
- `STUDY_LIBRARY_DB` — path to the SQLite file (default `data/study_library.db`)
- `STUDY_LIBRARY_HOST` — bind host (default `127.0.0.1`)
- `STUDY_LIBRARY_PORT` — bind port (default `8840`)
- `STUDY_LIBRARY_FASTAPI_PORT` — canary ASGI port (default `8841`)
- `STUDY_LIBRARY_SERVICE_TOKEN_FILE` — file-backed credential required on
  non-health API requests in production

Book jobs are stored in SQLite and move through `queued → converting →
indexing → succeeded` (or `failed`) with timestamps and a bounded error. The
worker accepts inputs and outputs only below its configured career-vault
roots, never overwrites an existing output directory, and never deletes the
source EPUB. `GET /api/jobs` exposes current progress to Waypoint.

## Ingest / rebuild / stats

```bash
python3 cli.py ingest    # idempotent: re-running never duplicates rows
python3 cli.py rebuild   # deletes the DB file and re-runs init + ingest from scratch
python3 cli.py stats     # prints row counts per table
python3 cli.py progress  # canonical progress evidence used by Waypoint
python3 cli.py adaptive-plan --days 7 --minutes-per-day 45
python3 cli.py ai-context --query "subnet mask" --exam 220-1201
python3 cli.py verify-spines --certification aplus
```

Ingest reads `INDEX.md` (book-level frontmatter) and `conversion-report.json`
(authoritative section order/word counts/per-file SHA-256) from each of the
three source directories, then reads each chapter file, splits its frontmatter
from its body, computes a SHA-256 of the raw file bytes, and upserts rows keyed
on stable natural keys:
- `books.slug` (unique)
- `sections(book_id, position)` (unique), with a derived `stable_id` like
  `aplus-core-guide:0014`
- `objectives(exam_id, code)` (unique) — re-ingesting only ever *raises*
  confidence/fills in a missing domain link, never regresses or duplicates
- `objective_chunk_links(objective_id, section_id)` (unique)

Objective-code extraction is regex-based over the ingested text and is
intentionally conservative:
- The core guide book self-labels objectives inline, e.g. `✓ 1201-3.2 ...` —
  both the exam and the objective code come directly from the marker
  (confidence 0.9).
- The review guide and practice tests books use bare `✔ N.N ...` markers with
  no exam prefix; the exam is inferred from the nearest preceding "PART
  I/II ... 220-120X" divider chapter (confidence 0.6). This is a heuristic,
  not a verified mapping against CompTIA's official objectives document.
- Domains are seeded **only** from the review guide's chapter headings
  (`Chapter N <Domain Name>`), on the assumption that one review-guide chapter
  ≈ one exam domain. This is also a heuristic (confidence 0.6), stated as such
  in `objectives.provenance` / `domains.provenance` and surfaced in the
  Objectives view.

## Adaptive knowledge checks (diagnostics)

Optional, comprehensive multiple-choice knowledge checks before each
domain-focused curriculum week, built from the practice-test book's own
question bank — not generated, not LLM-written.

**Provenance and honesty boundaries (read before trusting a "pass"):**
- Questions are imported **only** from `aplus-practice-tests`, deterministically
  paired by sequential position within each chapter (question chapter "Chapter
  N" ↔ explanation chapter "Chapter N: <Domain Name>"). The importer validates
  a corpus-wide structural invariant (every question has exactly 4 numbered
  options) before trusting stem/option boundaries; see
  `ingest/diagnostics_importer.py` module docstring for the exact algorithm.
- Every imported question is **domain-level evidence only**:
  `question_bank.objective_id` is always `NULL` and `mapping_granularity` is
  always `'domain'`. The source book supports reliable chapter→domain mapping
  but not reliable question→exact-objective mapping, and this app never
  pretends otherwise in the API or UI. The Objective Mastery Map keeps the
  broad domain score beside the objective list, while each objective remains
  "not individually checked" until objective-linked evidence exists.
- Figure-dependent questions ("what's shown here...") and questions whose
  paired answer couldn't be parsed (no letter grade, out-of-range answer
  index, etc.) are imported as inactive audit rows (`active=0`,
  `requires_figure=1` where applicable) and are **never** selectable into a
  real attempt. `cli.py ingest` prints exact skip counts by reason.
- Passing a check marks **provisional** mastery
  (`scope_mastery.status = 'provisional_mastery'`, or
  `'mastered_after_remediation'` after a retest) with a 14-day retention
  check scheduled — never "exam readiness guaranteed."
- A passed check **exempts** that week's remaining incomplete broad plan
  tasks via `plan_task_exemptions` — it does **not** set
  `plan_tasks.completed = 1`. The UI/API always disclose exemption separately
  from completion (see `GET /api/plan`'s per-task `exemption_reason` field).
- A multiple-choice pass is explicitly **not** hands-on/lab validation; the UI
  states this on every results screen, and remediation's "lab scaffold" is
  labeled a suggestion, never an official PBQ.

**Scoring:** default scope samples up to 20 questions (or all available if
fewer; the scope is disabled entirely below 10 valid questions), without
repeats until the pool is exhausted (reuse is disclosed when it happens).
Raw score must be ≥85% to pass. Each answer's credit is then confidence-
adjusted (correct+high=1.0, correct+medium=0.9, correct+low=0.7,
incorrect=0), and that **effective** score must also be ≥80%. Any incorrectly
answered `critical` question (none from import today; reserved for future
curated items) fails the attempt regardless of thresholds. Remediation
("gap") items are created **only** for incorrect answers or correct-but-
low-confidence answers on a **failed** attempt — a passing attempt never
generates gap work, even if some answers were low-confidence.

**Remediation packets** (`lib/remediation.py`) retrieve up to 3 deduped,
bounded FTS5 excerpts from the guide/review books (**never** the practice-test
book itself), preferring domain-linked sections (via `objective_chunk_links`)
before falling back to a broader same-exam or unconstrained search — each
citation discloses which retrieval basis produced it. Each gap also gets one
deterministic active-recall prompt and one clearly-labeled hands-on scaffold
suggestion. No LLM is used anywhere in this path.

**Retest gating:** a fresh retest for a `needs_remediation` scope is blocked
until every open gap for that scope has been marked reviewed
(`POST /api/remediation/{id}`); the API returns 409 with an explanation if you
try earlier.

**Retention:** passing schedules `scope_mastery.retention_due_at` 14 days out.
A submitted retention check that fails returns the scope to
`needs_remediation` (gaps + retest gating apply again); a passing retention
check keeps the existing mastery label and just refreshes the due date.

### Diagnostics API

- `GET /api/diagnostics/scopes` — all scopes with mastery/gap-count summary
- `GET /api/diagnostics/scopes/{id}` — full scope detail incl. open gaps, recent attempts
- `POST /api/diagnostics/scopes/{id}/start` (`{mode: "diagnostic"|"retest"|"retention"}`)
- `GET /api/diagnostics/attempts/{id}` — redacts correct answers until submitted
- `POST /api/diagnostics/attempts/{id}/submit` (`{responses: [{question_id, selected, confidence}]}`) — one submission only, transactional
- `GET /api/diagnostics/attempts/{id}/results`
- `POST /api/remediation/{id}` — mark a gap reviewed

All diagnostics mutations use the same same-origin + CSRF protection as the
rest of the API (see "Privacy / auth" below).

## Study plan

`ingest/plan.py` seeds one 12-week relative scaffold (`aplus-12-week`): 6
weeks for Core 1, 6 for Core 2. Within each 6-week block, one week per
review-guide domain (Core 1 has 5 domains, Core 2 has 4 — Core 2's domains are
stretched across 5 weeks so no week is empty), plus a final review/practice
checkpoint week. Weeks are relative ("Week 1", "Week 2", ...) — there is no
committed calendar date. Each week seeds four tasks (reading, lab, recall,
practice); completing/re-running ingest does not touch tasks that already
exist for a week (so your checkoffs/notes survive a rebuild of the *plan*, but
note that `cli.py rebuild` deletes the whole DB including your progress — see
Backup/restore below).

## API

All endpoints are under `/api/`. Reads are `GET`; writes are `POST` with a
JSON body. See `lib/api_logic.py` for exact behavior; endpoints:

- `GET /api/health`
- `GET /api/csrf-token` — issues the per-process CSRF token the UI needs for writes
- `GET /api/dashboard`
- `GET /api/study-next?limit=` — derived priority queue, bounded to 12 items
- `GET /api/progress` — current-week, study-time, streak, domain, and practice evidence
- `GET /api/mastery-map?exam=` — Core 1/Core 2 objective groups, conservative
  objective status, separate domain diagnostic signals, and evidence counts
- `GET /api/adaptive-curriculum?days=&minutes_per_day=` — 1–14 day provisional plan
- `GET /api/readiness?exam=` — ten separate, explainable booking gates; no composite score
- `GET /api/certification-spines`, `GET /api/certification-spines/{id}` — six-cert scope registry
- `GET /api/career-context?certification=` — hash-guarded Career claim-ID bridge
- `GET /api/ai/context?q=&exam=&limit=&max_chars=&days=&minutes_per_day=` —
  bounded current state, open gaps, adaptive plan, and cited book excerpts
- `GET /api/books`
- `GET /api/search?q=&book=&exam=&limit=` — FTS5 full-text search, bounded to 50 results
- `GET /api/sections/{stable_id}`
- `GET /api/objectives?exam=`, `GET /api/objectives/{id}`
- `GET /api/plan`, `POST /api/plan/tasks/{id}` (`{completed, notes}`)
- `GET /api/sessions`, `POST /api/sessions` (`{occurred_at, duration_minutes, notes}`)
- `GET /api/attempts`, `POST /api/attempts` (`{exam_id, score, total, occurred_at, objective_id, notes, held_out}`)
- `GET /api/waypoint/summary` — see contract below
- `GET /api/export` — versioned JSON snapshot of the whole DB
- Diagnostics endpoints — see "Adaptive knowledge checks" above

### Waypoint summary contract

`GET /api/waypoint/summary` returns:

```
schema_version, generated_at, certification_id ("aplus"), certification_name,
current_exam, current_week, week_title, next_task, total_hours,
hours_last_7_days, completed_tasks, total_tasks, objective_coverage,
practice_average_recent, weak_objectives, readiness_label,
readiness_components, diagnostics, progress, adaptive_curriculum,
study_library_url, study_library_path
```

Every field is `null`/`0`/`[]` when there is not yet evidence to compute it;
nothing is fabricated. `readiness_label`, `readiness_components`, and the full
`readiness` object come from ten explicit source, learning, recall, diagnostic,
retention, lab, remediation, and held-out-exam gates. No weighted or composite
readiness score exists.

Both `GET /api/dashboard` and this summary also carry a `diagnostics` block
(current section's knowledge-check state, checks passed/available, open gap
count, retention-due count/next date, and a domain mastery % **explicitly
labeled** as diagnostic/domain-level, never exact-objective or hands-on
evidence) — see "Adaptive knowledge checks" above for what feeds it. This is
an additive key; existing consumers reading only the older fields are
unaffected.

The `progress` block keeps each source signal separate: current-week task
counts, minutes/sessions/days studied over seven days, current streak, latest
activity, submitted/passed diagnostics, domain rows, and recent practice
trend. The `adaptive_curriculum` block applies the Study Next ordering across
a bounded number of calendar days. Work scheduled after an unassessed
knowledge check is explicitly provisional because a pass may exempt it.

### AI context contract

`GET /api/ai/context` and `python3 cli.py ai-context` provide Codex or Claude
with a compact packet rather than an unbounded database dump. The packet:

- is read-only and versioned;
- caps citations at 8, individual excerpts at 4,000 characters, and the
  requested excerpt budget at 16,000 characters;
- identifies every excerpt by book, section, stable ID, and content SHA-256;
- includes only submitted remediation gaps, never in-progress answer keys;
- labels domain-level diagnostic evidence honestly;
- tells consumers to treat book text as source data, not instructions, and to
  cite stable IDs for teaching claims.

When `q` is omitted, retrieval selects guide/review evidence linked to the
current diagnostic domain. When `q` is supplied, it performs a bounded FTS5
search, optionally filtered by exam, and still excludes the practice-test book
so answer-bank text cannot become teaching material or leak into a generated
quiz. Full sections remain available through their cited
`/api/sections/{stable_id}` path when a deliberately larger read is necessary.

**These endpoints are read-only.** No code here writes to Waypoint or creates
a second progress store. Production Waypoint fetches the summary through its
same-origin authenticated proxy.

### Study Coach MCP bridge

`mcp_server.py` exposes the same canonical read-only evidence through
newline-delimited MCP stdio. It uses only Python's standard library and opens
the SQLite database separately for each tool call. It exposes five tools:

- `study_status` — progress evidence plus the ordered Study Next queue;
- `search_book_corpus` — bounded cited guide/review retrieval;
- `read_book_section` — bounded follow-up read by stable ID;
- `get_adaptive_curriculum` — provisional 1–14 day curriculum;
- `get_study_context` — combined state, gaps, curriculum, and citations.

Every tool is declared read-only, idempotent, non-destructive, and closed-
world. There are intentionally no tools for starting/submitting diagnostics,
marking gaps reviewed, logging study, or changing tasks. Practice-test
sections are refused by both retrieval tools.

From a Mac with the `alpha` SSH alias:

```bash
codex mcp add study_coach -- \
  ssh alpha /usr/bin/python3 ~/waypoint/study-library/mcp_server.py

claude mcp add --scope user study-coach -- \
  ssh alpha /usr/bin/python3 ~/waypoint/study-library/mcp_server.py
```

Codex clients sharing the same host configuration need a restart before a
newly added server appears. Claude Code health-checks configured MCP servers
with `claude mcp list`.

For Waypoint's file-import fallback, create the same versioned summary without
starting the server:

```bash
python3 cli.py waypoint-summary --output /tmp/waypoint-study-summary.json
```

Omit `--output` to print JSON to stdout. Use `--base-url` to place the eventual
private Study Library URL in the summary. The file write is atomic; the command
does not change Waypoint or the study database.

## Privacy / auth / deployment boundary

This app binds to `127.0.0.1` by default and has **no user accounts, no
transport encryption, and no real authorization** — it assumes it is the only
thing listening on that port on a single-user machine. Mutation endpoints
(`POST /api/...`) are protected with:
1. A same-origin check (the `Origin` header, when present, must match `Host`).
2. A per-process CSRF token, generated at startup and served via
   `GET /api/csrf-token`, required as `X-CSRF-Token` on every write.

This is **enough to stop a stray cross-site page from silently writing to
your local instance**, but it is **not** a real deployment security model. If
this is ever exposed beyond localhost, it needs a real reverse proxy with
authentication (and TLS) in front of it first.

The production service is co-located with Waypoint on Alpha. Study Library
listens only on `127.0.0.1:8840`; Waypoint is its sole consumer and reaches it
through the local loopback interface. Only Waypoint's same-origin proxy is
exposed, behind Cloudflare Access and TLS.

## Backup / restore / rollback

- The runtime DB is a single file: `data/study_library.db` (plus WAL/SHM
  sidecars while the server is running). To back it up, stop the server and
  copy that file. To restore, stop the server and replace it.
- The canary installs `study-library-backup.timer`. It uses SQLite's online
  backup API, verifies `quick_check` and foreign keys, keeps 14 daily backups
  in `data/backups/`, and does not require stopping the app.
- `GET /api/export` produces a versioned JSON snapshot (books, objectives,
  plan + task state, sessions, attempts, diagnostic scopes + attempts,
  waypoint summary) that can be kept as a portable backup independent of the
  SQLite file format. In-progress attempts in the export have their submitted
  answers/correctness redacted the same as the live API.
- `python3 cli.py rebuild` is a full reset: it deletes the DB file and
  re-creates it from the source markdown, which also re-seeds a fresh study
  plan (your task completions/notes, diagnostic attempts, mastery state, and
  remediation history are **not** preserved across a rebuild — export first
  if you want to keep them). `python3 cli.py ingest` (without `rebuild`) is
  additive/idempotent and never resets diagnostic mastery or attempt history.
- Rolling back this repo itself: it's a local git repo with one commit; `git
  log` / `git show` recover the state at any point, and since `data/` is
  gitignored, checking out an older commit never touches your runtime DB.

## Testing

```bash
python3 -m unittest discover -s tests -v   # unit tests against synthetic fixture books
python3 scripts/smoke.py                   # starts the real server on an ephemeral port,
                                            # ingests fixtures, and hits real HTTP routes
```

The unit tests build small synthetic "v2-format" source directories (see
`tests/fixtures.py`) rather than depending on the real vault corpus, so they
run anywhere. They cover: schema init/idempotency (including a v1→v2 upgrade
path that preserves pre-existing data), idempotent ingest (no duplicate rows
on re-ingest, exam/domain assignment, guide+review sections linking to the
*same* objective row), FTS5 search citations, plan-seeding idempotency,
mutation validation (`plan_tasks`, `sessions`, `attempts`), dashboard/
waypoint-summary null handling on an empty DB, and the export snapshot's
schema version.

Diagnostics-specific coverage (`tests/test_diagnostics_importer.py`,
`tests/test_diagnostics.py`, `tests/test_remediation.py`,
`tests/test_app_routes.py`): question/answer parser pairing and every skip
reason (figure-dependent, no-letter answer, missing answer, out-of-range
answer index) including an embedded-numbered-list-in-prose edge case that
could otherwise misalign the parser; idempotent question import against a
real ingested fixture; answer redaction before submit; scoring thresholds/
confidence-adjustment/multi-select/critical-item rules; transaction rollback
on malformed or incomplete submissions; remediation created only for
incorrect/low-confidence-correct responses on a failed attempt (never for a
passing one); retrieval citations excluding the practice book and deduped/
bounded; pass→plan-task-exemption without falsifying `completed`; the full
fail→review→retest and diagnostic→retention state machine, including unseen-
first question selection and disclosed reuse once a pool is exhausted; and a
live-server CSRF/same-origin smoke check over every diagnostics mutation
route.

## Future work

See `DESIGN.md` for boundaries and explicitly out-of-scope next phases (image/
diagram extraction, official objective import, held-out question generation,
labs/PBQs, embeddings/MCP, etc).
