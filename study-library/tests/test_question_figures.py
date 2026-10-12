"""Structural figure resolution for practice questions."""

import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import question_figures


# Mirrors the publisher's real markup: the question is an <li> in the outer
# <ol>, the figure sits between the stem and a nested options <ol>.
CHAPTER = """<html><body>
<ol class="calibre_51"><li value="1" class="calibre_26">Identify the connector in the picture.
<p><img src="images/00046.jpg"/></p>
<ol class="calibre_52"><li value="1">F-type</li><li value="2">BNC</li></ol></li></ol>
<ol class="calibre_1"><li value="2" class="calibre_26">A question with no figure at all.
<ol class="calibre_52"><li value="1">Yes</li><li value="2">No</li></ol></li></ol>
<ol class="calibre_1"><li value="3" class="calibre_26">A question whose option carries the art.
<ol class="calibre_52"><li value="1">Plain</li><li value="2"><img src="images/00099.jpg"/></li></ol></li></ol>
<ol class="calibre_1"><li value="4" class="calibre_26">A question pointing at a missing file.
<p><img src="images/nope.jpg"/></p>
<ol class="calibre_52"><li value="1">Yes</li></ol></li></ol>
</body></html>"""


def _epub():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("chapter.html", CHAPTER)
        archive.writestr("images/00046.jpg", b"\xff\xd8\xff\xe0jpeg")
        archive.writestr("images/00099.jpg", b"\xff\xd8\xff\xe0jpeg")
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


class TestParseDocument(unittest.TestCase):
    def setUp(self):
        self.epub = _epub()
        self.names = set(self.epub.namelist())

    def test_question_level_image_is_resolved(self):
        figures = question_figures._parse_document(self.epub, "chapter.html", self.names)
        self.assertEqual(figures[1], "images/00046.jpg")

    def test_question_without_figure_is_absent(self):
        figures = question_figures._parse_document(self.epub, "chapter.html", self.names)
        self.assertNotIn(2, figures)

    def test_option_image_does_not_become_the_question_figure(self):
        # The art belongs to answer choice B, not to the stem; crediting it
        # would show one option's picture as if it were the question's.
        figures = question_figures._parse_document(self.epub, "chapter.html", self.names)
        self.assertNotIn(3, figures)

    def test_image_missing_from_the_archive_is_not_claimed(self):
        figures = question_figures._parse_document(self.epub, "chapter.html", self.names)
        self.assertNotIn(4, figures)


class TestClaimsFigure(unittest.TestCase):
    def test_prose_promising_a_picture(self):
        self.assertTrue(question_figures.claims_figure("What is shown in the following image?", []))
        self.assertTrue(question_figures.claims_figure("Based on the illustration shown, what is A?", []))

    def test_prose_that_only_looks_visual(self):
        self.assertFalse(question_figures.claims_figure("What is true about this graphics type?", []))
        self.assertFalse(
            question_figures.claims_figure("What is the throughput of a device in this port?", [])
        )


class TestFigurePayload(unittest.TestCase):
    def test_payload_points_at_the_sanitized_asset_route(self):
        payload = question_figures.figure_payload("aplus-practice-tests:0016", "images/00046.jpg")
        self.assertEqual(payload["member"], "images/00046.jpg")
        self.assertEqual(
            payload["url"],
            "/api/v2/study/sections/aplus-practice-tests%3A0016/epub-assets/images/00046.jpg",
        )

    def test_missing_pieces_yield_no_payload(self):
        self.assertIsNone(question_figures.figure_payload(None, "images/00046.jpg"))
        self.assertIsNone(question_figures.figure_payload("aplus-practice-tests:0016", None))


if __name__ == "__main__":
    unittest.main()
