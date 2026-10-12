# Waypoint

Waypoint is a self-hosted study and credential workspace. It connects
certification and degree milestones to the detailed learning evidence held by
its Study Library engine, so "what should I study next" is answered from
recorded progress rather than from a static plan.

It is built and installed for a single operator, but the architecture is the
part worth reading: a small, durable milestone store paired with a separate
corpus-and-coaching engine, joined by a versioned proxy behind one
authenticated origin.

## Running this

Two components that ship together: a React + TypeScript PWA at the repository
root, and the Study Library backend under `study-library/`.

```sh
cd frontend && npm ci && npm run build && cd ..
python3 ops/server.py                    # PWA + state API + bounded proxy
cd study-library && python3 app.py       # Study Engine
```

Tests:

```sh
python3 -m unittest discover -s tests             # 13
cd study-library && python3 -m unittest discover -s tests   # 219
```

Deployment-specific paths are environment variables with home-relative
defaults, so nothing assumes a particular user:

| Key | What it is |
|---|---|
| `STUDY_LIBRARY_PATH` | the Study Library working tree |
| `STUDY_LIBRARY_EPUB_ROOT` | where source EPUBs live |
| `STUDY_COACH_CLAUDE_BIN` | Claude CLI used by the coach |

Runtime state (`data/`, `*.db`, `.venv-api/`) is gitignored — your progress,
scores and corpus are never repository content.

## Repository layout

This repository holds **both halves of the product**. They were separate
repositories until 2026-08-07 and were merged here as a subtree with full
history, because they had always shipped together — every feature landed as a
paired backend/frontend commit, and the runbook records paired HEADs and paired
rollback tags.

| Path | Component | Runs as |
|---|---|---|
| repository root | Waypoint PWA + same-origin gateway (`ops/server.py`) | `waypoint.service`, loopback `:8790` |
| `study-library/` | Study Library / Study Core backend, compiler, ingest, MCP surface | `study-library.service` `:8840`, `study-core-canary.service` `:8841`, `study-book-worker.service` |

Both components run on **alpha** and are reached only over loopback; the public
origin is the edge Cloudflare tunnel in front of Cloudflare Access. Unit
files live beside their own component — `ops/` for Waypoint, `study-library/ops/`
for the backend. Each component keeps its own `.gitignore`, so runtime state
(`data/`, `*.db`, `.venv-api/`) stays untracked.

## Product architecture

Waypoint is a React + TypeScript PWA served at `/v2/`; root and historical
browser routes redirect into that single production interface. The earlier
single-file shell remains in Git history and rollback tags, not in the active
user path. See `docs/ARCHITECTURE-V2.md`.

- **Waypoint app shell:** responsive routes for Today, Study,
  Library, Journey, and More. A service worker supplies an offline-readable
  shell and detects updates.
- **App identity:** `assets/brand/waypoint-mark.svg` is the canonical mark.
  Light Apple touch and PWA icons render it on an opaque white field.
  `assets/brand/waypoint-app-icon-dark.svg` is the derived dark appearance:
  the same geometry with a white ring, red core, and opaque ink field.
  Safari receives the appearance-matched touch icon when the app is installed,
  plus ICO, PNG, and SVG favicon fallbacks for tabs and bookmarks.
- **Milestone state:** validated singleton state in SQLite with
  optimistic revisions. Existing browser-local state is migrated once; an
  IndexedDB snapshot remains available for offline reading. Mutations pause
  while offline to avoid silent conflicts.
- **Study Engine (`study-library/`):** Study Library remains canonical for tasks,
  diagnostic gaps, citations, practice evidence, adaptive curriculum, and the
  subscription-backed Study Coach. Daily Study Sessions are resumable and
  automatically collect supported activity into a recap and progress record.
  Its shared six-certification spine, ten-gate readiness model, protected
  28-day finish line, and hash-guarded Career claim bridge keep official scope,
  learning proof, career relevance, and scheduling pressure separate.
- **Private ingress:** Cloudflare Access protects one public origin. Waypoint
  proxies bounded Study Engine routes, so the product does not expose its
  internal host split or require wildcard CORS.

This separation is intentional: milestone tracking is small and durable,
whereas corpus retrieval and coaching have different compute, data, and failure
characteristics. The UI can evolve independently while those contracts remain
versioned.

## Operations

- Origin: `http://127.0.0.1:8790` on Alpha
- Production: `https://waypoint.example.com`
- Study Engine gateway: `/api/v2/study/`
- App state: `data/waypoint.db`
- Verified backups: `data/backups/` via `waypoint-backup.timer`
- NAS/GPU use on Waypoint: none

`ops/server.py` serves real app routes, the state API, and the bounded Study
Library proxy. `ops/waypoint.service` and the backup timer are user units.

## Validation

Run:

```sh
cd frontend
./node_modules/.bin/tsc -b --pretty false
./node_modules/.bin/vitest run
./node_modules/.bin/vite build
cd ..
python3 -m unittest discover -s tests -v
WAYPOINT_ALLOW_DIRTY=1 python3 tests/check_integration.py
node --check sw.js
```

The deployment procedure creates a rollback tag, installs the user units,
restarts Waypoint, and verifies the origin plus the Access boundary. Repository
publication or a GitHub push is a separate decision.
