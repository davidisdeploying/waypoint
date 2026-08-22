import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {useState} from "react";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {pageDeltaForGesture, ReaderHtml, ReaderText, SectionReader} from "./SectionReader";

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

afterEach(() => {
  cleanup();
  document.body.removeAttribute("style");
  document.getElementById("root")?.removeAttribute("aria-hidden");
  document.getElementById("root")?.removeAttribute("inert");
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("SectionReader", () => {
  it("renders book Markdown as readable structure", () => {
    render(<ReaderText content={"# Mobile devices\n\n**Battery safety** matters.\n\n- Check power\n- Remove the pack"} />);
    expect(screen.getByRole("heading", {name: "Mobile devices"})).toBeInTheDocument();
    expect(screen.getByText("Battery safety").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("renders sanitized EPUB figures and their authentic images", () => {
    render(<ReaderHtml html={'<div class="epub-reader-content"><figure><img src="/figure.jpg" alt="Airflow diagram"><figcaption>Figure 5.29</figcaption></figure></div>'} />);
    expect(screen.getByRole("img", {name: "Airflow diagram"})).toHaveAttribute("src", "/figure.jpg");
    expect(screen.getByText("Figure 5.29")).toBeInTheDocument();
  });

  it("locks the review page and restores its exact scroll position when closed", () => {
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    Object.defineProperty(window, "scrollY", {configurable: true, value: 742});
    function Harness() {
      const [open, setOpen] = useState(true);
      return open ? (
        <SectionReader
          sectionId="section-1"
          title="Battery monitoring"
          bookTitle="A+ Review Guide"
          content="A full section"
          onClose={() => setOpen(false)}
        />
      ) : <p>Review restored</p>;
    }
    render(
      <Harness />,
    );
    expect(screen.getByRole("dialog", {name: "Battery monitoring"})).toBeInTheDocument();
    expect(document.body.style.position).toBe("fixed");
    fireEvent.click(screen.getByRole("button", {name: /close reader/i}));
    expect(screen.getByText("Review restored")).toBeInTheDocument();
    expect(document.body.style.position).toBe("");
    expect(scrollTo).toHaveBeenCalledWith(0, 742);
  });

  it("advances one locked page per swipe and remembers that page", async () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    Object.defineProperty(window, "scrollY", {configurable: true, value: 315});
    const {unmount} = render(
      <SectionReader
        sectionId="section-remembered"
        title="Storage"
        bookTitle="A+ Review Guide"
        content="Long reading"
        onClose={() => undefined}
      />,
    );
    const frame = document.querySelector(".section-reader-frame") as HTMLDivElement;
    const columns = document.querySelector(".section-reader-text.paginated") as HTMLDivElement;
    Object.defineProperty(frame, "clientWidth", {configurable: true, value: 320});
    Object.defineProperty(columns, "scrollWidth", {configurable: true, value: 1040});
    fireEvent(window, new Event("resize"));
    await waitFor(() => expect(screen.getByText("Page 1 of 3")).toBeInTheDocument());

    expect(pageDeltaForGesture(300, 300, 210, 304)).toBe(1);
    expect(pageDeltaForGesture(250, 300, 245, 220)).toBe(0);
    fireEvent.click(screen.getByRole("button", {name: "Next page"}));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(localStorage.getItem("waypoint:section-reader-page:section-remembered")).toBe("1");
    expect(screen.getByLabelText("67% through section")).toBeInTheDocument();

    unmount();
    expect(window.scrollTo).toHaveBeenCalledWith(0, 315);
  });

  it("reflows EPUB and study readings with persistent display controls", () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    render(
      <SectionReader
        sectionId="shared-reader"
        title="Network services"
        bookTitle="A+ Review Guide"
        html={'<div class="epub-reader-content"><p>Shared original section</p></div>'}
        onClose={() => undefined}
      />,
    );

    fireEvent.click(screen.getByRole("button", {name: "Display"}));
    fireEvent.click(screen.getByRole("button", {name: "Increase text size"}));
    fireEvent.click(screen.getByRole("button", {name: "night"}));
    fireEvent.change(screen.getByLabelText("Line spacing"), {target: {value: "1.8"}});

    expect(screen.getByRole("dialog")).toHaveClass("reader-theme-night");
    expect(screen.getByText("Shared original section").closest(".section-reader-text")).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("waypoint:reader-preferences:v1") ?? "{}")).toMatchObject({
      fontSize: 22,
      lineHeight: 1.8,
      theme: "night",
    });
  });
});
