# Certification Knowledge Compiler

Study Core compiles each certification into a deterministic, versioned
knowledge pack before the study experience uses it.

## Authority policy

1. Official exam-objectives documents define the active exam codes, domains,
   weights, and objective identifiers.
2. Official vendor and standards documentation may validate time-sensitive
   facts, but cannot expand the exam scope.
3. Current-edition instructional books provide explanations and labs.
4. Review books provide the default focused lesson for an objective.
5. Practice-test books are assessment-only. They are never returned as
   instructional evidence.
6. AI can organize already-admitted, cited evidence. It cannot admit a source,
   change the official scope, resolve a conflict, or browse the open web during
   a study session.

## Build contract

Each manifest under `sources/certifications/` pins:

- certification and exam version;
- official document URL, document version, retrieval date, and SHA-256;
- the complete objective-code spine and domain weights;
- each book's source EPUB SHA-256, declared exam codes, source type, use role,
  whether it is required, and its deterministic parser adapter/directory;
- the allowlist of vendor hosts permitted for official-source verification.

The shared registry in `certification-spines-v1.json` defines the six-cert
journey before any individual pack is compiled. A production manifest binds
to `spine_registry_version`; bound manifests fail closed when their exams,
domain names or weights, official URL, or official hash differs from that
registry. Pre-registry manifests remain readable only as a migration bridge.

`python3 cli.py compile-pack --manifest <path>` applies the following gates
inside a rollback-only savepoint and stores an immutable preview:

- required official documents must have a URL, verification date, and pinned
  SHA-256;
- local book hashes must match the manifest;
- no source may name an exam outside the active pack;
- every official objective must exist in the ingested database;
- every objective must have active instructional coverage;
- assessment-only sources are excluded from lesson retrieval.

Any required source mismatch, missing official objective, or teaching gap
blocks the pack. A blocked or quarantined source is visible in the API and
Waypoint; it is not silently used.

The normal `ingest` command compiles an initial pack after deterministic book,
question, and diagnostic ingestion. Once a certification has a published
build, production ingestion for that certification fails closed. Corpus
changes must be rehearsed in a database copy and require a revisioned-source
migration; they cannot silently mutate the active study evidence.

## Preview and promotion

Compiler v5 separates building from publishing:

1. `python3 cli.py compile-pack --manifest <path>` creates a sealed preview.
   The candidate compile runs inside a savepoint, so the active pack,
   objectives, dossiers, and retrieval behavior remain unchanged.
2. The preview stores a canonical snapshot, SHA-256, and human-readable diff
   against the live pack. SQLite triggers prevent edits to the snapshot,
   report, diff, inputs, or hashes after insertion.
3. `python3 cli.py publish-pack <build-id> --manifest <path>` recompiles from
   current inputs. Promotion succeeds only if that fresh snapshot has the
   exact reviewed build hash and no blocking findings.
4. The previous published build is marked superseded and the active-build
   pointer changes in the same transaction. A changed source, parser,
   manifest, or official objective heading invalidates the preview.

Waypoint displays the latest release status and diff. It does not expose a
browser publish button; promotion remains a deliberate operator action.

## Parser adapter contract

Each converted book declares one allowlisted parser under `ingest.parser`.
Adapters receive only the manifest's active exam codes and one book's ordered
Markdown sections. They return objective hits and optional provisional domain
seeds; they do not read the database, network, or another book's state.

Current adapters:

- `inline-prefixed-objectives-v1`: checkmark lines contain an exam prefix and
  objective code;
- `divider-bare-objectives-domain-v1`: bare objective codes inherit the nearest
  preceding exam divider and chapter headings may seed provisional domains;
- `divider-bare-objectives-v1`: the same divider inference without domain
  seeding, used for assessment books;
- `none-v1`: ingest searchable sections without extracting objectives.

The registry cannot import a parser named by a manifest. Unknown adapters,
ambiguous exam prefixes, and missing parser declarations fail closed. Adapter
name and contract version are included in the pack's source-set hash, so
changing extraction behavior produces a materially different compiled input.

## Objective dossiers

Compiler v5 materializes one dossier per official objective after source and
coverage gates run. A dossier records:

- the pinned official source and objective-code scope;
- the canonical objective heading extracted from the pinned vendor document,
  plus its exact official provenance;
- the selected primary lesson excerpt and every admitted instructional
  citation;
- supplemental and assessment-source counts;
- direct objective-question and conservative domain-question counts;
- deterministic quality gates and a `complete`, `thin`, `conflicted`, or
  `missing` status.

Assessment-only books contribute availability counts but never appear as
instructional citations. `complete` means that official scope, primary
instruction, supplemental instruction, assessment availability, and
conflict-free gates passed. It is a source-quality claim, never a learner
mastery claim. The optional developer extractor verifies the PDF SHA-256
before reading it, admits only manifest-expected codes, joins wrapped
headings, and fails on missing or duplicate codes. The committed objective
JSON participates in the pack source-set hash. PDF parsing is a controlled
build-time operation, never a runtime web dependency.

`python3 cli.py verify-sources --manifest <path>` performs a controlled refresh
audit. It downloads only HTTPS URLs on the manifest's vendor-host allowlist,
streams at most 25 MiB per document, records the observed hash and response
metadata, and exits nonzero on drift or error. A mismatch never updates the
pinned hash, source disposition, or ready pack; it creates a visible
review-required event for a human-controlled manifest update.

`python3 cli.py verify-spines [--certification <id>]` applies the same bounded,
read-only hash check to the official documents for all six certification
spines. A page-only source or changed byte stream exits review-required and
never rewrites a trusted pin.

## Adding another certification

1. Obtain the current official objectives directly from the certification
   vendor.
2. Record the official URL, exact document/version identifiers, retrieval date,
   and locally verified SHA-256.
3. Convert the current-edition EPUBs to the v2 Markdown format.
4. Add their slugs, EPUB hashes, exam codes, and roles to a new certification
   manifest.
5. Declare each converted book's `ingest.parser` adapter and directory in the same
   manifest. Certification identity, exams, and corpus selection require no
   Python edit.
6. Extract official headings from the hash-verified vendor PDF and require an
   exact code/count match.
7. Compile against a database copy. Resolve every blocking finding.
8. Create a production preview, inspect the diff, and publish only the exact
   reviewed `ready` build. Then inspect provenance and coverage in Waypoint.

Official-source refresh is a controlled build-time action. Runtime retrieval
does not fetch arbitrary web pages, so a transient search result or an AI
answer cannot silently alter a learner's curriculum.
