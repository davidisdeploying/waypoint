"""Retrieval-backed remediation packet content: relevant-section citations,
a deterministic active-recall prompt, and a labeled hands-on scaffold.

No LLM calls anywhere in this module -- everything is FTS5 retrieval over the
already-ingested sections table plus fixed string templates.
"""
import re

PRACTICE_BOOK_SLUG = "aplus-practice-tests"
MAX_READINGS = 3
SNIPPET_WORDS = 20

STOPWORDS = {
    "a", "an", "as", "at", "be", "by", "do", "does", "if", "in", "is",
    "it", "its", "of", "on", "or", "same", "to", "was", "were",
    "the", "and", "for", "are", "that", "this", "with", "from", "your", "you",
    "what", "which", "would", "will", "have", "has", "not", "but", "when",
    "their", "they", "them", "into", "onto", "than", "then", "most", "likely",
    "following", "should", "could", "these", "those", "been", "being", "also",
    "used", "using", "use", "can", "may", "must", "one", "two", "three", "four",
    "choose", "select", "correct", "answer", "customer", "client", "user",
}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}")


def _extract_terms(text, limit=8):
    seen = []
    for tok in TOKEN_RE.findall(text.lower()):
        if tok in STOPWORDS or tok in seen:
            continue
        seen.append(tok)
        if len(seen) >= limit:
            break
    return seen


def _fts_query(terms):
    if not terms:
        return None
    escaped = [t.replace('"', '') for t in terms]
    return " OR ".join(f'"{t}"' for t in escaped)


# Scope restriction is a semi-join, not a join. Joining through
# objective_chunk_links fans one section out into a row per linked objective,
# which then needs SELECT DISTINCT to collapse -- and DISTINCT proves
# uniqueness by comparing every selected column, including the whole section
# body. Restricting with IN never creates the duplicates, so no DISTINCT is
# needed. Verified equivalent across 4131 query pairs (every question in the
# bank x every scope) with zero differences, at 2.1x the speed.
_OBJECTIVE_SEMI_JOIN = (
    "s.id IN (SELECT ocl.section_id FROM objective_chunk_links ocl "
    "JOIN objectives ob ON ob.id = ocl.objective_id WHERE ob.{column} = ?)"
)


def _fts_search(conn, fts_query, domain_id, exam_id, limit):
    where = ["sections_fts MATCH ?", "b.slug != ?"]
    params = [fts_query, PRACTICE_BOOK_SLUG]
    if domain_id is not None:
        where.append(_OBJECTIVE_SEMI_JOIN.format(column="domain_id"))
        params.append(domain_id)
    elif exam_id is not None:
        where.append(_OBJECTIVE_SEMI_JOIN.format(column="exam_id"))
        params.append(exam_id)
    sql = (
        "SELECT s.stable_id, s.title, s.content, s.content_sha256, "
        "b.slug AS book_slug, b.title AS book_title, "
        "snippet(sections_fts, 1, '', '', '…', ?) AS snippet, bm25(sections_fts) AS rank "
        "FROM sections_fts JOIN sections s ON s.id = sections_fts.rowid JOIN books b ON b.id = s.book_id "
        " WHERE " + " AND ".join(where) + " ORDER BY rank LIMIT ?"
    )
    params_full = [SNIPPET_WORDS] + params + [limit]
    try:
        return conn.execute(sql, params_full).fetchall()
    except Exception:
        return []


def _local_terms(text, limit):
    terms = []
    for term in _extract_terms(text, limit=limit):
        for part in re.findall(r"[a-z0-9]+", term.lower()):
            if len(part) < 2 or part in STOPWORDS or part in terms:
                continue
            terms.append(part)
            if len(terms) >= limit:
                return terms
    return terms


MAX_TERM_POSITIONS = 24


def _best_local_window(content, priority_terms, context_terms, radius=320, lower=None):
    if lower is None:
        lower = content.lower()
    positions = []
    for term in priority_terms:
        positions.extend((start, term, True) for start in _find_starts(lower, term))
    if not positions:
        for term in context_terms:
            positions.extend((start, term, False) for start in _find_starts(lower, term))
    best = None
    for position, _term, _is_priority in positions:
        if position < 0:
            continue
        start = max(0, position - radius)
        end = min(len(content), position + radius)
        window = lower[start:end]
        priority_hits = sum(1 for term in priority_terms if _contains_term(window, term))
        context_hits = sum(1 for term in context_terms if _contains_term(window, term))
        score = priority_hits * 8 + context_hits * 2
        candidate = (score, priority_hits, context_hits, -start, end)
        if best is None or candidate > best:
            best = candidate
    if not best:
        return None
    score, priority_hits, context_hits, negative_start, end = best
    return score, priority_hits, context_hits, -negative_start, end


def _find_starts(text, term):
    pattern = _term_pattern(term)
    for index, match in enumerate(pattern.finditer(text)):
        if index >= MAX_TERM_POSITIONS:
            break
        yield match.start()


def _contains_term(text, term):
    return bool(_term_pattern(term).search(text))


# Compiled once per term rather than per call. re has its own pattern cache, but
# reaching it still meant rebuilding the pattern string and re.escape()-ing the
# term on every one of the ~580k calls a single submit used to make.
_TERM_PATTERNS = {}


def _term_pattern(term):
    pattern = _TERM_PATTERNS.get(term)
    if pattern is None:
        suffix = r"(?:s|es)?" if len(term) >= 3 else ""
        if len(term) >= 4:
            suffix = r"(?:s|es|ed|ing|ment)?"
        pattern = re.compile(
            rf"(?<![a-z0-9]){re.escape(term)}{suffix}(?![a-z0-9])"
        )
        _TERM_PATTERNS[term] = pattern
    return pattern


def _required_hits(priority_total):
    """Lower bounds _precise_candidates will demand of the winning window."""
    if priority_total >= 2:
        return min(2, priority_total), 1
    if priority_total == 1:
        return 1, 2
    return 0, 4


def _can_qualify(lower, priority_terms, context_terms):
    """Whether any window in this section could clear the acceptance bar.

    A window is a slice of the section, so it can never contain more distinct
    terms than the whole section does. Counting present terms with an
    early-exiting search is far cheaper than locating every match and scoring
    every candidate window, and rejecting here is equivalent to letting
    _precise_candidates reject the same section afterwards.
    """
    need_priority, need_context = _required_hits(len(priority_terms))
    for terms, needed in ((priority_terms, need_priority), (context_terms, need_context)):
        if not needed:
            continue
        found = 0
        remaining = len(terms)
        for term in terms:
            remaining -= 1
            if _contains_term(lower, term):
                found += 1
                if found >= needed:
                    break
            elif found + remaining < needed:
                return False
        if found < needed:
            return False
    return True


def _precise_candidates(rows, priority_terms, context_terms, scope_label, window_cache=None):
    candidates = []
    for row in rows:
        # The scope passes overlap heavily -- the same section is commonly
        # returned domain-linked, exam-constrained, and again as corpus
        # fallback. The window result depends only on the content and the
        # terms, both fixed for this lookup; only the scope bonus below differs.
        cache_key = row["content_sha256"]
        if window_cache is not None and cache_key in window_cache:
            best = window_cache[cache_key]
        else:
            lower = row["content"].lower()
            best = (
                _best_local_window(row["content"], priority_terms, context_terms, lower=lower)
                if _can_qualify(lower, priority_terms, context_terms)
                else None
            )
            if window_cache is not None:
                window_cache[cache_key] = best
        if not best:
            continue
        score, priority_hits, context_hits, start, end = best
        priority_total = len(priority_terms)
        if priority_total >= 2:
            accepted = priority_hits >= min(2, priority_total) and context_hits >= 1
        elif priority_total == 1:
            accepted = priority_hits == 1 and context_hits >= 2
        else:
            accepted = context_hits >= 4
        if not accepted:
            continue
        if scope_label == "domain-linked":
            score += 12
        elif scope_label == "exam-constrained":
            score += 4
        snippet = " ".join(row["content"][start:end].split())
        if start:
            snippet = "…" + snippet
        if end < len(row["content"]):
            snippet += "…"
        candidates.append((score, row, snippet, scope_label))
    return candidates


def find_relevant_readings(
    conn, exam_id, domain_id, query_text, limit=MAX_READINGS, priority_text=""
):
    """Up to `limit` answer-focused citations with local-window verification."""
    priority_terms = _local_terms(priority_text, limit=8)
    context_terms = [
        term for term in _local_terms(query_text, limit=14)
        if term not in priority_terms
    ]
    if not context_terms and not priority_terms:
        return []

    fts_query = _fts_query(priority_terms + context_terms)
    candidates = []
    scopes = [
        (domain_id, None, "domain-linked"),
        (None, exam_id, "exam-constrained"),
        (None, None, "corpus fallback"),
    ]
    window_cache = {}
    for scoped_domain, scoped_exam, scope_label in scopes:
        rows = _fts_search(conn, fts_query, scoped_domain, scoped_exam, 40)
        candidates.extend(
            _precise_candidates(
                rows, priority_terms, context_terms, scope_label, window_cache
            )
        )

    candidates.sort(key=lambda item: (-item[0], item[1]["rank"]))
    results = []
    seen_hashes = set()
    quality_floor = candidates[0][0] - 1 if candidates else 0
    for score, row, snippet, scope_label in candidates:
        if score < quality_floor:
            break
        if row["content_sha256"] in seen_hashes:
            continue
        seen_hashes.add(row["content_sha256"])
        results.append({
            "book_slug": row["book_slug"],
            "book_title": row["book_title"],
            "section_stable_id": row["stable_id"],
            "section_title": row["title"],
            "snippet": snippet,
            "content_hash": row["content_sha256"],
            "retrieval_basis": (
                f"answer-focused local-window FTS; {scope_label}"
                + (" via objective links" if scope_label != "corpus fallback" else "")
                + f"; relevance {score}"
            ),
        })
        if len(results) >= limit:
            break
    return results


def build_recall_prompt(prompt, options, correct_indexes):
    correct_text = "; ".join(options[i] for i in correct_indexes if 0 <= i < len(options))
    return (
        f"Active recall (no notes): without looking back, explain in your own words why "
        f"\"{correct_text}\" is the correct answer to: {prompt}"
    )


def build_lab_scaffold(domain_name):
    return (
        f"[Scaffold suggestion, not an official lab or PBQ] Find or set up a real or "
        f"virtual example touching \"{domain_name}\" and practice applying this concept "
        f"hands-on. This is a starting point for you to scope a concrete exercise, not a "
        f"validated lab -- multiple-choice mastery here does not itself prove hands-on ability."
    )
