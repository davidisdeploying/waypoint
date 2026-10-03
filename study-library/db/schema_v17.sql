-- Link each admitted Markdown book to its immutable presentation EPUB.
-- The EPUB remains optional so existing knowledge/search ingestion degrades safely.

CREATE INDEX IF NOT EXISTS idx_books_source_epub_sha256
    ON books(source_epub_sha256);
