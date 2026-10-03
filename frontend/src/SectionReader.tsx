import {useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode} from "react";
import {createPortal} from "react-dom";

function inlineMarkdown(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) => {
    const bold = part.startsWith("**") && part.endsWith("**");
    const content = bold ? part.slice(2, -2) : part;
    return bold
      ? <strong key={`${part}-${index}`}>{content}</strong>
      : <span key={`${part}-${index}`}>{content}</span>;
  });
}

function isBlockStart(line: string) {
  return /^(#{1,6}\s+|[-*]\s+|\d+\.\s+|\[Image:|---+$)/.test(line);
}

export function ReaderText({content, paginated = false}: {content: string; paginated?: boolean}) {
  const lines = content.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }
    if (/^---+$/.test(line)) {
      blocks.push(<hr key={`rule-${index}`} />);
      index += 1;
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const level = Math.min(heading[1].length + 1, 6);
      const Tag = `h${level}` as "h2" | "h3" | "h4" | "h5" | "h6";
      blocks.push(<Tag key={`heading-${index}`}>{inlineMarkdown(heading[2])}</Tag>);
      index += 1;
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul key={`ul-${index}`}>
          {items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{inlineMarkdown(item)}</li>)}
        </ul>,
      );
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ol key={`ol-${index}`}>
          {items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{inlineMarkdown(item)}</li>)}
        </ol>,
      );
      continue;
    }
    if (/^\[Image:/.test(line)) {
      blocks.push(<aside className="reading-figure-note" key={`image-${index}`}>{line.slice(1, -1)}</aside>);
      index += 1;
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index].trim())) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={`paragraph-${index}`}>{inlineMarkdown(paragraph.join(" "))}</p>);
  }

  return <div className={paginated ? "section-reader-text paginated" : "section-reader-text"}>{blocks}</div>;
}

export function ReaderHtml({html}: {html: string}) {
  // Study Library emits an allowlisted, script-free fragment from a hash-verified EPUB.
  return <div className="section-reader-text paginated" dangerouslySetInnerHTML={{__html: html}} />;
}

const READER_PREFERENCES_KEY = "waypoint:reader-preferences:v1";

type ReaderTheme = "paper" | "warm" | "night";
type ReaderFont = "serif" | "sans";
type ReaderMeasure = "focused" | "wide";

interface ReaderPreferences {
  fontSize: number;
  lineHeight: number;
  theme: ReaderTheme;
  font: ReaderFont;
  measure: ReaderMeasure;
}

const DEFAULT_READER_PREFERENCES: ReaderPreferences = {
  fontSize: 20,
  lineHeight: 1.62,
  theme: "paper",
  font: "serif",
  measure: "focused",
};

function savedReaderPreferences(): ReaderPreferences {
  try {
    const saved = JSON.parse(localStorage.getItem(READER_PREFERENCES_KEY) ?? "{}") as Partial<ReaderPreferences>;
    return {
      fontSize: typeof saved.fontSize === "number" && saved.fontSize >= 16 && saved.fontSize <= 28 ? saved.fontSize : DEFAULT_READER_PREFERENCES.fontSize,
      lineHeight: [1.45, 1.62, 1.8].includes(saved.lineHeight ?? 0) ? saved.lineHeight! : DEFAULT_READER_PREFERENCES.lineHeight,
      theme: ["paper", "warm", "night"].includes(saved.theme ?? "") ? saved.theme! : DEFAULT_READER_PREFERENCES.theme,
      font: ["serif", "sans"].includes(saved.font ?? "") ? saved.font! : DEFAULT_READER_PREFERENCES.font,
      measure: ["focused", "wide"].includes(saved.measure ?? "") ? saved.measure! : DEFAULT_READER_PREFERENCES.measure,
    };
  } catch {
    return DEFAULT_READER_PREFERENCES;
  }
}

function storageKey(sectionId: string) {
  return `waypoint:section-reader-page:${sectionId}`;
}

function savedReaderPage(sectionId: string) {
  try {
    const saved = localStorage.getItem(storageKey(sectionId)) ?? sessionStorage.getItem(storageKey(sectionId));
    return Number.parseInt(saved ?? "0", 10) || 0;
  } catch {
    return 0;
  }
}

export function pageDeltaForGesture(startX: number, startY: number, endX: number, endY: number) {
  const horizontal = endX - startX;
  const vertical = endY - startY;
  if (Math.abs(horizontal) < 44 || Math.abs(horizontal) < Math.abs(vertical) * 1.15) return 0;
  return horizontal < 0 ? 1 : -1;
}

export function SectionReader({
  sectionId,
  title,
  bookTitle,
  content,
  html,
  loading,
  error,
  onClose,
  readerLabel,
  navigation,
  onPageChange,
}: {
  sectionId: string;
  title: string;
  bookTitle: string;
  content?: string;
  html?: string;
  loading?: boolean;
  error?: unknown;
  onClose: () => void;
  readerLabel?: string;
  navigation?: ReactNode;
  onPageChange?: (page: number, pageCount: number) => void;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const gestureRef = useRef<{pointerId: number; x: number; y: number} | null>(null);
  const pageRef = useRef(savedReaderPage(sectionId));
  const pageCountRef = useRef(1);
  const [page, setPage] = useState(pageRef.current);
  const [pageCount, setPageCount] = useState(1);
  const [pageWidth, setPageWidth] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [preferences, setPreferences] = useState(savedReaderPreferences);
  const hasReading = Boolean(html || content);

  const updatePreferences = (next: Partial<ReaderPreferences>) => {
    setPreferences((current) => ({...current, ...next}));
  };

  const goToPage = (nextPage: number) => {
    const bounded = Math.max(0, Math.min(pageCountRef.current - 1, nextPage));
    pageRef.current = bounded;
    setPage(bounded);
  };

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const savedPage = savedReaderPage(sectionId);
    pageRef.current = savedPage;
    pageCountRef.current = 1;
    setPage(savedPage);
    setPageCount(1);
  }, [sectionId]);

  useEffect(() => {
    const pageScrollY = window.scrollY;
    const root = document.getElementById("root");
    const previousBodyStyle = {
      position: document.body.style.position,
      top: document.body.style.top,
      left: document.body.style.left,
      right: document.body.style.right,
      width: document.body.style.width,
      overflow: document.body.style.overflow,
    };
    const previousAriaHidden = root?.getAttribute("aria-hidden");
    const previouslyInert = root?.hasAttribute("inert") ?? false;

    Object.assign(document.body.style, {
      position: "fixed",
      top: `-${pageScrollY}px`,
      left: "0",
      right: "0",
      width: "100%",
      overflow: "hidden",
    });
    root?.setAttribute("aria-hidden", "true");
    root?.setAttribute("inert", "");
    closeRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
      if (event.key === "ArrowLeft") goToPage(pageRef.current - 1);
      if (event.key === "ArrowRight") goToPage(pageRef.current + 1);
    };
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      Object.assign(document.body.style, previousBodyStyle);
      if (root) {
        if (previousAriaHidden == null) root.removeAttribute("aria-hidden");
        else root.setAttribute("aria-hidden", previousAriaHidden);
        if (!previouslyInert) root.removeAttribute("inert");
      }
      window.scrollTo(0, pageScrollY);
    };
  }, []);

  useLayoutEffect(() => {
    if (!hasReading || !frameRef.current) return;
    const frame = frameRef.current;
    const columns = frame.querySelector<HTMLElement>(".section-reader-text.paginated");
    if (!columns) return;
    let measurementFrame = 0;
    const measure = () => {
      window.cancelAnimationFrame(measurementFrame);
      const width = frame.clientWidth;
      if (!width) return;
      setPageWidth(width);
      columns.style.setProperty("--reader-page-width", `${width}px`);
      measurementFrame = window.requestAnimationFrame(() => {
        const gap = 40;
        const measuredCount = Math.max(1, Math.ceil((columns.scrollWidth + gap) / (width + gap)));
        pageCountRef.current = measuredCount;
        setPageCount(measuredCount);
        goToPage(pageRef.current);
      });
    };
    measure();
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    resizeObserver?.observe(frame);
    const images = Array.from(columns.querySelectorAll("img"));
    images.forEach((image) => image.addEventListener("load", measure));
    window.addEventListener("resize", measure);
    void document.fonts?.ready.then(measure);
    return () => {
      resizeObserver?.disconnect();
      images.forEach((image) => image.removeEventListener("load", measure));
      window.removeEventListener("resize", measure);
      window.cancelAnimationFrame(measurementFrame);
    };
  }, [hasReading, html, content, sectionId, preferences]);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(sectionId), String(page));
    } catch {
      // The reader still works when private storage is unavailable.
    }
  }, [page, sectionId]);

  useEffect(() => {
    try {
      localStorage.setItem(READER_PREFERENCES_KEY, JSON.stringify(preferences));
    } catch {
      // Display preferences are optional when private storage is unavailable.
    }
  }, [preferences]);

  useEffect(() => {
    onPageChange?.(page, pageCount);
  }, [onPageChange, page, pageCount]);

  const progress = ((page + 1) / pageCount) * 100;
  const pageOffset = page * (pageWidth + 40);
  const readerStyle = {
    "--reader-font-size": `${preferences.fontSize}px`,
    "--reader-line-height": String(preferences.lineHeight),
    "--reader-max-width": preferences.measure === "wide" ? "880px" : "720px",
  } as CSSProperties;

  return createPortal(
    <div
      className={`section-reader-overlay reader-theme-${preferences.theme} reader-font-${preferences.font}`}
      style={readerStyle}
      role="dialog"
      aria-modal="true"
      aria-labelledby="section-reader-title"
    >
      <header className="section-reader-header">
        <div className="section-reader-heading">
          <span className="section-reader-kicker">{readerLabel ?? `Reading from ${bookTitle}`}</span>
          <h1 id="section-reader-title">{title}</h1>
        </div>
        <div className="section-reader-header-actions">
          <button
            className="section-reader-settings-button"
            type="button"
            aria-expanded={settingsOpen}
            aria-controls="section-reader-settings"
            onClick={() => setSettingsOpen((open) => !open)}
          >
            <span aria-hidden="true">Aa</span>
            <span>Display</span>
          </button>
          <button ref={closeRef} className="section-reader-close" type="button" onClick={onClose} aria-label="Close reader and return to review">
            <span aria-hidden="true">×</span>
            <span>Done</span>
          </button>
        </div>
        {navigation ? <div className="section-reader-navigation">{navigation}</div> : null}
        {settingsOpen ? (
          <section id="section-reader-settings" className="section-reader-settings" aria-label="Reading display settings">
            <div className="reader-setting-group">
              <span>Text size</span>
              <div className="reader-stepper">
                <button type="button" onClick={() => updatePreferences({fontSize: Math.max(16, preferences.fontSize - 2)})} disabled={preferences.fontSize === 16} aria-label="Decrease text size">A−</button>
                <output aria-live="polite">{preferences.fontSize}px</output>
                <button type="button" onClick={() => updatePreferences({fontSize: Math.min(28, preferences.fontSize + 2)})} disabled={preferences.fontSize === 28} aria-label="Increase text size">A+</button>
              </div>
            </div>
            <label className="reader-setting-group">
              <span>Typeface</span>
              <select aria-label="Typeface" value={preferences.font} onChange={(event) => updatePreferences({font: event.target.value as ReaderFont})}>
                <option value="serif">Book serif</option>
                <option value="sans">Clean sans</option>
              </select>
            </label>
            <label className="reader-setting-group">
              <span>Line spacing</span>
              <select aria-label="Line spacing" value={preferences.lineHeight} onChange={(event) => updatePreferences({lineHeight: Number(event.target.value)})}>
                <option value="1.45">Compact</option>
                <option value="1.62">Comfortable</option>
                <option value="1.8">Relaxed</option>
              </select>
            </label>
            <label className="reader-setting-group">
              <span>Page width</span>
              <select aria-label="Page width" value={preferences.measure} onChange={(event) => updatePreferences({measure: event.target.value as ReaderMeasure})}>
                <option value="focused">Focused</option>
                <option value="wide">Wide</option>
              </select>
            </label>
            <fieldset className="reader-setting-group reader-theme-options">
              <legend>Theme</legend>
              {(["paper", "warm", "night"] as ReaderTheme[]).map((theme) => (
                <button key={theme} type="button" aria-pressed={preferences.theme === theme} onClick={() => updatePreferences({theme})}>{theme}</button>
              ))}
            </fieldset>
            <button className="reader-reset-button" type="button" onClick={() => setPreferences(DEFAULT_READER_PREFERENCES)}>Reset</button>
          </section>
        ) : null}
        <div className="section-reader-progress" aria-label={`${Math.round(progress)}% through section`}>
          <span style={{width: `${progress}%`}} />
        </div>
      </header>
      <div className="section-reader-stage">
        {loading ? <p className="section-reader-status">Opening your section…</p> : null}
        {error ? <p className="notice error section-reader-error" role="alert">{error instanceof Error ? error.message : "This section could not be opened."}</p> : null}
        {hasReading ? (
          <>
            <main
              className="section-reader-page-viewport"
              aria-label={`Page ${page + 1} of ${pageCount}`}
              onPointerDown={(event) => {
                if (event.isPrimary === false) return;
                gestureRef.current = {pointerId: event.pointerId, x: event.clientX, y: event.clientY};
                event.currentTarget.setPointerCapture?.(event.pointerId);
              }}
              onPointerUp={(event) => {
                const gesture = gestureRef.current;
                gestureRef.current = null;
                if (!gesture || gesture.pointerId !== event.pointerId) return;
                const delta = pageDeltaForGesture(gesture.x, gesture.y, event.clientX, event.clientY);
                if (delta) goToPage(pageRef.current + delta);
              }}
              onPointerCancel={() => { gestureRef.current = null; }}
            >
              <div ref={frameRef} className="section-reader-frame">
                <div className="section-reader-page-track" style={{transform: `translate3d(-${pageOffset}px, 0, 0)`}}>
                  {html ? <ReaderHtml html={html} /> : <ReaderText content={content!} paginated />}
                </div>
              </div>
            </main>
            <footer className="section-reader-controls">
              <button type="button" onClick={() => goToPage(pageRef.current - 1)} disabled={page === 0} aria-label="Previous page">‹</button>
              <span aria-live="polite">Page {page + 1} of {pageCount}</span>
              <button type="button" onClick={() => goToPage(pageRef.current + 1)} disabled={page >= pageCount - 1} aria-label="Next page">›</button>
            </footer>
          </>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
