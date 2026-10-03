# Waypoint 2.0 architecture

## Decision

Waypoint 2.0 is one private product with a thin edge and one modular study
core. It is not a fleet of public microservices.

```text
Safari / installed PWA
        |
Cloudflare Access and TLS
        |
Delta: static typed PWA + versioned gateway
        |
Tailscale + authenticated service request
        |
Charlie: modular Study Core + canonical SQLite + background jobs
```

## Product modules

- Today: next action, resumable daily session, automatic activity recap,
  progress, and current study evidence.
- Study: Study Next, Objective Mastery Map, curriculum, knowledge checks,
  remediation, practice, and Study Coach.
- Library: books, full-text search, sections, citations, and objectives.
- Journey: certifications, WGU milestone plan, target dates, and proof state.
- More: privacy, health, data export, install/update state, and architecture.

## Migration outcome and rules

1. Historical root routes redirect to the `/v2/` production shell. The old
   shell remains recoverable through Git rollback tags.
2. Existing databases remain available until each replacement passes data
   reconciliation and rollback tests.
3. Versioned gateway routes live under `/api/v2/`.
4. Study Core SQLite is canonical for learning evidence and the reconciled
   credential/degree milestone singleton.
6. No destructive migration is permitted. Every schema change is additive,
   backed up, reconciled, and reversible before cutover.
7. Practice questions remain excluded from teaching and Coach retrieval.
8. Domain-mapped practice results remain domain signals. Waypoint does not
   convert them into exact objective mastery. Objective status requires
   objective-linked study or assessment evidence.

## Technology

- React and TypeScript for component and state contracts.
- Vite for a static production build.
- TanStack Query for server-state lifecycle.
- Zod for runtime validation at API boundaries.
- FastAPI and Pydantic for the typed Study Core canary transport.
- SQLite, explicit SQL migrations, WAL, and FTS5 remain the data foundation.

React, Vite, and FastAPI are implementation tools, not domain boundaries.
Domain logic stays framework-independent and directly testable.
