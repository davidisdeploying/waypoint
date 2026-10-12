import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {BookReader, type ReaderBook} from "./BookReader";
import {queries} from "./api";

const book: ReaderBook = {
  slug: "review-guide",
  title: "A+ Review Guide",
  creator: "Author",
  original_epub_linked: true,
  reader_sections: [
    {stable_id: "review:1", title: "Mobile Devices", position: 1, part: 1, part_count: 1},
    {stable_id: "review:2", title: "Networking", position: 2, part: 1, part_count: 1},
  ],
};

beforeEach(() => {
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    },
  });
});

function renderReader() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return render(
    <QueryClientProvider client={client}>
      <BookReader book={book} onClose={() => undefined} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  document.body.removeAttribute("style");
  document.getElementById("root")?.removeAttribute("aria-hidden");
  document.getElementById("root")?.removeAttribute("inert");
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("BookReader", () => {
  it("navigates original EPUB sections and never renders the Markdown fallback", async () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    vi.spyOn(queries, "readerSection").mockImplementation(async (stableId) => ({
      stable_id: stableId,
      title: stableId === "review:1" ? "Mobile Devices" : "Networking",
      book_title: book.title,
      reader_format: "epub",
      html: `<div class="epub-reader-content"><p>${stableId}</p></div>`,
      content: null,
      locator: "OEBPS/ch.xhtml#path=body",
    }));

    renderReader();
    expect(await screen.findByText("review:1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: "Next EPUB section"}));
    expect(await screen.findByText("review:2")).toBeInTheDocument();
    expect(localStorage.getItem("waypoint:book-reader-section:review-guide")).toBe("1");
    expect(screen.getByText(/Book \d+%/)).toBeInTheDocument();
  });

  it("fails closed instead of displaying generated Markdown", async () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    vi.spyOn(queries, "readerSection").mockResolvedValue({
      stable_id: "review:1",
      title: "Mobile Devices",
      book_title: book.title,
      reader_format: "markdown",
      html: null,
      content: "Generated Markdown must remain hidden.",
      locator: null,
    });

    renderReader();
    expect(await screen.findByRole("alert")).toHaveTextContent("original EPUB section is unavailable");
    expect(screen.queryByText("Generated Markdown must remain hidden.")).not.toBeInTheDocument();
    await waitFor(() => expect(queries.readerSection).toHaveBeenCalledWith("review:1"));
  });
});
