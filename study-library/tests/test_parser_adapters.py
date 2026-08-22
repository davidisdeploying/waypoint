import unittest

from ingest.adapters import (
    ParserAdapterError,
    build_parser_adapter,
    parser_adapter_names,
)
from ingest.sources import get_sources


class TestParserAdapters(unittest.TestCase):
    def test_registry_is_explicit_and_unknown_adapter_fails_closed(self):
        self.assertIn("inline-prefixed-objectives-v1", parser_adapter_names())
        with self.assertRaisesRegex(ParserAdapterError, "unknown parser adapter"):
            build_parser_adapter("import-anything", "book", ["EX-1"])

    def test_inline_adapter_uses_manifest_exam_codes_not_aplus_constants(self):
        adapter = build_parser_adapter(
            "inline-prefixed-objectives-v1", "network-book", ["N10-009"]
        )
        result = adapter.consume(
            "Networking",
            "✓ N10-009-1.1 Explain networking concepts.\n"
            "✓ 009-2.3 Configure a network appliance.",
        )
        self.assertEqual(
            [(hit.exam_code, hit.code) for hit in result.objectives],
            [("N10-009", "1.1"), ("N10-009", "2.3")],
        )

    def test_divider_adapter_keeps_state_within_one_book(self):
        adapter = build_parser_adapter(
            "divider-bare-objectives-domain-v1",
            "review-book",
            ["N10-009"],
        )
        divider = adapter.consume("PART I", "Current exam N10-009")
        self.assertFalse(divider.objectives)
        chapter = adapter.consume(
            "Chapter 1 Networking Concepts",
            "✔ 1.1 Explain networking concepts.",
        )
        self.assertEqual(chapter.objectives[0].exam_code, "N10-009")
        self.assertEqual(chapter.domains[0].name, "Networking Concepts")
        self.assertEqual(chapter.domains[0].code, "1")

        fresh = build_parser_adapter(
            "divider-bare-objectives-domain-v1",
            "another-book",
            ["N10-009"],
        )
        self.assertFalse(
            fresh.consume(
                "Chapter 1 Networking Concepts",
                "✔ 1.1 Explain networking concepts.",
            ).objectives
        )

    def test_ambiguous_short_exam_prefix_is_rejected(self):
        with self.assertRaisesRegex(ParserAdapterError, "ambiguous"):
            build_parser_adapter(
                "inline-prefixed-objectives-v1",
                "book",
                ["EX-101", "ALT-101"],
            )

    def test_manifest_source_carries_parser_into_ingest(self):
        manifest = {
            "sources": [{
                "source_key": "book",
                "title": "Book",
                "book_slug": "book",
                "ingest": {
                    "kind": "review",
                    "parser": "divider-bare-objectives-v1",
                    "dir": "/books/book",
                },
            }]
        }
        sources = get_sources(manifest)
        self.assertEqual(sources[0]["parser"], "divider-bare-objectives-v1")
        self.assertEqual(sources[0]["dir"], "/books/book")


if __name__ == "__main__":
    unittest.main()
