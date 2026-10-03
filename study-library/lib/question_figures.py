"""Resolve practice-question figures from the immutable EPUB source.

A practice-test question owns a figure when the question is a numbered
``<li>`` whose own subtree contains an ``<img>``. That structural fact is
ground truth: it is authored by the publisher and needs no phrase matching.
Prose heuristics ("shown here", "in the graphic") were the previous
detector and both over- and under-matched -- they missed nine live
figure-dependent questions and cannot distinguish "plugged into this port"
(self-contained) from "what this port is" (needs the picture).

Images nested inside an option list belong to that option, not the stem, so
only the question-level ``<li>`` is credited. Members are returned as EPUB
zip paths; callers hand them to ``epub_reader.get_reader_asset`` for the
sanitized, identity-checked byte serve.
"""

from __future__ import annotations

import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from . import epub_reader
from .epub_reader import EpubUnavailable


class _QuestionListParser(HTMLParser):
    """Collect question-level ``<li>`` frames and the images they contain.

    Depth tracking is what separates a question from its options: the
    question list is the outermost ``<ol>``, and the four answer choices are
    always a nested ``<ol>`` inside the question's own ``<li>``.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ol_depth = 0
        self._stack = []
        self.questions = []

    def _current(self):
        # Only the innermost <li> counts. Walking past a nested option frame
        # would credit an answer choice's own art to the question stem.
        return self._stack[-1] if self._stack else None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "ol":
            self._ol_depth += 1
        elif tag == "li":
            if self._ol_depth == 1:
                self._stack.append({"value": attributes.get("value"), "text": [], "images": []})
            else:
                self._stack.append(None)
        elif tag == "img":
            frame = self._current()
            if frame is not None:
                frame["images"].append(attributes.get("src") or "")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "ol":
            self._ol_depth = max(0, self._ol_depth - 1)
        elif tag == "li" and self._stack:
            frame = self._stack.pop()
            if frame is not None:
                self.questions.append(frame)

    def handle_data(self, data):
        frame = self._current()
        if frame is not None:
            frame["text"].append(data)


def _first_image(source_item, images, names):
    """Return the first image that is a real, allowed member of this EPUB."""
    for href in images:
        try:
            member = epub_reader._safe_member(source_item, href)
        except EpubUnavailable:
            continue
        if member in names and Path(member).suffix.lower() in epub_reader.IMAGE_EXTENSIONS:
            return member
    return None


def _parse_document(epub, source_item, names):
    parser = _QuestionListParser()
    parser.feed(epub.read(source_item).decode("utf-8", "replace"))
    figures = {}
    for frame in parser.questions:
        value = frame["value"]
        if not value or not str(value).isdigit() or not frame["images"]:
            continue
        number = int(value)
        if number in figures:
            continue  # first occurrence wins; the list is authored in order
        member = _first_image(source_item, frame["images"], names)
        if member:
            figures[number] = member
    return figures


def figure_map(conn, book_slug):
    """Map ``(source_item, question_number)`` to an EPUB image member.

    Returns an empty map when the book has no usable EPUB, so ingest keeps
    working from Markdown alone rather than failing the whole import.
    """
    row = conn.execute(
        "SELECT id, source_epub_path, source_epub_sha256 FROM books WHERE slug = ?",
        (book_slug,),
    ).fetchone()
    if not row:
        return {}
    try:
        epub_path = epub_reader._book_epub(row)
    except (EpubUnavailable, OSError):
        return {}

    source_items = [
        item["source_item"]
        for item in conn.execute(
            "SELECT DISTINCT source_item FROM sections WHERE book_id = ? AND source_item IS NOT NULL",
            (row["id"],),
        )
    ]
    mapping = {}
    try:
        with zipfile.ZipFile(epub_path) as epub:
            names = set(epub.namelist())
            for source_item in source_items:
                if source_item not in names:
                    continue
                for number, member in _parse_document(epub, source_item, names).items():
                    mapping[(source_item, number)] = member
    except (OSError, zipfile.BadZipFile):
        return {}
    return mapping


CLAIMS_FIGURE_RE = re.compile(
    r"shown (?:here|below|in the)|pictured (?:here|below)|"
    r"following (?:graphic|image|figure|illustration|screenshot|diagram)\b|"
    r"in the (?:image|graphic|picture|figure|illustration|diagram)\b|"
    r"this (?:graphic|image|figure|illustration|screenshot|diagram)\b|"
    r"(?:figure|graphic|image|illustration) shown",
    re.IGNORECASE,
)


def claims_figure(stem, options):
    """True when the prose says a figure exists.

    Only used to report questions whose text promises a picture we could not
    resolve -- never to decide that a figure exists.
    """
    if CLAIMS_FIGURE_RE.search(stem or ""):
        return True
    return any(CLAIMS_FIGURE_RE.search(option or "") for option in options or [])


def figure_payload(section_stable_id, member):
    """Point at the sanitized EPUB asset route for a question's figure.

    Figures are never withheld with the answer key: the picture is part of
    the question, so it stays visible while an attempt is still open.
    """
    if not section_stable_id or not member:
        return None
    return {
        "member": member,
        "url": (
            f"/api/v2/study/sections/{quote(section_stable_id, safe='')}"
            f"/epub-assets/{quote(member, safe='/')}"
        ),
    }
