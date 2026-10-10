"""Allowlisted objective parser adapters for converted Markdown books.

Adapters are stateful per book so formats that infer an exam from a preceding
divider cannot leak that state into another source. The registry is explicit:
a manifest cannot dynamically import code or silently fall back to guessing.
"""
import re
from dataclasses import dataclass, field

from lib import parsing


ADAPTER_CONTRACT_VERSION = "1"


class ParserAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class ObjectiveHit:
    exam_code: str
    code: str
    description: str
    confidence: float
    provenance: str


@dataclass(frozen=True)
class DomainSeed:
    exam_code: str
    code: str
    name: str
    confidence: float
    provenance: str


@dataclass(frozen=True)
class ParseResult:
    objectives: list[ObjectiveHit] = field(default_factory=list)
    domains: list[DomainSeed] = field(default_factory=list)


def _exam_prefixes(exam_codes):
    prefixes = {}
    for exam_code in exam_codes:
        candidates = {exam_code, exam_code.rsplit("-", 1)[-1]}
        for candidate in candidates:
            existing = prefixes.get(candidate)
            if existing and existing != exam_code:
                raise ParserAdapterError(
                    f"exam prefix '{candidate}' is ambiguous between "
                    f"'{existing}' and '{exam_code}'"
                )
            prefixes[candidate] = exam_code
    return prefixes


class InlinePrefixedObjectives:
    """Checkmark lines carry an exam prefix and objective code."""

    def __init__(self, slug, exam_codes):
        self.slug = slug
        self.prefixes = _exam_prefixes(exam_codes)
        alternatives = "|".join(
            re.escape(value)
            for value in sorted(self.prefixes, key=len, reverse=True)
        )
        self.pattern = re.compile(
            rf"[✔✓]\s*(?P<exam>{alternatives})-"
            rf"(?P<code>\d+(?:\.\d+)?)\s+(?P<desc>.+)"
        )

    def consume(self, title, body):
        hits = []
        for line in body.splitlines():
            match = self.pattern.search(line)
            if not match:
                continue
            exam_code = self.prefixes[match.group("exam")]
            code = match.group("code")
            hits.append(ObjectiveHit(
                exam_code=exam_code,
                code=code,
                description=match.group("desc").strip(),
                confidence=0.9,
                provenance=(
                    f"{self.slug}: inline '{match.group('exam')}-{code}' "
                    f"objective marker in section '{title}'"
                ),
            ))
        return ParseResult(objectives=hits)


class DividerBareObjectives:
    """Bare objective codes inherit the nearest preceding exam divider."""

    def __init__(self, slug, exam_codes, derive_domains=False):
        self.slug = slug
        self.exam_codes = tuple(exam_codes)
        self.derive_domains = derive_domains
        self.current_exam_code = None
        alternatives = "|".join(
            re.escape(code)
            for code in sorted(self.exam_codes, key=len, reverse=True)
        )
        self.exam_pattern = re.compile(rf"(?<![\w-])({alternatives})(?![\w-])")

    def _detect_exam(self, text):
        matches = list(self.exam_pattern.finditer(text))
        return matches[-1].group(1) if matches else None

    def consume(self, title, body):
        if parsing.is_part_divider(title):
            detected = self._detect_exam(body) or self._detect_exam(title)
            if detected:
                self.current_exam_code = detected
        if not self.current_exam_code:
            return ParseResult()

        hits = [
            ObjectiveHit(
                exam_code=self.current_exam_code,
                code=code,
                description=description,
                confidence=0.6,
                provenance=(
                    f"{self.slug}: bare '{code}' objective marker in section "
                    f"'{title}'; exam inferred from nearest preceding PART divider"
                ),
            )
            for code, description in parsing.extract_bare_objectives(body)
        ]
        domains = []
        if hits and self.derive_domains:
            domain_name = parsing.domain_name_from_chapter_title(title)
            if domain_name:
                domain_code = hits[0].code.split(".")[0]
                domains.append(DomainSeed(
                    exam_code=self.current_exam_code,
                    code=domain_code,
                    name=domain_name,
                    confidence=0.6,
                    provenance=(
                        f"{self.slug}: derived from chapter heading '{title}'; "
                        "chapter assumed 1:1 with an exam domain, not verified "
                        "against the vendor's published objectives document"
                    ),
                ))
        return ParseResult(objectives=hits, domains=domains)


class NoObjectives:
    def consume(self, title, body):
        return ParseResult()


PARSER_ADAPTERS = {
    "inline-prefixed-objectives-v1": (
        lambda slug, exam_codes: InlinePrefixedObjectives(slug, exam_codes)
    ),
    "divider-bare-objectives-v1": (
        lambda slug, exam_codes: DividerBareObjectives(slug, exam_codes)
    ),
    "divider-bare-objectives-domain-v1": (
        lambda slug, exam_codes: DividerBareObjectives(
            slug, exam_codes, derive_domains=True
        )
    ),
    "none-v1": lambda slug, exam_codes: NoObjectives(),
}


def parser_adapter_names():
    return frozenset(PARSER_ADAPTERS)


def build_parser_adapter(name, slug, exam_codes):
    factory = PARSER_ADAPTERS.get(name)
    if not factory:
        raise ParserAdapterError(
            f"unknown parser adapter '{name}'; allowed: "
            f"{', '.join(sorted(PARSER_ADAPTERS))}"
        )
    if not exam_codes:
        raise ParserAdapterError(f"parser adapter '{name}' requires exam codes")
    return factory(slug, tuple(exam_codes))
