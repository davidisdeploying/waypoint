import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from lib import api_logic, db, epub_reader


class TestEpubReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.epub_path = self.root / "book.epub"
        xhtml = """<?xml version="1.0" encoding="utf-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml"><body>
          <h1>Cooling</h1><p>Opening paragraph belongs only to part one.</p>
          <p>Boundary paragraph begins part two and explains airflow.</p>
          <script>alert('no')</script>
          <figure id="fig1"><img src="graphics/airflow.jpg" alt="Airflow diagram" onerror="bad()"/>
          <figcaption>Figure 5.29 Placement of fans</figcaption></figure>
        </body></html>"""
        with zipfile.ZipFile(self.epub_path, "w") as epub:
            epub.writestr("OEBPS/ch.xhtml", xhtml)
            epub.writestr("OEBPS/graphics/airflow.jpg", b"jpeg-fixture")
        digest = hashlib.sha256(self.epub_path.read_bytes()).hexdigest()

        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        ts = "2026-08-09T00:00:00+00:00"
        self.conn.execute(
            "INSERT INTO books(slug,title,source_dir,source_epub_sha256,source_epub_path,created_at,updated_at) "
            "VALUES ('fixture','Fixture','/fixture',?,?,?,?)",
            (digest, str(self.epub_path), ts, ts),
        )
        book_id = self.conn.execute("SELECT id FROM books").fetchone()["id"]
        sections = [
            ("fixture:0001", 1, 1, "Part one", "# Part one\n\nOpening paragraph belongs only to part one."),
            ("fixture:0002", 2, 2, "Part two", "# Part two\n\nBoundary paragraph begins part two and explains airflow."),
        ]
        for stable_id, position, part, title, content in sections:
            self.conn.execute(
                "INSERT INTO sections(stable_id,book_id,position,source_position,part,part_count,title,"
                "source_item,source_path,word_count,content,content_sha256,created_at,updated_at) "
                "VALUES (?,?,?,1,?,2,?,'OEBPS/ch.xhtml',?,10,?,'hash',?,?)",
                (stable_id, book_id, position, part, title, f"{position}.md", content, ts, ts),
            )
        self.conn.commit()
        self.previous_root = epub_reader.EPUB_ROOT
        epub_reader.EPUB_ROOT = self.root.resolve()
        epub_reader._verify_epub.cache_clear()

    def tearDown(self):
        epub_reader.EPUB_ROOT = self.previous_root
        epub_reader._verify_epub.cache_clear()
        self.conn.close()
        self.tmp.cleanup()

    def test_part_range_uses_epub_html_and_authentic_image(self):
        part_one = epub_reader.get_reader_section(self.conn, "fixture:0001")
        self.assertEqual(part_one["reader_format"], "epub")
        self.assertIn("Opening paragraph", part_one["html"])
        self.assertNotIn("Boundary paragraph", part_one["html"])

        part_two = epub_reader.get_reader_section(self.conn, "fixture:0002")
        self.assertEqual(part_two["reader_format"], "epub")
        self.assertIn("Boundary paragraph", part_two["html"])
        self.assertIn("Airflow diagram", part_two["html"])
        self.assertIn("epub-assets/OEBPS/graphics/airflow.jpg", part_two["html"])
        self.assertNotIn("Opening paragraph", part_two["html"])
        self.assertNotIn("script", part_two["html"].lower())
        self.assertNotIn("onerror", part_two["html"].lower())
        self.assertIn("OEBPS/ch.xhtml#path=", part_two["locator"])

    def test_only_image_assets_can_be_read(self):
        data, content_type = epub_reader.get_reader_asset(
            self.conn, "fixture:0002", "OEBPS/graphics/airflow.jpg"
        )
        self.assertEqual(data, b"jpeg-fixture")
        self.assertEqual(content_type, "image/jpeg")
        with self.assertRaises(epub_reader.EpubUnavailable):
            epub_reader.get_reader_asset(self.conn, "fixture:0002", "OEBPS/ch.xhtml")
        with self.assertRaises(epub_reader.EpubUnavailable):
            epub_reader.get_reader_asset(self.conn, "fixture:0002", "../book.epub")

    def test_unlinked_epub_falls_back_to_markdown(self):
        self.conn.execute("UPDATE books SET source_epub_path = NULL")
        result = epub_reader.get_reader_section(self.conn, "fixture:0002")
        self.assertEqual(result["reader_format"], "markdown")
        self.assertIn("Boundary paragraph", result["content"])

    def test_book_catalog_exposes_ordered_reader_sections_without_epub_path(self):
        books = api_logic.list_books(self.conn)

        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["original_epub_linked"], 1)
        self.assertNotIn("source_epub_path", books[0])
        self.assertEqual(
            [item["stable_id"] for item in books[0]["reader_sections"]],
            ["fixture:0001", "fixture:0002"],
        )
        self.assertEqual(books[0]["reader_sections"][1]["part"], 2)


if __name__ == "__main__":
    unittest.main()
