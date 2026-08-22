"""Deterministic extraction helpers for vendor objective documents.

PDF decoding is intentionally kept outside the runtime compiler.  Operators
extract layout-preserving text with Poppler, validate it here against the
manifest's expected objective codes, and commit the resulting descriptions to
the governed manifest beside the pinned PDF hash.
"""
import re


HEADING_RE = re.compile(r"^\s*(\d+\.\d+)\s+(.+?)\s*$")
BULLET_PREFIXES = ("•", "-", "−", "◦", "գ")


class OfficialObjectiveError(ValueError):
    pass


def _clean(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\.\s+\.$", ".", text)
    return text


def parse_layout_text(text, expected_codes):
    """Return exact objective heading text from `pdftotext -layout` output.

    Only headings whose codes are explicitly expected are admitted. Wrapped
    heading lines are joined until terminal punctuation or a bullet/list line.
    Duplicate, missing, or empty objectives fail closed.
    """
    expected = list(expected_codes)
    expected_set = set(expected)
    found = {}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if not match or match.group(1) not in expected_set:
            continue
        code, first = match.groups()
        if code in found:
            raise OfficialObjectiveError(f"duplicate official objective {code}")
        parts = [first]
        cursor = index + 1
        while cursor < len(lines) and not parts[-1].rstrip().endswith((".", "?", "!")):
            continuation = lines[cursor].strip()
            if not continuation:
                cursor += 1
                continue
            if continuation.startswith(BULLET_PREFIXES):
                break
            if HEADING_RE.match(lines[cursor]):
                break
            parts.append(continuation)
            cursor += 1
        description = _clean(" ".join(parts))
        if not description:
            raise OfficialObjectiveError(f"empty official objective {code}")
        found[code] = description
    missing = expected_set - set(found)
    extra = set(found) - expected_set
    if missing or extra:
        raise OfficialObjectiveError(
            f"official objective mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return [{"code": code, "description": found[code]} for code in expected]
