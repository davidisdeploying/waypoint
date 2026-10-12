import {useEffect, useMemo, useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Link, Navigate, useParams} from "react-router-dom";
import {queries, trackStudyEvent} from "../api";
import {ErrorNotice, Loading, Panel, ProgressBar, QuestionFigure} from "../components";
import {SectionReader} from "../SectionReader";
import type {DiagnosticScope, RemediationGap} from "../types";

export function RemediationScopePage() {
  const {scopeId: rawScopeId} = useParams();
  const scopeId = Number(rawScopeId);
  const scopeQuery = useQuery({
    queryKey: ["diagnostic-scope", scopeId],
    queryFn: () => queries.diagnosticScope(scopeId),
    enabled: Number.isInteger(scopeId) && scopeId > 0,
  });
  if (scopeQuery.isLoading) return <Loading label="Finding your latest result" />;
  if (scopeQuery.error) return <ErrorNotice error={scopeQuery.error} />;
  const latest = scopeQuery.data!.recent_attempts.find((attempt) =>
    attempt.state === "submitted" && attempt.bucket_result === "needs_remediation");
  if (!latest) return <Navigate to="/study" replace />;
  return <Navigate to={`/study/results/${latest.id}`} replace />;
}

function SourceReading({gap}: {gap: RemediationGap}) {
  const [stableId, setStableId] = useState<string | null>(gap.readings[0]?.section_stable_id ?? null);
  const [showFull, setShowFull] = useState(false);
  useEffect(() => {
    const firstReading = gap.readings[0];
    setStableId(firstReading?.section_stable_id ?? null);
    setShowFull(false);
    if (firstReading) {
      trackStudyEvent(
        "reading_opened",
        firstReading.section_title,
        `section:${firstReading.section_stable_id}`,
        {book_title: firstReading.book_title},
      );
    }
  }, [gap.remediation_id, gap.readings]);
  const section = useQuery({
    queryKey: ["reader-section", stableId],
    queryFn: () => queries.readerSection(stableId!),
    enabled: Boolean(stableId) && showFull,
  });
  const selectedReading = gap.readings.find((reading) => reading.section_stable_id === stableId);

  return (
    <div className="gap-readings">
      <h3>Learn this from your books</h3>
      {gap.readings.length > 1 ? gap.readings.map((reading) => (
        <button
          type="button"
          key={reading.section_stable_id}
          className={stableId === reading.section_stable_id ? "reading-choice selected" : "reading-choice"}
          onClick={() => {
            setStableId(reading.section_stable_id);
            setShowFull(false);
          }}
        >
          <strong>{reading.section_title}</strong>
          <span>{reading.book_title}</span>
        </button>
      )) : null}

      {selectedReading ? (
        <article className="source-reader">
          <span className="eyebrow">From {selectedReading.book_title}</span>
          <h3>{selectedReading.section_title}</h3>
          <p className="source-snippet">{selectedReading.snippet}</p>
          <button className="text-button" type="button" onClick={() => {
            setShowFull(true);
            trackStudyEvent(
              "reading_opened",
              selectedReading.section_title,
              `section:${selectedReading.section_stable_id}`,
              {book_title: selectedReading.book_title},
            );
          }}>
            Read full section
          </button>
          {showFull ? (
            <SectionReader
              sectionId={selectedReading.section_stable_id}
              title={selectedReading.section_title}
              bookTitle={selectedReading.book_title}
              content={section.data?.content ?? undefined}
              html={section.data?.html ?? undefined}
              loading={section.isLoading}
              error={section.error}
              onClose={() => setShowFull(false)}
            />
          ) : null}
        </article>
      ) : <p className="notice">Your books do not contain a close enough passage for this item. Use the explanation above; Waypoint will not show an unrelated citation.</p>}
    </div>
  );
}

function UnfinishedAttempt({scope, onDiscarded}: {
  scope: DiagnosticScope;
  onDiscarded: () => void;
}) {
  const unfinished = scope.recent_attempts.find((attempt) => attempt.state === "in_progress");
  const discard = useMutation({
    mutationFn: () => queries.abandonDiagnostic(unfinished!.id),
    onSuccess: onDiscarded,
  });
  if (!unfinished) return null;
  return (
    <div className="notice unfinished-check">
      <strong>An unfinished {unfinished.mode} check is still open.</strong>
      <p>Resume it, or discard it before starting your focused retest.</p>
      <div className="action-row">
        <Link className="button secondary" to={`/study/check/${scope.id}?mode=${unfinished.mode}`}>Resume</Link>
        <button className="button secondary" disabled={discard.isPending} onClick={() => discard.mutate()}>
          {discard.isPending ? "Discarding..." : "Discard unfinished check"}
        </button>
      </div>
      {discard.error ? <ErrorNotice error={discard.error} /> : null}
    </div>
  );
}

export function RemediationPage() {
  const {attemptId: rawAttemptId} = useParams();
  const attemptId = Number(rawAttemptId);
  const queryClient = useQueryClient();
  const [gapIndex, setGapIndex] = useState(0);
  const results = useQuery({
    queryKey: ["diagnostic-results", attemptId],
    queryFn: () => queries.diagnosticResults(attemptId),
    enabled: Number.isInteger(attemptId) && attemptId > 0,
  });
  const scopeId = results.data?.scope_id;
  const scope = useQuery({
    queryKey: ["diagnostic-scope", scopeId],
    queryFn: () => queries.diagnosticScope(scopeId!),
    enabled: Boolean(scopeId),
  });
  const review = useMutation({
    mutationFn: (itemId: number) => queries.markRemediationReviewed(itemId),
    onSuccess: async () => {
      await Promise.all([results.refetch(), scope.refetch()]);
      void queryClient.invalidateQueries({queryKey: ["study-next"]});
      void queryClient.invalidateQueries({queryKey: ["study-progress"]});
      void queryClient.invalidateQueries({queryKey: ["adaptive-plan"]});
    },
  });

  const gaps = results.data?.gaps ?? [];
  const openCount = gaps.filter((gap) => gap.status === "open").length;
  const activeGap = gaps[gapIndex];
  const unfinished = scope.data?.recent_attempts.some((attempt) => attempt.state === "in_progress");

  useEffect(() => {
    if (gapIndex >= gaps.length && gaps.length) setGapIndex(gaps.length - 1);
  }, [gapIndex, gaps.length]);

  const reviewedCount = useMemo(
    () => gaps.filter((gap) => gap.status === "reviewed").length,
    [gaps],
  );

  if (results.isLoading || (scopeId && scope.isLoading)) return <Loading label="Building focused remediation" />;
  if (results.error) return <ErrorNotice error={results.error} />;
  if (scope.error) return <ErrorNotice error={scope.error} />;
  const attempt = results.data!;

  if (attempt.passed) {
    return (
      <>
        <div className="page-title">
          <span className="eyebrow">Knowledge check complete</span>
          <h1>Section passed</h1>
          <p>Your broad review is exempted. A retention check will bring this material back later.</p>
        </div>
        <Panel eyebrow="Result" title={`${attempt.raw_score_pct}% raw score`}>
          <p>Confidence-adjusted score: {attempt.effective_score_pct}%.</p>
          <p className="fine-print">This is provisional multiple-choice mastery, not hands-on or PBQ proof.</p>
          <Link className="button primary" to="/study">Continue to Study</Link>
        </Panel>
      </>
    );
  }

  return (
    <div className={activeGap ? "remediation-page remediation-page-with-question-nav" : "remediation-page"}>
      <div className="page-title remediation-title">
        <span className="eyebrow">Guided review</span>
        <h1>{openCount ? `Learn the ${openCount} questions you missed` : "Ready to retest"}</h1>
        <p>For each missed question, compare the answer, read the short lesson, explain it in your own words, then continue.</p>
      </div>

      <ol className="review-steps" aria-label="How guided review works">
        <li><strong>Compare</strong><span>See why your answer missed.</span></li>
        <li><strong>Learn</strong><span>Read the matching book excerpt.</span></li>
        <li><strong>Recall</strong><span>Explain it without looking.</span></li>
        <li><strong>Continue</strong><span>Mark it understood and move on.</span></li>
      </ol>

      <div className="result-strip">
        <div><strong>{attempt.raw_score_pct}%</strong><span>Knowledge check</span></div>
        <div><strong>{gaps.length}</strong><span>Questions to learn</span></div>
        <div><strong>{reviewedCount} / {gaps.length}</strong><span>Finished</span></div>
      </div>
      <ProgressBar value={gaps.length ? (reviewedCount / gaps.length) * 100 : 100} />

      {scope.data ? (
        <UnfinishedAttempt scope={scope.data} onDiscarded={() => void scope.refetch()} />
      ) : null}

      {activeGap ? (
        <section className="panel gap-focus">
          <header className="gap-header">
            <div>
              <span className="eyebrow">Missed question {gapIndex + 1} of {gaps.length}</span>
              <h2>{activeGap.gap_reason === "incorrect" ? "Compare your answer" : "Strengthen a low-confidence answer"}</h2>
            </div>
            <div className="gap-header-actions">
              <span className={activeGap.status === "reviewed" ? "mastery mastered_after_remediation" : "mastery needs_remediation"}>
                {activeGap.status === "reviewed" ? "understood" : "to review"}
              </span>
              <div className="gap-pager">
                <button
                  className="button secondary"
                  disabled={gapIndex === 0}
                  onClick={() => setGapIndex(gapIndex - 1)}
                >
                  Prev
                </button>
                <button
                  className="button secondary"
                  disabled={gapIndex >= gaps.length - 1}
                  onClick={() => setGapIndex(gapIndex + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          </header>
          <p className="gap-question">{activeGap.prompt_snapshot}</p>
          <QuestionFigure figure={activeGap.figure} />
          <div className="answer-comparison">
            <div><span>Your answer</span><strong>{activeGap.submitted_answer_text.join("; ") || "None"}</strong></div>
            <div><span>Correct answer</span><strong>{activeGap.correct_answer_text.join("; ")}</strong></div>
          </div>
          {activeGap.explanation ? (
            <div className="concept-explanation">
              <span className="eyebrow">Why</span>
              <p>{activeGap.explanation}</p>
            </div>
          ) : null}

          <SourceReading gap={activeGap} />

          <div className="recall-box">
            <span className="eyebrow">Say it in your own words</span>
            <p>{activeGap.recall_prompt}</p>
          </div>

          {review.error ? <ErrorNotice error={review.error} /> : null}
          <nav className="gap-navigation remediation-question-nav" aria-label="Review question navigation">
            <button
              className="button secondary"
              disabled={gapIndex === 0}
              onClick={() => setGapIndex(gapIndex - 1)}
            >
              Previous question
            </button>
            {activeGap.status === "open" ? (
              <button
                className="button primary"
                disabled={review.isPending}
                onClick={() => review.mutate(activeGap.remediation_id, {
                  onSuccess: () => {
                    trackStudyEvent(
                      "gap_reviewed",
                      activeGap.prompt_snapshot,
                      `gap:${activeGap.remediation_id}`,
                    );
                    if (gapIndex < gaps.length - 1) setGapIndex(gapIndex + 1);
                  },
                })}
              >
                {review.isPending ? "Saving..." : "I understand — next"}
              </button>
            ) : (
              <button
                className="button primary"
                disabled={gapIndex >= gaps.length - 1}
                onClick={() => setGapIndex(gapIndex + 1)}
              >
                Next question
              </button>
            )}
          </nav>
        </section>
      ) : null}

      {!openCount && scope.data ? (
        <Panel eyebrow="Next step" title="Take a fresh focused retest">
          <p>The remediation gate is complete. The retest uses a fresh sample and records mastery separately.</p>
          <Link
            className={unfinished ? "button primary disabled-link" : "button primary"}
            aria-disabled={unfinished}
            onClick={(event) => {
              if (unfinished) event.preventDefault();
            }}
            to={`/study/check/${scope.data.id}?mode=retest`}
          >
            Start focused retest
          </Link>
        </Panel>
      ) : null}
    </div>
  );
}
