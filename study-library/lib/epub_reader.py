"""Safe, section-scoped presentation rendering from immutable EPUB sources."""

from __future__ import annotations

import hashlib
import html
import mimetypes
import os
import posixpath
import re
import zipfile
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET


EPUB_ROOT = Path(
    os.environ.get(
        "STUDY_LIBRARY_EPUB_ROOT", os.path.expanduser("~/Vaults/career-vault/files")
    )
).resolve()
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd", "figcaption", "blockquote", "pre"}
ALLOWED_TAGS = {
    "div", "section", "article", "aside", "header", "footer", "figure", "figcaption",
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
    "strong", "b", "em", "i", "small", "mark", "span", "sup", "sub", "blockquote",
    "pre", "code", "br", "hr", "img", "a",
}
DROP_TAGS = {"script", "style", "nav", "noscript", "iframe", "object", "embed", "form", "input", "button", "audio", "video", "source"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}


class EpubUnavailable(Exception):
    pass


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _normalize(value):
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _safe_member(base, href):
    href = (href or "").split("#", 1)[0].split("?", 1)[0]
    member = posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    if not href or member.startswith("/") or member == ".." or member.startswith("../"):
        raise EpubUnavailable("unsafe EPUB resource path")
    return member


def _path_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@lru_cache(maxsize=16)
def _verify_epub(path_text, expected_hash, size, mtime_ns):
    path = Path(path_text)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if not expected_hash or digest.hexdigest() != expected_hash:
        raise EpubUnavailable("EPUB identity check failed")
    with zipfile.ZipFile(path) as epub:
        if epub.testzip() is not None:
            raise EpubUnavailable("EPUB integrity check failed")
    return path


def _book_epub(row):
    raw_path = row["source_epub_path"]
    if not raw_path:
        raise EpubUnavailable("EPUB is not linked")
    path = Path(raw_path).resolve()
    if not _path_within(path, EPUB_ROOT) or not path.is_file() or path.suffix.lower() != ".epub":
        raise EpubUnavailable("EPUB link is unavailable")
    stat = path.stat()
    return _verify_epub(str(path), row["source_epub_sha256"], stat.st_size, stat.st_mtime_ns)


def _markdown_candidates(content):
    candidates = []
    blocks = re.split(r"\n\s*\n", content or "")
    for index, block in enumerate(blocks):
        value = block.strip()
        if not value or re.fullmatch(r"-+", value):
            continue
        if index == 0 and value.startswith("# "):
            continue  # generated section title, not a converter split boundary
        value = re.sub(r"^#{1,6}\s+", "", value)
        value = re.sub(r"(?m)^\s*(?:[-*]|\d+\.)\s+", "", value)
        value = value.replace("**", "").replace("`", "").replace("*", "")
        if value.startswith("[Image:") and value.endswith("]"):
            value = value[7:-1]
        value = _normalize(value)
        if len(value) >= 24:
            candidates.append(value)
        if len(candidates) >= 16:
            break
    return candidates


def _element_text(element):
    return _normalize(" ".join(element.itertext()))


def _element_path(root, target):
    parent = {child: node for node in root.iter() for child in node}
    parts = []
    node = target
    while node is not root:
        owner = parent.get(node)
        if owner is None:
            raise EpubUnavailable("EPUB locator could not be created")
        parts.append(str(list(owner).index(node)))
        node = owner
    return "/".join(reversed(parts))


def _find_boundary(root, content, after_index=-1):
    elements = [element for element in root.iter() if _local(element.tag) in BLOCK_TAGS]
    indexes = {element: index for index, element in enumerate(root.iter())}
    for candidate in _markdown_candidates(content):
        probe = candidate[:180]
        matches = []
        for element in elements:
            if indexes[element] <= after_index:
                continue
            text = _element_text(element)
            if text and (
                text.startswith(probe)
                or (len(text) >= 8 and probe.startswith(text[:180]))
            ):
                matches.append((len(text), element))
        if matches:
            return min(matches, key=lambda item: item[0])[1]
    raise EpubUnavailable("EPUB section boundary could not be located")


def _resolve_path(root, path_text):
    node = root
    if not path_text:
        return node
    try:
        for value in path_text.split("/"):
            node = list(node)[int(value)]
    except (ValueError, IndexError):
        raise EpubUnavailable("EPUB locator is invalid")
    return node


def _sanitize_attrs(element, tag, source_item, stable_id, names):
    attrs = {}
    for key, value in element.attrib.items():
        key = _local(key)
        if key in {"id", "class"}:
            cleaned = re.sub(r"[^A-Za-z0-9_:. -]", "", value)[:240]
            if cleaned:
                attrs[key] = cleaned
        elif key in {"alt", "title", "aria-label", "aria-describedby"}:
            attrs[key] = value[:1000]
        elif key in {"width", "height", "colspan", "rowspan", "start"} and re.fullmatch(r"\d{1,5}", value or ""):
            attrs[key] = value
    if tag == "img":
        member = _safe_member(source_item, element.attrib.get("src", ""))
        if member not in names or Path(member).suffix.lower() not in IMAGE_EXTENSIONS:
            raise EpubUnavailable("EPUB image resource is missing")
        encoded = quote(member, safe="/")
        attrs["src"] = f"/api/v2/study/sections/{quote(stable_id, safe='')}/epub-assets/{encoded}"
        attrs["loading"] = "eager"
        attrs["decoding"] = "async"
    elif tag == "a":
        href = element.attrib.get("href", "")
        if href.startswith("#") and re.fullmatch(r"#[A-Za-z0-9_:.-]+", href):
            attrs["href"] = href
    return attrs


def _clone_range(root, source_item, stable_id, names, start_element, end_element=None):
    ordered = list(root.iter())
    indexes = {element: index for index, element in enumerate(ordered)}
    subtree_end = {}

    def record_end(element):
        end = indexes[element]
        for child in element:
            end = max(end, record_end(child))
        subtree_end[element] = end
        return end

    record_end(root)
    start = indexes[start_element]
    end = indexes[end_element] if end_element is not None else len(ordered)
    if end <= start:
        raise EpubUnavailable("EPUB section range is invalid")

    def intersects(element):
        return subtree_end[element] >= start and indexes[element] < end

    def clone(element):
        if not intersects(element):
            return None
        source_tag = _local(element.tag)
        if source_tag in DROP_TAGS:
            return None
        tag = source_tag if source_tag in ALLOWED_TAGS else "div"
        copied = ET.Element(tag, _sanitize_attrs(element, tag, source_item, stable_id, names))
        if start <= indexes[element] < end:
            copied.text = element.text
        for child in element:
            child_copy = clone(child)
            if child_copy is not None:
                if subtree_end[child] >= start and subtree_end[child] < end:
                    child_copy.tail = child.tail
                copied.append(child_copy)
        return copied

    return clone(root)


def _inner_html(element):
    prefix = html.escape(element.text or "")
    return prefix + "".join(ET.tostring(child, encoding="unicode", method="html") for child in element)


def _section_row(conn, stable_id):
    return conn.execute(
        "SELECT s.id, s.stable_id, s.title, s.position, s.part, s.part_count, s.content, "
        "s.source_item, b.id AS book_id, b.slug AS book_slug, b.title AS book_title, "
        "b.source_epub_sha256, b.source_epub_path "
        "FROM sections s JOIN books b ON b.id = s.book_id WHERE s.stable_id = ?",
        (stable_id,),
    ).fetchone()


def get_reader_section(conn, stable_id):
    row = _section_row(conn, stable_id)
    if not row:
        return None
    fallback = {
        "stable_id": row["stable_id"], "title": row["title"], "book_title": row["book_title"],
        "reader_format": "markdown", "content": row["content"], "html": None,
        "locator": None,
    }
    try:
        epub_path = _book_epub(row)
        source_item = row["source_item"]
        if not source_item:
            raise EpubUnavailable("section has no EPUB spine item")
        with zipfile.ZipFile(epub_path) as epub:
            names = set(epub.namelist())
            if source_item not in names:
                raise EpubUnavailable("EPUB spine item is missing")
            root = ET.fromstring(epub.read(source_item))
            body = next((item for item in root.iter() if _local(item.tag) == "body"), root)
            start_element = body
            end_element = None
            if (row["part_count"] or 1) > 1:
                ordered = list(body.iter())
                last_index = -1
                parts = conn.execute(
                    "SELECT position, content FROM sections WHERE book_id = ? AND source_item = ? "
                    "ORDER BY position",
                    (row["book_id"], source_item),
                ).fetchall()
                for part_index, part_row in enumerate(parts):
                    if part_index == 0:
                        continue
                    boundary = _find_boundary(body, part_row["content"], after_index=last_index)
                    last_index = ordered.index(boundary)
                    if part_row["position"] <= row["position"]:
                        start_element = boundary
                    else:
                        end_element = boundary
                        break

            rendered = _clone_range(body, source_item, stable_id, names, start_element, end_element)
            if rendered is None:
                raise EpubUnavailable("EPUB section is empty")
            locator = f"{source_item}#path={_element_path(body, start_element)}"
            return {
                **fallback,
                "reader_format": "epub",
                "content": None,
                "html": f'<div class="epub-reader-content">{_inner_html(rendered)}</div>',
                "locator": locator,
            }
    except (EpubUnavailable, OSError, zipfile.BadZipFile, ET.ParseError):
        return fallback


def get_reader_asset(conn, stable_id, member):
    row = _section_row(conn, stable_id)
    if not row:
        raise EpubUnavailable("section not found")
    epub_path = _book_epub(row)
    member = posixpath.normpath(member)
    if member.startswith("/") or member == ".." or member.startswith("../"):
        raise EpubUnavailable("unsafe EPUB resource path")
    extension = Path(member).suffix.lower()
    if extension not in IMAGE_EXTENSIONS:
        raise EpubUnavailable("EPUB resource type is not allowed")
    with zipfile.ZipFile(epub_path) as epub:
        if member not in epub.namelist():
            raise EpubUnavailable("EPUB resource not found")
        data = epub.read(member)
    content_type = mimetypes.guess_type(member)[0] or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise EpubUnavailable("EPUB resource type is not allowed")
    return data, content_type
