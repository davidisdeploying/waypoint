import {useEffect, useMemo, useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Link, useNavigate, useParams} from "react-router-dom";
import {queries} from "../api";
import {ErrorNotice, Loading, Metric, Panel, ProgressBar, QuestionFigure, formatDate} from "../components";
import {expectedSelections} from "../diagnostics";
import type {
  PracticeExamAttempt,
  PracticeExamResponse,
  PracticeReadinessBand,
} from "../types";

const readinessLabels: Record<PracticeReadinessBand, string> = {
  review_needed: "Review needed",
  approaching: "Approaching readiness",
  strong_signal: "Strong practice signal",
};

function formatClock(seconds: number) {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function answerText(response: PracticeExamResponse, indexes: number[] = []) {
  return indexes.map((index) => response.options[index] ?? `Option ${index + 1}`);
}

export function PracticeExamsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const overview = useQuery({queryKey: ["practice-exams"], queryFn: queries.practiceExams});
  const start = useMutation({
    mutationFn: queries.startPracticeExam,
    onSuccess: (attempt) => {
      void queryClient.invalidateQueries({queryKey: ["practice-exams"]});
      navigate(`/practice/${attempt.id}`);
    },
  });
  if (overview.isLoading) return <Loading label="Opening practice exams" />;
  if (overview.error) return <ErrorNotice error={overview.error} />;
  const data = overview.data!;
  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Full practice exams</span>
        <h1>Rehearse the complete exam</h1>
        <p>
          Ninety questions, ninety minutes, automatic answer saves, and review only
          after submission.
        </p>
      </div>
      <div className="metric-grid compact">
        <Metric value={data.question_target} label="Questions" />
        <Metric value={data.duration_minutes} label="Minutes" accent />
        <Metric value="2" label="A+ exams" />
      </div>
      <div className="practice-exam-grid">
        {data.exams.map((exam) => (
          <Panel
            key={exam.id}
            eyebrow={exam.code}
            title={exam.name}
            action={exam.in_progress ? (
              <Link className="button primary" to={`/practice/${exam.in_progress.id}`}>Resume exam</Link>
            ) : (
              <button
                className="button primary"
                disabled={start.isPending}
                onClick={() => start.mutate(exam.code)}
              >
                Start 90-minute exam
              </button>
            )}
          >
            <p>
              {exam.reserved_questions
                ? `${exam.reserved_questions} questions protected in the held-out pool.`
                : "The protected pool will be sealed when you start your first attempt."}
            </p>
            {exam.recent_attempts.length ? (
              <ol className="practice-history">
                {exam.recent_attempts.map((attempt) => (
                  <li key={attempt.id}>
                    <Link to={`/practice/${attempt.id}`}>
                      <strong>{formatDate(attempt.started_at)}</strong>
                      <span>
                        {attempt.state === "submitted"
                          ? `${attempt.raw_score_pct}% · ${readinessLabels[attempt.readiness_band!]}`
                          : attempt.state.replace("_", " ")}
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
            ) : <p className="notice">No attempts yet.</p>}
          </Panel>
        ))}
      </div>
      {start.error ? <ErrorNotice error={start.error} /> : null}
      <p className="fine-print">{data.pool_note} {data.evidence_note}</p>
    </>
  );
}

function ExamResults({attempt}: {attempt: PracticeExamAttempt}) {
  return (
    <>
      <div className="page-title">
        <span className="eyebrow">{attempt.exam_code} practice exam complete</span>
        <h1>{attempt.raw_score_pct}%</h1>
        <p>{readinessLabels[attempt.readiness_band!]} · {attempt.answered_count} of {attempt.question_target} answered.</p>
      </div>
      <div className="result-strip">
        <div><strong>{attempt.raw_score_pct}%</strong><span>Raw practice score</span></div>
        <div><strong>{attempt.answered_count}</strong><span>Answered</span></div>
        <div><strong>{attempt.timed_out ? "Yes" : "No"}</strong><span>Time expired</span></div>
      </div>
      <Panel eyebrow="Domain breakdown" title="Where the result came from">
        <div className="exam-domain-results">
          {attempt.breakdown?.domains.map((domain) => (
            <div key={domain.domain_code}>
              <span>Domain {domain.domain_code}</span>
              <strong>{domain.score_pct}%</strong>
              <small>{domain.correct} of {domain.total} · {domain.domain_name}</small>
              <ProgressBar value={domain.score_pct} />
            </div>
          ))}
        </div>
        <p className="fine-print">{attempt.breakdown?.mapping_note}</p>
      </Panel>
      <Panel eyebrow="Question review" title="Compare every response">
        <ol className="practice-review-list">
          {attempt.responses.map((response) => (
            <li key={response.id} className={response.is_correct ? "correct" : "incorrect"}>
              <details>
                <summary>
                  <span>{response.is_correct ? "Correct" : "Review"}</span>
                  <strong>{response.position + 1}. {response.prompt_snapshot}</strong>
                </summary>
                <div className="answer-comparison">
                  <div>
                    <span>Your answer</span>
                    <strong>{answerText(response, response.submitted_answer).join("; ") || "Unanswered"}</strong>
                  </div>
                  <div>
                    <span>Correct answer</span>
                    <strong>{answerText(response, response.correct_answers).join("; ")}</strong>
                  </div>
                </div>
                {response.explanation ? <p>{response.explanation}</p> : null}
                <small>Domain {response.domain_code} · {response.mapping_granularity}-mapped</small>
              </details>
            </li>
          ))}
        </ol>
      </Panel>
      <Link className="button primary" to="/practice">Back to practice exams</Link>
      <p className="fine-print">
        This is a Waypoint practice-readiness signal, not an official CompTIA scaled
        score or pass guarantee.
      </p>
    </>
  );
}

export function PracticeExamPage() {
  const {attemptId: rawAttemptId} = useParams();
  const attemptId = Number(rawAttemptId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [index, setIndex] = useState(0);
  const [clockTick, setClockTick] = useState(Date.now());
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const attemptQuery = useQuery({
    queryKey: ["practice-exam", attemptId],
    queryFn: () => queries.practiceExam(attemptId),
    enabled: Number.isInteger(attemptId) && attemptId > 0,
    retry: false,
  });
  const attempt = attemptQuery.data;
  useEffect(() => {
    if (!attempt || attempt.state !== "in_progress") return;
    const timer = window.setInterval(() => setClockTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [attempt?.id, attempt?.state]);
  const remaining = attempt
    ? Math.max(0, Math.floor((new Date(attempt.expires_at).getTime() - clockTick) / 1000))
    : 0;
  const save = useMutation({
    mutationFn: ({questionId, selected}: {questionId: number; selected: number[]}) =>
      queries.savePracticeExamAnswer(attemptId, questionId, selected),
    onSuccess: (saved) => {
      queryClient.setQueryData<PracticeExamAttempt>(
        ["practice-exam", attemptId],
        (current) => current ? {
          ...current,
          answered_count: saved.answered_count,
          responses: current.responses.map((response) =>
            response.question_id === saved.question_id
              ? {...response, submitted_answer: saved.selected}
              : response,
          ),
        } : current,
      );
    },
    onError: () => void attemptQuery.refetch(),
  });
  const submit = useMutation({
    mutationFn: () => queries.submitPracticeExam(attemptId),
    onSuccess: (result) => {
      queryClient.setQueryData(["practice-exam", attemptId], result);
      void queryClient.invalidateQueries({queryKey: ["practice-exams"]});
      window.scrollTo({top: 0, behavior: "smooth"});
    },
  });
  const abandon = useMutation({
    mutationFn: () => queries.abandonPracticeExam(attemptId),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: ["practice-exams"]});
      navigate("/practice", {replace: true});
    },
  });
  const current = attempt?.responses[index];
  const expected = current ? expectedSelections(current.prompt_snapshot) : 1;
  const answeredIndexes = useMemo(
    () => attempt?.responses
      .map((response, position) => response.submitted_answer.length ? position : -1)
      .filter((position) => position >= 0) ?? [],
    [attempt],
  );

  if (attemptQuery.isLoading) return <Loading label="Resuming your practice exam" />;
  if (attemptQuery.error) return <ErrorNotice error={attemptQuery.error} />;
  if (!attempt) return <ErrorNotice error={new Error("Practice exam not found.")} />;
  if (attempt.state === "submitted") return <ExamResults attempt={attempt} />;
  if (attempt.state === "abandoned") {
    return <Panel title="This practice exam was abandoned"><Link className="button primary" to="/practice">Return to exams</Link></Panel>;
  }
  if (!current) return <ErrorNotice error={new Error("This practice exam has no questions.")} />;

  function choose(optionIndex: number) {
    const selected = expected === 1
      ? [optionIndex]
      : current!.submitted_answer.includes(optionIndex)
        ? current!.submitted_answer.filter((value) => value !== optionIndex)
        : [...current!.submitted_answer, optionIndex];
    queryClient.setQueryData<PracticeExamAttempt>(
      ["practice-exam", attemptId],
      (cached) => cached ? {
        ...cached,
        responses: cached.responses.map((response) =>
          response.question_id === current!.question_id
            ? {...response, submitted_answer: selected}
            : response,
        ),
      } : cached,
    );
    save.mutate({questionId: current!.question_id, selected});
  }

  return (
    <>
      <div className="practice-exam-header">
        <div>
          <span className="eyebrow">{attempt.exam_code} full practice exam</span>
          <h1>Question {index + 1} of {attempt.question_target}</h1>
        </div>
        <div className={remaining <= 300 ? "exam-timer urgent" : "exam-timer"}>
          <span>Time remaining</span>
          <strong>{formatClock(remaining)}</strong>
        </div>
      </div>
      <div className="exam-progress-row">
        <span>{attempt.answered_count} answered</span>
        <ProgressBar value={(attempt.answered_count / attempt.question_target) * 100} />
      </div>
      <section className="panel diagnostic-card practice-question-card">
        <p className="selection-note">{expected > 1 ? `Select exactly ${expected}` : "Select one answer"}</p>
        <h2>{current.prompt_snapshot}</h2>
        <QuestionFigure figure={current.figure} />
        <fieldset className="answer-options">
          <legend className="sr-only">Answer choices</legend>
          {current.options.map((option, optionIndex) => (
            <label
              key={`${option}-${optionIndex}`}
              className={current.submitted_answer.includes(optionIndex) ? "answer-option selected" : "answer-option"}
            >
              <input
                type={expected > 1 ? "checkbox" : "radio"}
                name="practice-answer"
                checked={current.submitted_answer.includes(optionIndex)}
                onChange={() => choose(optionIndex)}
              />
              <span className="answer-letter">{String.fromCharCode(65 + optionIndex)}</span>
              <span>{option}</span>
            </label>
          ))}
        </fieldset>
        {save.error ? <ErrorNotice error={save.error} /> : null}
        <div className="diagnostic-nav">
          <button
            className="button secondary"
            disabled={index === 0}
            onClick={() => setIndex(index - 1)}
          >
            Previous
          </button>
          <button
            className="button primary"
            disabled={index >= attempt.responses.length - 1}
            onClick={() => setIndex(index + 1)}
          >
            Next
          </button>
        </div>
        <div className="question-map" aria-label="Practice exam questions">
          {attempt.responses.map((response, position) => (
            <button
              key={response.id}
              className={`${position === index ? "current " : ""}${answeredIndexes.includes(position) ? "answered" : ""}`}
              onClick={() => setIndex(position)}
              aria-label={`Question ${position + 1}${response.submitted_answer.length ? ", answered" : ""}`}
            >
              {position + 1}
            </button>
          ))}
        </div>
      </section>
      {remaining === 0 ? <p className="notice error">Time has expired. Submit the answers currently saved.</p> : null}
      {confirmSubmit ? (
        <div className="notice submit-confirmation">
          <strong>Submit this exam?</strong>
          <p>{attempt.question_target - attempt.answered_count} questions are unanswered. Answers cannot be changed after submission.</p>
          <div className="action-row">
            <button className="button primary" disabled={submit.isPending} onClick={() => submit.mutate()}>
              {submit.isPending ? "Scoring..." : "Submit and score"}
            </button>
            <button className="button secondary" onClick={() => setConfirmSubmit(false)}>Keep working</button>
          </div>
        </div>
      ) : (
        <button className="button secondary" onClick={() => setConfirmSubmit(true)}>Review and submit</button>
      )}
      {submit.error ? <ErrorNotice error={submit.error} /> : null}
      <button className="text-button discard-check" disabled={abandon.isPending} onClick={() => abandon.mutate()}>
        Abandon this exam
      </button>
      <p className="fine-print">{attempt.selection_disclosure} Correct answers and explanations remain hidden until submission.</p>
    </>
  );
}
