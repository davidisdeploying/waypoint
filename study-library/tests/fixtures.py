"""Builds small synthetic v2-format source directories for tests.

Mirrors the real Localworker v2 export shape (INDEX.md + conversion-report.json +
chapters/*.md with the flat frontmatter block) closely enough to exercise the
real parsing/ingest code paths without depending on the real vault corpus.
"""
import json
from pathlib import Path

GUIDE_CHAPTER = """---
type: book-section
book: "Fixture Guide Book"
section: {position}
source_position: {position}
part: 1
part_count: 1
source_item: "OEBPS/ch{position}.xhtml"
source_epub_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
converter_version: 2
generated_by: Localworker
derivative: true
---

# {title}

In this chapter you will learn about {topic}.

CompTIA Exam Objectives:

-

✓ 1201-{code} {desc}

Body text about {topic} follows here, discussing {topic} in useful detail for search.
"""

REVIEW_DIVIDER = """---
type: book-section
book: "Fixture Review Guide"
section: {position}
source_position: {position}
part: 1
part_count: 1
source_item: "OEBPS/p{position}.xhtml"
source_epub_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
converter_version: 2
generated_by: Localworker
derivative: true
---

# PART {roman}

Fixture Review Guide

PART {roman}
COMPTIA A+ {label} EXAM {exam}
"""

REVIEW_CHAPTER = """---
type: book-section
book: "Fixture Review Guide"
section: {position}
source_position: {position}
part: 1
part_count: 1
source_item: "OEBPS/c{position}.xhtml"
source_epub_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
converter_version: 2
generated_by: Localworker
derivative: true
---

# Chapter {chapter_num} {domain_name}

Fixture Review Guide

### COMPTIA A+ EXAM OBJECTIVES COVERED IN THIS CHAPTER:

**✔ {code} {desc}**

Body text about {domain_name} follows here for full-text search purposes.
"""

PRACTICE_DIVIDER = """---
type: book-section
book: "Fixture Practice Tests"
section: {position}
source_position: {position}
part: 1
part_count: 1
source_item: "index_split_{position}.html"
source_epub_sha256: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
converter_version: 2
generated_by: Localworker
derivative: true
---

# PART {roman}

Fixture Practice Tests

PART {roman}
COMPTIA A+ {label} EXAM {exam}
"""

PRACTICE_CHAPTER = """---
type: book-section
book: "Fixture Practice Tests"
section: {position}
source_position: {position}
part: 1
part_count: 1
source_item: "index_split_{position}.html"
source_epub_sha256: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
converter_version: 2
generated_by: Localworker
derivative: true
---

# Chapter {chapter_num}

Fixture Practice Tests

> THE COMPTIA A+ TOPICS COVERED IN THIS CHAPTER INCLUDE THE FOLLOWING:

> ✔ {code} {desc}

Practice question body text about {domain_name} for search purposes.
"""


def _write(dirpath, sections_meta, template_map):
    chapters = dirpath / "chapters"
    chapters.mkdir(parents=True, exist_ok=True)
    sections = []
    for meta in sections_meta:
        fname = f"{meta['position']:03d}-{meta['slug']}.md"
        text = template_map[meta["kind"]].format(**meta)
        (chapters / fname).write_text(text, encoding="utf-8")
        sections.append({
            "position": meta["position"],
            "source_position": meta["position"],
            "part": 1,
            "part_count": 1,
            "title": meta["title"],
            "file": f"chapters/{fname}",
            "source_item": f"OEBPS/x{meta['position']}.xhtml",
            "words": len(text.split()),
            "sha256": "0" * 64,
        })
    return sections


def build_guide_source(base_dir):
    d = base_dir / "fixture-guide-v2"
    sections_meta = [
        {"position": 1, "slug": "cover", "kind": "cover", "title": "Fixture Guide Book"},
        {"position": 2, "slug": "ch1", "kind": "guide", "title": "1 Mobile Devices",
         "topic": "mobile devices", "code": "1.1", "desc": "Summarize mobile device hardware."},
        {"position": 3, "slug": "ch2", "kind": "guide", "title": "2 Networking",
         "topic": "networking", "code": "2.1", "desc": "Compare networking hardware."},
    ]
    cover_tpl = "---\ntype: book-section\nbook: \"Fixture Guide Book\"\nsection: 1\n---\n\n# Cover\n\nFixture Guide Book.\n"
    template_map = {"cover": cover_tpl, "guide": GUIDE_CHAPTER}
    sections = _write(d, sections_meta, template_map)
    (d / "INDEX.md").write_text(
        '---\ntype: book-index\ntitle: "Fixture Guide Book"\ncreator: "Test Author"\n'
        'language: "en"\nsource_epub_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n'
        'converter_version: 2\ngenerated_by: Localworker\nderivative: true\n---\n\n# Fixture Guide Book\n',
        encoding="utf-8",
    )
    report = {
        "status": "success", "title": "Fixture Guide Book", "source_size_bytes": 100,
        "source_sha256": "a" * 64, "creator": "Test Author", "language": "en",
        "converter_version": 2, "source_item_count": len(sections),
        "section_count": len(sections), "total_words": sum(s["words"] for s in sections),
        "sections": sections, "token": "x",
    }
    (d / "conversion-report.json").write_text(json.dumps(report), encoding="utf-8")
    return {
        "slug": "fixture-guide",
        "kind": "guide",
        "parser": "inline-prefixed-objectives-v1",
        "dir": str(d),
    }


def build_review_source(base_dir):
    d = base_dir / "fixture-review-v2"
    sections_meta = [
        {"position": 1, "slug": "part1", "kind": "divider", "title": "PART I", "roman": "I",
         "label": "CORE 1", "exam": "220-1201"},
        {"position": 2, "slug": "ch1", "kind": "chapter", "title": "Chapter 1 Mobile Devices",
         "chapter_num": 1, "domain_name": "Mobile Devices", "code": "1.1",
         "desc": "Given a scenario, monitor mobile device hardware."},
        {"position": 3, "slug": "part2", "kind": "divider", "title": "PART II", "roman": "II",
         "label": "CORE 2", "exam": "220-1202"},
        {"position": 4, "slug": "ch2", "kind": "chapter", "title": "Chapter 2 Operating Systems",
         "chapter_num": 2, "domain_name": "Operating Systems", "code": "1.1",
         "desc": "Given a scenario, install and configure operating systems."},
    ]
    template_map = {"divider": REVIEW_DIVIDER, "chapter": REVIEW_CHAPTER}
    sections = _write(d, sections_meta, template_map)
    (d / "INDEX.md").write_text(
        '---\ntype: book-index\ntitle: "Fixture Review Guide"\ncreator: "Test Author"\n'
        'language: "en"\nsource_epub_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
        'converter_version: 2\ngenerated_by: Localworker\nderivative: true\n---\n\n# Fixture Review Guide\n',
        encoding="utf-8",
    )
    report = {
        "status": "success", "title": "Fixture Review Guide", "source_size_bytes": 100,
        "source_sha256": "b" * 64, "creator": "Test Author", "language": "en",
        "converter_version": 2, "source_item_count": len(sections),
        "section_count": len(sections), "total_words": sum(s["words"] for s in sections),
        "sections": sections, "token": "x",
    }
    (d / "conversion-report.json").write_text(json.dumps(report), encoding="utf-8")
    return {
        "slug": "fixture-review",
        "kind": "review",
        "parser": "divider-bare-objectives-domain-v1",
        "dir": str(d),
    }


def build_practice_source(base_dir):
    d = base_dir / "fixture-practice-v2"
    sections_meta = [
        {"position": 1, "slug": "part1", "kind": "divider", "title": "PART I", "roman": "I",
         "label": "CORE 1", "exam": "220-1201"},
        {"position": 2, "slug": "ch1", "kind": "chapter", "title": "Chapter 1",
         "chapter_num": 1, "domain_name": "Mobile Devices", "code": "1.1",
         "desc": "Given a scenario, monitor mobile device hardware."},
        {"position": 3, "slug": "part2", "kind": "divider", "title": "PART II", "roman": "II",
         "label": "CORE 2", "exam": "220-1202"},
        {"position": 4, "slug": "ch2", "kind": "chapter", "title": "Chapter 2",
         "chapter_num": 2, "domain_name": "Operating Systems", "code": "1.1",
         "desc": "Given a scenario, install and configure operating systems."},
    ]
    template_map = {"divider": PRACTICE_DIVIDER, "chapter": PRACTICE_CHAPTER}
    sections = _write(d, sections_meta, template_map)
    (d / "INDEX.md").write_text(
        '---\ntype: book-index\ntitle: "Fixture Practice Tests"\ncreator: "Test Author"\n'
        'language: "en"\nsource_epub_sha256: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\n'
        'converter_version: 2\ngenerated_by: Localworker\nderivative: true\n---\n\n# Fixture Practice Tests\n',
        encoding="utf-8",
    )
    report = {
        "status": "success", "title": "Fixture Practice Tests", "source_size_bytes": 100,
        "source_sha256": "c" * 64, "creator": "Test Author", "language": "en",
        "converter_version": 2, "source_item_count": len(sections),
        "section_count": len(sections), "total_words": sum(s["words"] for s in sections),
        "sections": sections, "token": "x",
    }
    (d / "conversion-report.json").write_text(json.dumps(report), encoding="utf-8")
    return {
        "slug": "fixture-practice",
        "kind": "practice",
        "parser": "divider-bare-objectives-v1",
        "dir": str(d),
    }


DIAG_FRONTMATTER = """---
type: book-section
book: "Fixture Practice Tests"
section: {position}
source_position: {position}
part: 1
part_count: 1
source_item: "index_split_{position}.html"
source_epub_sha256: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
converter_version: 2
generated_by: Localworker
derivative: true
---

"""

DIAG_PART1_DIVIDER = DIAG_FRONTMATTER + "# PART I\n\nFixture Practice Tests\n\nPART I\nCOMPTIA A+ CORE 1 EXAM 220-1201\n"

DIAG_QUESTION_CHAPTER = DIAG_FRONTMATTER + """# Chapter 1

Fixture Practice Tests

1. What color is commonly used for RAM slots on this fixture motherboard?

1. Blue

2. Green

3. Red

4. Yellow

2. Which two protocols are considered secure for remote access? (Choose two.)

1. SSH

2. Telnet

3. HTTPS

4. FTP

3. What component is shown in the following image?

1. CPU

2. RAM

3. GPU

4. PSU

4. What tool would you use to test cable continuity?

1. Multimeter

2. Screwdriver

3. Punch-down tool

4. Crimper
"""

# Answer for Q4 deliberately omits a letter grade (figure/unparseable-style
# exclusion case, mirroring the real corpus's occasional no-letter answer).
DIAG_EXPLANATION_CHAPTER = DIAG_FRONTMATTER + """# Chapter 1: Mobile Devices

Fixture Practice Tests

1. B. Green is commonly used to denote RAM slots on many fixture boards.

2. A, C. SSH and HTTPS are considered secure; Telnet and FTP transmit in cleartext.

3. C. This shows a fixture GPU heatsink.

4. A multimeter can test continuity, resistance, and voltage on cables and components.
"""


def build_diagnostics_practice_source(base_dir):
    """A minimal aplus-practice-tests-slugged book with one real question
    chapter (Chapter 1, exam 220-1201) + matching explanation chapter, for
    exercising ingest.diagnostics_importer through the real ingest pipeline.
    Uses the production slug 'aplus-practice-tests' deliberately (the importer
    is hardcoded to it, same as the real source)."""
    d = base_dir / "fixture-diag-practice-v2"
    sections_meta = [
        {"position": 1, "slug": "part1", "kind": "divider"},
        {"position": 2, "slug": "ch1-q", "kind": "question", "title": "Chapter 1"},
        {"position": 3, "slug": "ch1-a", "kind": "explanation", "title": "Chapter 1: Mobile Devices"},
    ]
    template_map = {
        "divider": DIAG_PART1_DIVIDER,
        "question": DIAG_QUESTION_CHAPTER,
        "explanation": DIAG_EXPLANATION_CHAPTER,
    }
    chapters = d / "chapters"
    chapters.mkdir(parents=True, exist_ok=True)
    sections = []
    for meta in sections_meta:
        fname = f"{meta['position']:03d}-{meta['slug']}.md"
        text = template_map[meta["kind"]].format(position=meta["position"])
        title = meta.get("title") or ("PART I" if meta["kind"] == "divider" else meta["kind"])
        (chapters / fname).write_text(text, encoding="utf-8")
        sections.append({
            "position": meta["position"], "source_position": meta["position"],
            "part": 1, "part_count": 1, "title": title, "file": f"chapters/{fname}",
            "source_item": f"index_split_{meta['position']}.html",
            "words": len(text.split()), "sha256": "0" * 64,
        })
    (d / "INDEX.md").write_text(
        '---\ntype: book-index\ntitle: "Fixture Practice Tests"\ncreator: "Test Author"\n'
        'language: "en"\nsource_epub_sha256: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd\n'
        'converter_version: 2\ngenerated_by: Localworker\nderivative: true\n---\n\n# Fixture Practice Tests\n',
        encoding="utf-8",
    )
    report = {
        "status": "success", "title": "Fixture Practice Tests", "source_size_bytes": 100,
        "source_sha256": "d" * 64, "creator": "Test Author", "language": "en",
        "converter_version": 2, "source_item_count": len(sections),
        "section_count": len(sections), "total_words": sum(s["words"] for s in sections),
        "sections": sections, "token": "x",
    }
    (d / "conversion-report.json").write_text(json.dumps(report), encoding="utf-8")
    return {
        "slug": "aplus-practice-tests",
        "kind": "practice",
        "parser": "divider-bare-objectives-v1",
        "dir": str(d),
    }


def build_all_sources(base_dir):
    # review first, matching ingest.sources.get_sources() ordering (seeds domains)
    return [
        build_review_source(base_dir),
        build_guide_source(base_dir),
        build_practice_source(base_dir),
    ]
