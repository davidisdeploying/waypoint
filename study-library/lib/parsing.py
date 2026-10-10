"""Parsing helpers for Localworker v2 markdown book exports.

These directories are treated as immutable input (see README). We parse:
 - the YAML-ish frontmatter block that prefixes INDEX.md and every chapter file
 - conversion-report.json for the authoritative section list/order
 - CompTIA-style "objective" checkmark lines embedded in chapter bodies

The frontmatter blocks used by this converter are a flat `key: value` list
(no nesting, no lists) so a tiny line-based parser is sufficient and avoids
requiring a YAML library that may not be installed.
"""
import re

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def parse_frontmatter(text):
    """Split a markdown file into (frontmatter_dict, body). Empty dict if none found."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    block = m.group(1)
    body = text[m.end():]
    meta = {}
    for line in block.splitlines():
        line = line.rstrip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if value.lower() == "true":
            value = True
        elif value.lower() == "false":
            value = False
        else:
            try:
                value = int(value)
            except ValueError:
                pass
        meta[key] = value
    return meta, body


# --- Objective extraction -------------------------------------------------
#
# The "review guide" and "practice tests" books use bare "N.N" objective
# numbers (no exam prefix) inside a checkmark or blockquote-checkmark line;
# the exam has to be inferred from the nearest preceding PART divider.
BARE_OBJECTIVE_RE = re.compile(
    r"^(?:>\s*)?\*{0,2}[✔✓]\s*(?P<code>\d+\.\d+)\s+(?P<desc>.+?)\*{0,2}$", re.MULTILINE
)

PART_DIVIDER_RE = re.compile(
    r"^\s*PART\s+(?:[IVXLCDM]+|\d+)\b", re.IGNORECASE
)
CHAPTER_TITLE_RE = re.compile(
    r"^Chapter\s+\d+\s*(.*?)\s*(?:\(Part\s+\d+\s+of\s+\d+\))?$",
    re.IGNORECASE,
)


def extract_bare_objectives(body):
    """Return [(objective_code, description)] for review-guide/practice-tests chapters.

    Exam assignment is the caller's job (via divider-based positional inference)
    since these books present one exam's worth of chapters between PART markers.
    """
    out = []
    for m in BARE_OBJECTIVE_RE.finditer(body):
        out.append((m.group("code"), m.group("desc").strip()))
    return out


def is_part_divider(title):
    return bool(PART_DIVIDER_RE.search(title or ""))


def domain_name_from_chapter_title(title):
    match = CHAPTER_TITLE_RE.match((title or "").strip())
    if match and match.group(1):
        return match.group(1).strip()
    return None
