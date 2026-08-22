import {useEffect, useMemo, useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {queries} from "./api";
import {SectionReader} from "./SectionReader";

export interface ReaderBookSection {
  stable_id: string;
  title: string;
  position: number;
  part: number | null;
  part_count: number | null;
}

export interface ReaderBook {
  slug: string;
  title: string;
  creator: string;
  original_epub_linked: number | boolean;
  reader_sections: ReaderBookSection[];
}

function sectionStorageKey(slug: string) {
  return `waypoint:book-reader-section:${slug}`;
}

function savedSectionIndex(book: ReaderBook) {
  try {
    const value = Number.parseInt(localStorage.getItem(sectionStorageKey(book.slug)) ?? sessionStorage.getItem(sectionStorageKey(book.slug)) ?? "0", 10);
    return Math.max(0, Math.min(book.reader_sections.length - 1, value || 0));
  } catch {
    return 0;
  }
}

export function BookReader({book, onClose}: {book: ReaderBook; onClose: () => void}) {
  const [sectionIndex, setSectionIndex] = useState(() => savedSectionIndex(book));
  const [pagePosition, setPagePosition] = useState({page: 0, pageCount: 1});
  const section = book.reader_sections[sectionIndex];
  const sectionQuery = useQuery({
    queryKey: ["reader-section", section?.stable_id],
    queryFn: () => queries.readerSection(section!.stable_id),
    enabled: Boolean(section),
  });

  useEffect(() => {
    try {
      localStorage.setItem(sectionStorageKey(book.slug), String(sectionIndex));
    } catch {
      // Reading remains available when private storage is unavailable.
    }
  }, [book.slug, sectionIndex]);

  const overallProgress = Math.round(
    ((sectionIndex + (pagePosition.page + 1) / Math.max(1, pagePosition.pageCount)) / Math.max(1, book.reader_sections.length)) * 100,
  );

  const originalEpubError = useMemo(() => {
    if (!section) return new Error("This EPUB has no readable sections.");
    if (sectionQuery.error) return sectionQuery.error;
    if (sectionQuery.data && sectionQuery.data.reader_format !== "epub") {
      return new Error("The original EPUB section is unavailable. The Markdown knowledge-base copy is intentionally not shown here.");
    }
    return undefined;
  }, [section, sectionQuery.data, sectionQuery.error]);

  const selectSection = (nextIndex: number) => {
    setSectionIndex(Math.max(0, Math.min(book.reader_sections.length - 1, nextIndex)));
  };

  const navigation = (
    <nav className="epub-book-navigation" aria-label="EPUB section navigation">
      <button
        type="button"
        onClick={() => selectSection(sectionIndex - 1)}
        disabled={sectionIndex === 0}
        aria-label="Previous EPUB section"
      >
        ‹ <span>Previous section</span>
      </button>
      <label>
        <span>Section {sectionIndex + 1} of {book.reader_sections.length}</span>
        <select
          aria-label="Choose EPUB section"
          value={sectionIndex}
          onChange={(event) => selectSection(Number(event.target.value))}
        >
          {book.reader_sections.map((item, index) => (
            <option key={item.stable_id} value={index}>{item.title}</option>
          ))}
        </select>
      </label>
      <button
        type="button"
        onClick={() => selectSection(sectionIndex + 1)}
        disabled={sectionIndex >= book.reader_sections.length - 1}
        aria-label="Next EPUB section"
      >
        <span>Next section</span> ›
      </button>
      <span className="epub-book-progress" aria-live="polite">Book {overallProgress}%</span>
    </nav>
  );

  return (
    <SectionReader
      sectionId={section?.stable_id ?? book.slug}
      title={section?.title ?? book.title}
      bookTitle={book.title}
      html={sectionQuery.data?.reader_format === "epub" ? sectionQuery.data.html ?? undefined : undefined}
      loading={sectionQuery.isLoading}
      error={originalEpubError}
      onClose={onClose}
      readerLabel={`Original EPUB · ${book.title}`}
      navigation={navigation}
      onPageChange={(page, pageCount) => setPagePosition((current) => (
        current.page === page && current.pageCount === pageCount ? current : {page, pageCount}
      ))}
    />
  );
}
