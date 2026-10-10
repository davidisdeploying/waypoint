# Waypoint Learning Architecture

Waypoint prepares one learner for six certifications and seven exam sittings
before the planned 2027-08-01 WGU start. The system is intentionally split
into five cooperating engines so source quality, learning evidence, planning,
career relevance, and calendar pressure never become one opaque score.

## 1. Certification spine registry

`sources/certifications/certification-spines-v1.json` is the shared scope
registry for A+, Network+, Security+, Cloud+, CCNA Automation, and CCSP. It
records sequence, exam sittings, official domain names and weights, vendor
source versions, hashes, and whether a real published curriculum or only a
domain scaffold exists.

All seven current exam-source documents are pinned to official vendor URLs and
verified SHA-256 values. The verifier will still disclose a future page-only
source as review-required rather than upgrading it implicitly.

Official vendor objectives define scope. A registry-bound pack declares
`spine_registry_version`; the compiler then fails closed if its exams,
domains, weights, URLs, or hashes diverge. `cli.py verify-spines` streams
pinned vendor documents through a 25 MiB limit and reports drift without
rewriting the registry. Page-only sources remain visibly review-required.

## 2. Knowledge compiler

The compiler attaches current instructional and assessment sources to the
official spine, produces cited objective dossiers, quarantines bad inputs,
and requires immutable preview/publish promotion. Books explain the spine;
they do not define it. Practice books stay assessment-only and never become
teaching citations.

## 3. Mastery and readiness evidence

The learner model keeps evidence classes separate. `lib/readiness.py` exposes
ten explainable gates:

1. hash-verified official scope;
2. published governed pack;
3. complete source dossier for every objective;
4. every objective lesson completed;
5. active recall for every objective;
6. every enabled domain check mastered;
7. every objective scheduled for retention with none overdue;
8. completed hands-on work across every domain, with unaided reproduction
   across at least half the domains;
9. no open remediation gaps; and
10. two fresh timed held-out exams at 85% overall, at least 75% in every
    domain, no timeout, and no reused questions.

There is no composite readiness score. Reading time, a resume claim, and a
multiple-choice result cannot substitute for one another. Waypoint recommends
booking only when all ten gates pass, and still does not claim a guaranteed
vendor-exam result.

## 4. Adaptive planner

The planner orders overdue retention, open remediation, knowledge checks,
objective lessons, and current curriculum work. It discloses provisional work
that may change after a diagnostic. It also calculates a protected finish line
28 days before 2027-08-01 so scheduling or one retake does not consume the WGU
start date.

## 5. Career-context bridge

`sources/career/career-context-v1.json` stores only stable Career claim IDs,
job-family mappings, and a SHA-256 guard for Career's canonical claims note.
Waypoint never copies or edits the claim text. Career context may prioritize
examples, labs, and review order inside official scope; it cannot remove exam
objectives or grant mastery.

Security+ and CCSP are explicitly supporting infrastructure/cloud knowledge.
They do not redirect the target trajectory toward dedicated cybersecurity
roles. CCSP also discloses that passing may result in Associate of ISC2 status
until the experience requirement is met.

## Operating rule

Only A+ currently has a published real curriculum. The other five entries are
honest official-domain projections until current instructional sources are
ingested, compiled, reviewed, and explicitly published. The architecture is
complete without pretending those content packs already exist.
