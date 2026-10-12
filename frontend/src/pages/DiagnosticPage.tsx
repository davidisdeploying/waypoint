import {useEffect, useMemo, useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Link, useNavigate, useParams, useSearchParams} from "react-router-dom";
import {ApiError, queries, trackStudyEvent} from "../api";
import {ErrorNotice, Loading, ProgressBar, QuestionFigure} from "../components";
import {
  clearDraft,
  expectedSelections,
  readDraft,
  serializeDiagnostic,
  writeDraft,
  type DraftAnswer,
} from "../diagnostics";
import type {DiagnosticAttempt, DiagnosticMode} from "../types";

async function loadOrStart(scopeId: number, mode: DiagnosticMode) {
  const scope = await queries.diagnosticScope(scopeId);
  const existing = scope.recent_attempts.find((attempt) => attempt.state === "in_progress");
  if (existing) return queries.diagnosticAttempt(existing.id);
  return queries.startDiagnostic(scopeId, mode);
}

export function DiagnosticPage() {
  const {scopeId: rawScopeId} = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const scopeId = Number(rawScopeId);
  const requestedMode = searchParams.get("mode");
  const mode: DiagnosticMode = requestedMode === "retest" || requestedMode === "retention"
    ? requestedMode
    : "diagnostic";
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<number, DraftAnswer>>({});

  const attemptQuery = useQuery({
    queryKey: ["diagnostic-attempt", scopeId, mode],
    queryFn: () => loadOrStart(scopeId, mode),
    enabled: Number.isInteger(scopeId) && scopeId > 0,
    retry: false,
  });
  const attempt = attemptQuery.data;

  useEffect(() => {
    if (attempt) setAnswers(readDraft(attempt.id));
  }, [attempt?.id]);

  const submit = useMutation({
    mutationFn: ({active, payload}: {
      active: DiagnosticAttempt;
      payload: ReturnType<typeof serializeDiagnostic>;
    }) => queries.submitDiagnostic(active.id, payload),
    onSuccess: (result) => {
      clearDraft(result.id);
      trackStudyEvent(
        "knowledge_check_completed",
        `${result.mode} knowledge check`,
        `diagnostic:${result.id}`,
        {score: result.raw_score_pct, passed: result.passed},
      );
      void queryClient.invalidateQueries({queryKey: ["study-next"]});
      void queryClient.invalidateQueries({queryKey: ["study-progress"]});
      void queryClient.invalidateQueries({queryKey: ["adaptive-plan"]});
      navigate(`/study/results/${result.id}`, {replace: true});
    },
    onError: (error, {active}) => {
      // "Already submitted" is not a dead end: scoring runs before the
      // response is written, so a submit whose reply was lost in transit has
      // still been recorded. Stranding the user on an error in front of work
      // that succeeded is worse than showing them the results.
      if (error instanceof ApiError && error.status === 409) {
        clearDraft(active.id);
        void queryClient.invalidateQueries({queryKey: ["study-next"]});
        void queryClient.invalidateQueries({queryKey: ["study-progress"]});
        void queryClient.invalidateQueries({queryKey: ["adaptive-plan"]});
        navigate(`/study/results/${active.id}`, {replace: true});
      }
    },
  });
  const abandon = useMutation({
    mutationFn: (attemptId: number) => queries.abandonDiagnostic(attemptId),
    onSuccess: (result) => {
      clearDraft(result.id);
      void queryClient.invalidateQueries({queryKey: ["study-next"]});
      navigate("/study", {replace: true});
    },
  });

  const current = attempt?.responses[index];
  const expected = current ? expectedSelections(current.prompt_snapshot) : 1;
  const answer = current ? answers[current.question_id] ?? {selected: [], confidence: null} : null;
  const complete = Boolean(answer?.confidence && answer.selected.length === expected);
  const answeredCount = useMemo(() => attempt
    ? attempt.responses.filter((response) => {
      const draft = answers[response.question_id];
      return draft?.confidence
        && draft.selected.length === expectedSelections(response.prompt_snapshot);
    }).length
    : 0, [answers, attempt]);

  if (attemptQuery.isLoading) return <Loading label="Preparing your private knowledge check" />;
  if (attemptQuery.error) return <ErrorNotice error={attemptQuery.error} />;
  if (!attempt || !current || !answer) return <ErrorNotice error={new Error("This check has no questions.")} />;

  function updateAnswer(next: DraftAnswer) {
    const updated = {...answers, [current!.question_id]: next};
    setAnswers(updated);
    writeDraft(attempt!.id, updated);
  }

  function toggleOption(optionIndex: number) {
    if (expected === 1) {
      updateAnswer({...answer!, selected: [optionIndex]});
      return;
    }
    const selected = answer!.selected.includes(optionIndex)
      ? answer!.selected.filter((value) => value !== optionIndex)
      : [...answer!.selected, optionIndex];
    updateAnswer({...answer!, selected});
  }

  function moveNext() {
    if (!complete) return;
    if (index < attempt!.responses.length - 1) {
      setIndex(index + 1);
      window.scrollTo({top: 0, behavior: "smooth"});
      return;
    }
    try {
      submit.mutate({active: attempt!, payload: serializeDiagnostic(attempt!, answers)});
    } catch (error) {
      submit.reset();
    }
  }

  return (
    <>
      <div className="page-title diagnostic-title">
        <span className="eyebrow">{attempt.mode} knowledge check</span>
        <h1>Question {index + 1} of {attempt.responses.length}</h1>
        <p>{answeredCount} answered. Your draft stays on this device if the app closes.</p>
      </div>

      <ProgressBar value={((index + 1) / attempt.responses.length) * 100} />

      <section className="panel diagnostic-card">
        <p className="selection-note">{expected > 1 ? `Select exactly ${expected}` : "Select one answer"}</p>
        <h2>{current.prompt_snapshot}</h2>
        <QuestionFigure figure={current.figure} />
        <fieldset className="answer-options">
          <legend className="sr-only">Answer choices</legend>
          {current.options.map((option, optionIndex) => (
            <label key={option} className={answer.selected.includes(optionIndex) ? "answer-option selected" : "answer-option"}>
              <input
                type={expected > 1 ? "checkbox" : "radio"}
                name="answer"
                checked={answer.selected.includes(optionIndex)}
                onChange={() => toggleOption(optionIndex)}
              />
              <span className="answer-letter">{String.fromCharCode(65 + optionIndex)}</span>
              <span>{option}</span>
            </label>
          ))}
        </fieldset>

        <fieldset className="confidence-options">
          <legend>How confident are you?</legend>
          {(["high", "medium", "low"] as const).map((confidence) => (
            <button
              key={confidence}
              type="button"
              className={answer.confidence === confidence ? "confidence selected" : "confidence"}
              onClick={() => updateAnswer({...answer, confidence})}
            >
              {confidence}
            </button>
          ))}
        </fieldset>

        {submit.error ? <ErrorNotice error={submit.error} /> : null}
        {!complete ? (
          <p className="selection-note" role="status">
            {answer.selected.length < expected
              ? `Select ${expected - answer.selected.length} more answer${expected - answer.selected.length === 1 ? "" : "s"}${answer.confidence ? "." : " and choose your confidence."}`
              : "Choose your confidence to continue."}
          </p>
        ) : null}
        <div className="diagnostic-nav">
          {index > 0
            ? <button className="button secondary" onClick={() => setIndex(index - 1)}>Previous</button>
            : <Link className="button secondary" to="/study">Back to Study</Link>}
          <button className="button primary" aria-busy={submit.isPending} disabled={!complete || submit.isPending} onClick={moveNext}>
            {submit.isPending ? "Scoring..." : index === attempt.responses.length - 1 ? "Submit check" : "Next question"}
          </button>
        </div>
        <button
          className="text-button discard-check"
          disabled={abandon.isPending}
          onClick={() => abandon.mutate(attempt.id)}
        >
          Discard this unfinished check
        </button>
        <p className="fine-print">Answers and explanations remain hidden until submission. This checks recall, not hands-on or PBQ ability.</p>
      </section>
    </>
  );
}
