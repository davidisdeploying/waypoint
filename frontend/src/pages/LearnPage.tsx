import {useEffect, useMemo, useRef, useState, type ReactNode} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Link, useParams} from "react-router-dom";
import {queries, trackStudyEvent} from "../api";
import {ErrorNotice, Loading, Metric, Panel} from "../components";
import {DomainBrowserCard} from "../DomainBrowser";
import {statusLabels} from "../mastery";
import type {
  CoachResponse,
  LearningEventType,
  ObjectiveDetail,
  StudyAnnotation,
} from "../types";

function objectivePath(objectiveId: number) {
  return `/learn/${objectiveId}`;
}

export function LearnPage() {
  const [exam, setExam] = useState("220-1201");
  const packQuery = useQuery({
    queryKey: ["certification-pack", "aplus"],
    queryFn: queries.certificationPack,
  });
  const mapQuery = useQuery({
    queryKey: ["mastery-map", exam],
    queryFn: () => queries.masteryMap(exam),
  });

  if (packQuery.isLoading || mapQuery.isLoading) {
    return <Loading label="Building your certification workspace" />;
  }
  const error = packQuery.error || mapQuery.error;
  if (error) return <ErrorNotice error={error} />;

  const pack = packQuery.data!;
  const map = mapQuery.data!;
  const examData = map.exams[0];
  const nextObjective = examData?.domains
    .flatMap((domain) => domain.objectives)
    .find((objective) => objective.evidence.lessons_completed === 0);

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Certification learning workspace</span>
        <h1>{pack.certification_name}</h1>
        <p>
          Follow the complete official exam roadmap, open any lesson directly,
          test out of familiar domains, and focus practice where the evidence says it matters.
        </p>
      </div>

      <Panel
        eyebrow={`${pack.exam_version} · ${pack.objective_count} official objectives`}
        title={nextObjective ? `Continue with ${nextObjective.code}` : "All lessons completed"}
        action={nextObjective ? (
          <Link className="button primary" to={objectivePath(nextObjective.id)}>
            {map.totals.objectives_started ? "Continue learning" : "Start learning"}
          </Link>
        ) : null}
      >
        <p className="large-copy">
          Official CompTIA objectives define what you learn. Approved books supply
          the lesson, and practice evidence remains separate from reading progress.
        </p>
      </Panel>

      <div className="metric-grid compact">
        <Metric value={map.totals.objectives} label="Objectives" />
        <Metric value={map.totals.objectives_started} label="Started" />
        <Metric value={map.totals.lessons_completed} label="Lessons completed" accent />
        <Metric value={map.totals.strong_signal} label="Strong signals" />
        <Metric value={map.totals.needs_work} label="Needs work" />
      </div>

      <div className="exam-switch" role="group" aria-label="A+ exam">
        <button
          className={exam === "220-1201" ? "selected" : ""}
          onClick={() => setExam("220-1201")}
        >
          Core 1 <span>220-1201</span>
        </button>
        <button
          className={exam === "220-1202" ? "selected" : ""}
          onClick={() => setExam("220-1202")}
        >
          Core 2 <span>220-1202</span>
        </button>
      </div>

      <div className="learning-legend">
        <strong>Choose your path:</strong>
        <span>Learn any objective</span>
        <span>Take a domain knowledge check</span>
        <span>Review only open gaps</span>
      </div>

      <div className="learning-domains">
        {examData?.domains.map((domain, index) => (
          <DomainBrowserCard key={domain.id} domain={domain} mode="learn" initiallyOpen={index === 0} />
        ))}
      </div>

      <p className="fine-print">
        “Lesson completed” records learning activity only. Mastery still requires direct assessment evidence.
      </p>
    </>
  );
}

function CoachLessonAnswer({response}: {response: CoachResponse}) {
  return (
    <div className="coach-answer">
      <span className="eyebrow">{response.provider_label}</span>
      <h3>{response.answer.title}</h3>
      <p>{response.answer.summary}</p>
      {response.answer.steps.length ? (
        <ol>{response.answer.steps.map((step) => <li key={step}>{step}</li>)}</ol>
      ) : null}
      {response.answer.check_yourself.length ? (
        <>
          <h4>Check yourself</h4>
          <ul>{response.answer.check_yourself.map((item) => <li key={item}>{item}</li>)}</ul>
        </>
      ) : null}
      <p className="fine-print">{response.answer.caveat}</p>
    </div>
  );
}

function lessonPrompt(objective: ObjectiveDetail) {
  return `Create an active-recall practice session specifically for ${objective.exam_code} objective ${objective.code}: ${objective.description}`;
}

function highlightText(
  text: string,
  highlights: StudyAnnotation[],
  keyPrefix: string,
  usedHighlightIds: Set<number>,
): ReactNode[] {
  const candidates = highlights
    .filter((annotation) =>
      !usedHighlightIds.has(annotation.id)
      && Boolean(annotation.quote_text && text.includes(annotation.quote_text)),
    )
    .map((annotation) => {
      const quote = annotation.quote_text!;
      const occurrences: number[] = [];
      let cursor = 0;
      while (cursor < text.length) {
        const index = text.indexOf(quote, cursor);
        if (index < 0) break;
        occurrences.push(index);
        cursor = index + quote.length;
      }
      const prefix = annotation.prefix_text?.slice(-80) ?? "";
      const suffix = annotation.suffix_text?.slice(0, 80) ?? "";
      const contextual = occurrences.find((index) => {
        const before = text.slice(Math.max(0, index - prefix.length), index);
        const after = text.slice(index + quote.length, index + quote.length + suffix.length);
        return (!prefix || before === prefix) && (!suffix || after === suffix);
      });
      return {
        annotation,
        index: contextual ?? occurrences[0],
        quote,
      };
    })
    .filter((candidate) => candidate.index >= 0)
    .sort((a, b) => a.index - b.index || b.quote.length - a.quote.length);
  if (!candidates.length) return [<span key={`${keyPrefix}-plain`}>{text}</span>];
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let part = 0;
  for (const candidate of candidates) {
    if (usedHighlightIds.has(candidate.annotation.id) || candidate.index < cursor) {
      continue;
    }
    if (candidate.index > cursor) {
      nodes.push(<span key={`${keyPrefix}-text-${part}`}>{text.slice(cursor, candidate.index)}</span>);
    }
    nodes.push(<mark key={`${keyPrefix}-mark-${part}`}>{candidate.quote}</mark>);
    usedHighlightIds.add(candidate.annotation.id);
    cursor = candidate.index + candidate.quote.length;
    part += 1;
  }
  if (cursor < text.length) {
    nodes.push(<span key={`${keyPrefix}-tail-${part}`}>{text.slice(cursor)}</span>);
  }
  return nodes;
}

function inlineMarkdown(
  text: string,
  highlights: StudyAnnotation[] = [],
  usedHighlightIds = new Set<number>(),
): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) => {
    const bold = part.startsWith("**") && part.endsWith("**");
    const content = bold ? part.slice(2, -2) : part;
    const rendered = highlightText(
      content,
      highlights,
      `${index}-${content.slice(0, 8)}`,
      usedHighlightIds,
    );
    return bold
      ? <strong key={`${part}-${index}`}>{rendered}</strong>
      : <span key={`${part}-${index}`}>{rendered}</span>;
  });
}

function isBlockStart(line: string) {
  return /^(#{1,6}\s+|[-*]\s+|\d+\.\s+|\[Image:)/.test(line);
}

function MarkdownReading({
  content,
  highlights = [],
  onHighlightParagraph,
}: {
  content: string;
  highlights?: StudyAnnotation[];
  onHighlightParagraph?: (text: string) => void;
}) {
  const lines = content.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  const usedHighlightIds = new Set<number>();
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const level = Math.min(heading[1].length + 1, 6);
      const Tag = `h${level}` as "h2" | "h3" | "h4" | "h5" | "h6";
      blocks.push(<Tag key={`heading-${index}`}>{inlineMarkdown(heading[2], highlights, usedHighlightIds)}</Tag>);
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
          {items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{inlineMarkdown(item, highlights, usedHighlightIds)}</li>)}
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
          {items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{inlineMarkdown(item, highlights, usedHighlightIds)}</li>)}
        </ol>,
      );
      continue;
    }
    if (/^\[Image:/.test(line)) {
      blocks.push(
        <aside className="reading-figure-note" key={`image-${index}`}>
          {line.slice(1, -1)}
        </aside>,
      );
      index += 1;
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !isBlockStart(lines[index].trim())
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    const paragraphText = paragraph.join(" ");
    blocks.push(
      <div className="annotatable-paragraph" key={`paragraph-${index}`}>
        <p>{inlineMarkdown(paragraphText, highlights, usedHighlightIds)}</p>
        {onHighlightParagraph ? (
          <button
            className="paragraph-highlight-button"
            type="button"
            onClick={() => onHighlightParagraph(paragraphText)}
          >
            Highlight paragraph
          </button>
        ) : null}
      </div>,
    );
  }
  return <div className="markdown-reading">{blocks}</div>;
}

interface HighlightDraft {
  source: ObjectiveDetail["evidence"][number];
  quote: string;
  prefix: string;
  suffix: string;
  start: number;
  end: number;
}

export function LessonPage() {
  const {objectiveId} = useParams();
  const id = Number(objectiveId);
  const queryClient = useQueryClient();
  const [openSections, setOpenSections] = useState<string[]>([]);
  const [highlightDraft, setHighlightDraft] = useState<HighlightDraft | null>(null);
  const [highlightNote, setHighlightNote] = useState("");
  const [objectiveNote, setObjectiveNote] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const readerRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const objectiveQuery = useQuery({
    queryKey: ["objective", id],
    queryFn: () => queries.objective(id),
    enabled: Number.isInteger(id) && id > 0,
  });
  const annotationQuery = useQuery({
    queryKey: ["annotations", id],
    queryFn: () => queries.annotations(id),
    enabled: Number.isInteger(id) && id > 0,
  });

  const record = useMutation({
    mutationFn: ({eventType, eventKey, metadata}: {
      eventType: LearningEventType;
      eventKey: string;
      metadata?: Record<string, unknown>;
    }) => queries.logLearningEvent(id, eventType, eventKey, metadata),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: ["objective", id]});
      void queryClient.invalidateQueries({queryKey: ["mastery-map"]});
      void queryClient.invalidateQueries({queryKey: ["study-next"]});
      void queryClient.invalidateQueries({queryKey: ["adaptive-plan"]});
      void queryClient.invalidateQueries({queryKey: ["retention"]});
    },
  });

  const coach = useMutation({
    mutationFn: (objective: ObjectiveDetail) =>
      queries.coach("practice", lessonPrompt(objective)),
    onSuccess: (_response, objective) => {
      record.mutate({
        eventType: "coach_used",
        eventKey: `objective:${objective.id}:coach:${Date.now()}`,
        metadata: {objective_code: objective.code},
      });
      trackStudyEvent(
        "coach_used",
        `${objective.exam_code} ${objective.code} practice`,
        `objective:${objective.id}:coach:${Date.now()}`,
      );
    },
  });
  const saveAnnotation = useMutation({
    mutationFn: queries.createAnnotation,
    onSuccess: () => {
      setHighlightDraft(null);
      setHighlightNote("");
      setObjectiveNote("");
      setSelectionError("");
      window.getSelection()?.removeAllRanges();
      void queryClient.invalidateQueries({queryKey: ["annotations", id]});
    },
  });
  const archiveAnnotation = useMutation({
    mutationFn: (annotationId: number) =>
      queries.updateAnnotation(annotationId, {archived: true}),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: ["annotations", id]});
    },
  });

  useEffect(() => {
    if (!Number.isInteger(id) || id <= 0) return;
    void queries.logLearningEvent(
      id,
      "objective_opened",
      `objective:${id}:opened`,
    ).catch(() => undefined);
  }, [id]);

  const objective = objectiveQuery.data;
  const primarySources = useMemo(
    () => objective?.evidence.filter((source) => source.source_role !== "supplemental_instruction") ?? [],
    [objective],
  );
  const supplementalSources = useMemo(
    () => objective?.evidence.filter((source) => source.source_role === "supplemental_instruction") ?? [],
    [objective],
  );

  if (objectiveQuery.isLoading || annotationQuery.isLoading) return <Loading label="Opening your lesson" />;
  if (objectiveQuery.error) return <ErrorNotice error={objectiveQuery.error} />;
  if (annotationQuery.error) return <ErrorNotice error={annotationQuery.error} />;
  if (!objective) return <ErrorNotice error={new Error("Objective not found")} />;

  const mastery = objective.mastery;
  const learning = objective.learning;
  const retention = objective.retention;
  const annotations = annotationQuery.data?.annotations ?? [];
  const highlights = annotations.filter((annotation) => annotation.kind === "highlight");
  const captureHighlight = (
    source: ObjectiveDetail["evidence"][number],
    quiet = false,
  ) => {
    const root = readerRefs.current[source.stable_id];
    const selection = window.getSelection();
    if (
      !root
      || !selection
      || selection.rangeCount !== 1
      || selection.isCollapsed
    ) {
      if (!quiet) {
        setSelectionError("Select a sentence or phrase in this open reading first.");
      }
      return;
    }
    const range = selection.getRangeAt(0);
    if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) {
      setSelectionError("The selected text must be inside this reading.");
      return;
    }
    const rawQuote = selection.toString();
    const quote = rawQuote.trim();
    if (!quote || quote.length > 2000) {
      setSelectionError("Select between 1 and 2,000 characters.");
      return;
    }
    const before = document.createRange();
    before.selectNodeContents(root);
    before.setEnd(range.startContainer, range.startOffset);
    const leading = rawQuote.length - rawQuote.trimStart().length;
    const start = before.toString().length + leading;
    const end = start + quote.length;
    const fullText = root.textContent ?? "";
    setHighlightDraft({
      source,
      quote,
      prefix: fullText.slice(Math.max(0, start - 120), start),
      suffix: fullText.slice(end, end + 120),
      start,
      end,
    });
    setSelectionError("");
  };
  const captureParagraph = (
    source: ObjectiveDetail["evidence"][number],
    quote: string,
  ) => {
    const sourceText = source.focused_excerpt;
    const start = Math.max(0, sourceText.indexOf(quote));
    const end = start + quote.length;
    setHighlightDraft({
      source,
      quote,
      prefix: sourceText.slice(Math.max(0, start - 120), start),
      suffix: sourceText.slice(end, end + 120),
      start,
      end,
    });
    setSelectionError("");
  };
  const toggleReading = (source: ObjectiveDetail["evidence"][number]) => {
    const opening = !openSections.includes(source.stable_id);
    setOpenSections((current) => (
      opening
        ? [...current, source.stable_id]
        : current.filter((stableId) => stableId !== source.stable_id)
    ));
    if (!opening) return;
    record.mutate({
      eventType: "reading_opened",
      eventKey: `objective:${objective.id}:section:${source.stable_id}`,
      metadata: {
        objective_id: objective.id,
        section_stable_id: source.stable_id,
        objective_code: objective.code,
        source_role: source.source_role ?? "primary_instruction",
      },
    });
    trackStudyEvent(
      "reading_opened",
      `${objective.exam_code} ${objective.code}: ${source.title}`,
      `section:${source.stable_id}`,
      {
        section_stable_id: source.stable_id,
        objective_id: objective.id,
        objective_code: objective.code,
      },
    );
  };

  return (
    <>
      <div className="page-title lesson-title">
        <span className="eyebrow">{objective.exam_code} · Domain {objective.domain_code} · Objective {objective.code}</span>
        <h1>{objective.description}</h1>
        <p>
          Learn from the approved source set, check your recall, then use assessment
          evidence to decide whether this objective is actually strong.
        </p>
      </div>

      <div className="lesson-status-strip">
        <div><span>Learning</span><strong>{learning.lesson_completed ? "Lesson complete" : learning.started ? "In progress" : "Not started"}</strong></div>
        <div><span>Recall</span><strong>{learning.recall_completed ? "Completed" : "Not completed"}</strong></div>
        <div><span>Memory review</span><strong>{retention ? (retention.due ? "Due now" : `In ${retention.interval_days} day${retention.interval_days === 1 ? "" : "s"}`) : "After completion"}</strong></div>
        <div><span>Evidence</span><strong>{statusLabels[mastery.status]}</strong></div>
      </div>

      {mastery.domain_signal.open_gap_count > 0 && mastery.domain_signal.scope_id ? (
        <Panel
          eyebrow="Your evidence"
          title={`${mastery.domain_signal.open_gap_count} open ${objective.domain_name} gaps`}
          action={<Link className="button primary" to={`/study/remediate/${mastery.domain_signal.scope_id}`}>Review gaps</Link>}
        >
          <p>These are domain-level gaps from your knowledge check. You can still study this lesson directly.</p>
        </Panel>
      ) : null}

      <Panel eyebrow="Step 1 · Understand" title="Read the focused lesson">
        <p>
          Start with the focused review source. Open the deeper textbook source only
          when you need more context or examples.
        </p>
        <div className="lesson-sources">
          {[...primarySources, ...supplementalSources].map((source) => (
            <article key={`${source.book_slug}:${source.stable_id}`} className="lesson-source">
              <div>
                <span className="eyebrow">
                  {source.source_role === "supplemental_instruction" ? "Deeper reading" : "Primary lesson"}
                </span>
                <h3>{source.title}</h3>
                <p>{source.book_title}</p>
              </div>
              <div className="source-actions">
                <button className="button secondary" onClick={() => toggleReading(source)}>
                  {openSections.includes(source.stable_id) ? "Close reading" : "Open reading"}
                </button>
                <button
                  className="text-button"
                  disabled={saveAnnotation.isPending || annotations.some(
                    (annotation) =>
                      annotation.kind === "bookmark"
                      && annotation.section_stable_id === source.stable_id,
                  )}
                  onClick={() => saveAnnotation.mutate({
                    objective_id: objective.id,
                    kind: "bookmark",
                    section_stable_id: source.stable_id,
                    content_sha256: source.content_sha256,
                    client_key: `bookmark:${objective.id}:${source.stable_id}`,
                  })}
                >
                  {annotations.some(
                    (annotation) =>
                      annotation.kind === "bookmark"
                      && annotation.section_stable_id === source.stable_id,
                  ) ? "Bookmarked" : "Bookmark"}
                </button>
              </div>
              {openSections.includes(source.stable_id) ? (
                <div className="full-source lesson-reader">
                  <div
                    className="reading-selection-area"
                    ref={(node) => {
                      readerRefs.current[source.stable_id] = node;
                    }}
                    onMouseUp={() => captureHighlight(source, true)}
                    onTouchEnd={() => {
                      window.setTimeout(() => captureHighlight(source, true), 150);
                    }}
                  >
                    <MarkdownReading
                      content={source.focused_excerpt}
                      highlights={highlights.filter(
                        (annotation) =>
                          annotation.section_stable_id === source.stable_id
                          && annotation.anchor_status !== "unresolved",
                      )}
                      onHighlightParagraph={(quote) => captureParagraph(source, quote)}
                    />
                  </div>
                  <div className="reader-tools">
                    <span>
                      Select text above, or use Highlight paragraph when mobile selection is awkward.
                    </span>
                    <button
                      className="button secondary"
                      onClick={() => captureHighlight(source)}
                    >
                      Use current selection
                    </button>
                  </div>
                </div>
              ) : null}
            </article>
          ))}
        </div>
        {selectionError ? <p className="notice error">{selectionError}</p> : null}
        {highlightDraft ? (
          <div className="highlight-composer">
            <span className="eyebrow">New highlight</span>
            <blockquote>{highlightDraft.quote}</blockquote>
            <label>
              Optional note
              <textarea
                value={highlightNote}
                maxLength={5000}
                onChange={(event) => setHighlightNote(event.target.value)}
                placeholder="Why is this important or how would you explain it?"
              />
            </label>
            <div className="action-row">
              <button
                className="button primary"
                disabled={saveAnnotation.isPending}
                onClick={() => saveAnnotation.mutate({
                  objective_id: objective.id,
                  kind: "highlight",
                  section_stable_id: highlightDraft.source.stable_id,
                  quote_text: highlightDraft.quote,
                  prefix_text: highlightDraft.prefix,
                  suffix_text: highlightDraft.suffix,
                  note_text: highlightNote.trim() || undefined,
                  content_sha256: highlightDraft.source.content_sha256,
                  anchor_start: highlightDraft.start,
                  anchor_end: highlightDraft.end,
                  client_key: `highlight:${objective.id}:${highlightDraft.source.stable_id}:${Date.now()}`,
                })}
              >
                Save highlight
              </button>
              <button className="button secondary" onClick={() => setHighlightDraft(null)}>
                Cancel
              </button>
            </div>
          </div>
        ) : null}
        {saveAnnotation.error ? <ErrorNotice error={saveAnnotation.error} /> : null}
      </Panel>

      <Panel eyebrow="Your notebook" title="Notes, highlights, and bookmarks">
        <div className="objective-note-composer">
          <label htmlFor="objective-note">Add a note to objective {objective.code}</label>
          <textarea
            id="objective-note"
            value={objectiveNote}
            maxLength={5000}
            onChange={(event) => setObjectiveNote(event.target.value)}
            placeholder="Write the concept in your own words, record a question, or save something to revisit."
          />
          <button
            className="button primary"
            disabled={!objectiveNote.trim() || saveAnnotation.isPending}
            onClick={() => saveAnnotation.mutate({
              objective_id: objective.id,
              kind: "note",
              note_text: objectiveNote.trim(),
              client_key: `note:${objective.id}:${Date.now()}`,
            })}
          >
            Save note
          </button>
        </div>
        {annotations.length ? (
          <ol className="annotation-list">
            {annotations.map((annotation) => (
              <li key={annotation.id}>
                <div className="annotation-meta">
                  <span>{annotation.kind}</span>
                  {annotation.book_title ? <small>{annotation.book_title}</small> : null}
                  {annotation.anchor_status === "unresolved" ? <small>Source changed · review needed</small> : null}
                </div>
                {annotation.quote_text ? <blockquote>{annotation.quote_text}</blockquote> : null}
                {annotation.note_text ? <p>{annotation.note_text}</p> : null}
                {annotation.kind === "bookmark" ? <strong>{annotation.section_title ?? "Objective bookmark"}</strong> : null}
                <button
                  className="text-button"
                  disabled={archiveAnnotation.isPending}
                  onClick={() => archiveAnnotation.mutate(annotation.id)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="notice">Nothing saved yet. Open a reading to highlight text, bookmark a source, or add your own note.</p>
        )}
        {archiveAnnotation.error ? <ErrorNotice error={archiveAnnotation.error} /> : null}
        <p className="fine-print">
          Highlights retain the source hash and surrounding quotation context so future book updates can be reviewed safely.
        </p>
      </Panel>

      <Panel eyebrow="Step 2 · Recall" title="Explain it without looking">
        <div className="recall-card">
          <p className="large-copy">Without your notes, explain:</p>
          <ol>
            <li>What this objective expects you to recognize or do.</li>
            <li>The important components, steps, or distinctions from the lesson.</li>
            <li>One realistic scenario where you would apply the material.</li>
          </ol>
        </div>
        <button
          className={learning.recall_completed ? "button secondary" : "button primary"}
          disabled={record.isPending}
          onClick={() => record.mutate({
            eventType: "recall_completed",
            eventKey: `objective:${objective.id}:recall-completed`,
          })}
        >
          {learning.recall_completed ? "Recall recorded" : "I completed the recall"}
        </button>
      </Panel>

      <Panel eyebrow="Step 3 · Practice" title="Practice this objective with Study Coach">
        <p>
          Claude uses only the approved cited corpus to create active-recall prompts.
          This does not expose or reproduce the private practice bank.
        </p>
        <button
          className="button secondary"
          disabled={coach.isPending}
          onClick={() => coach.mutate(objective)}
        >
          {coach.isPending ? "Building practice..." : "Create objective practice"}
        </button>
        {coach.error ? <ErrorNotice error={coach.error} /> : null}
        {coach.data ? <CoachLessonAnswer response={coach.data} /> : null}
      </Panel>

      <Panel
        eyebrow="Step 4 · Apply"
        title="Practice it hands-on"
        action={<Link className="button secondary" to={`/labs?objective_id=${objective.id}`}>Open lab workspace</Link>}
      >
        <p>
          Create a lab for this objective, capture the environment and results,
          then record whether you completed it with guidance, references, or unaided.
        </p>
      </Panel>

      <Panel
        eyebrow="Step 5 · Finish"
        title={learning.lesson_completed ? "Lesson completed" : "Record this lesson"}
        action={
          <button
            className={learning.lesson_completed ? "button secondary" : "button primary"}
            disabled={record.isPending}
            onClick={() => record.mutate({
              eventType: "lesson_completed",
              eventKey: `objective:${objective.id}:lesson-completed`,
            })}
          >
            {learning.lesson_completed ? "Completed" : "Mark lesson complete"}
          </button>
        }
      >
        <p>{learning.evidence_note}</p>
        {retention ? (
          <p>
            Next memory review: {new Date(retention.due_at).toLocaleDateString("en-US", {
              weekday: "long",
              month: "short",
              day: "numeric",
            })}.{" "}
            {retention.due ? <Link className="text-link" to={`/study/review/${objective.id}`}>Review now</Link> : null}
          </p>
        ) : null}
        {mastery.domain_signal.scope_id ? (
          <Link className="text-link" to={`/study/check/${mastery.domain_signal.scope_id}?mode=diagnostic`}>
            Take the {objective.domain_name} knowledge check
          </Link>
        ) : null}
      </Panel>

      <nav className="lesson-navigation" aria-label="Lesson navigation">
        {objective.navigation.previous ? (
          <Link to={objectivePath(objective.navigation.previous.id)}>
            <span>Previous</span>
            <strong>{objective.navigation.previous.code}</strong>
          </Link>
        ) : <span />}
        <Link className="text-link" to="/learn">All objectives</Link>
        {objective.navigation.next ? (
          <Link to={objectivePath(objective.navigation.next.id)}>
            <span>Next</span>
            <strong>{objective.navigation.next.code}</strong>
          </Link>
        ) : <span />}
      </nav>
    </>
  );
}
