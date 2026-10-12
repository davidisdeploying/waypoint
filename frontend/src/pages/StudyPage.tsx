import {useState} from "react";
import {useMutation, useQuery} from "@tanstack/react-query";
import {Link} from "react-router-dom";
import {queries, trackStudyEvent} from "../api";
import {ErrorNotice, Loading, Metric, Panel} from "../components";
import type {CoachResponse} from "../types";
import {sessionActionPath} from "../sessions";

function CoachAnswer({response}: {response: CoachResponse}) {
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
      <div className="citation-list">
        {response.answer.citations.map((citation) => (
          <a
            key={citation.citation_id}
            href={`/api/v2/study/sections/${encodeURIComponent(citation.citation_id)}`}
            target="_blank"
            rel="noreferrer"
          >
            {citation.book_title}: {citation.section_title}
          </a>
        ))}
      </div>
      <p className="fine-print">{response.answer.caveat}</p>
    </div>
  );
}

export function StudyPage() {
  const [question, setQuestion] = useState("");
  const [studyMinutesOverride, setStudyMinutesOverride] = useState<number | null>(null);
  const [customMinutes, setCustomMinutes] = useState("");
  const nextQuery = useQuery({queryKey: ["study-next"], queryFn: queries.studyNext});
  const progressQuery = useQuery({queryKey: ["study-progress"], queryFn: queries.progress});
  const goalQuery = useQuery({queryKey: ["study-goal"], queryFn: queries.studyGoal});
  const goalMinutes = goalQuery.data?.daily_target_minutes ?? 45;
  const studyMinutes = studyMinutesOverride ?? goalMinutes;
  const adaptiveQuery = useQuery({
    queryKey: ["adaptive-plan", studyMinutes],
    queryFn: () => queries.adaptive(studyMinutes),
  });
  const coach = useMutation({
    mutationFn: ({mode, prompt}: {mode: string; prompt?: string}) =>
      queries.coach(mode, prompt),
    onSuccess: (response) => {
      trackStudyEvent(
        "coach_used",
        response.answer.title,
        `coach:${Date.now()}`,
      );
    },
  });

  if (nextQuery.isLoading || progressQuery.isLoading || goalQuery.isLoading || adaptiveQuery.isLoading) {
    return <Loading label="Building today’s study view" />;
  }
  const error = nextQuery.error || progressQuery.error || goalQuery.error || adaptiveQuery.error;
  if (error) return <ErrorNotice error={error} />;

  const next = nextQuery.data!;
  const progress = progressQuery.data!;
  const adaptive = adaptiveQuery.data!;
  const primaryAction = next.primary?.action;
  let primaryButton = null;
  if (primaryAction?.type === "diagnostic" && primaryAction.scope_id) {
    primaryButton = (
      <Link
        className="button primary"
        to={`/study/check/${primaryAction.scope_id}?mode=${primaryAction.mode ?? "diagnostic"}`}
      >
        Begin knowledge check
      </Link>
    );
  } else if (next.primary?.kind === "remediation" && primaryAction?.scope_id) {
    primaryButton = (
      <Link className="button primary" to={`/study/remediate/${primaryAction.scope_id}`}>
        Start guided review
      </Link>
    );
  }

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Study</span>
        <h1>{next.week_title}</h1>
        <p>Learn the certification from beginning to end, test out of material you already know, or focus directly on gaps.</p>
      </div>

      <div className="metric-grid compact">
        <Metric value={progress.current_week_tasks.remaining} label="Current-week tasks" />
        <Metric value={progress.current_week_tasks.exempted} label="Tasks exempted" />
        <Metric value={progress.study_minutes_last_7_days} label="Minutes, 7 days" />
        <Metric value={`${progress.domains_mastered} / ${progress.domains_available}`} label="Domain checks passed" />
        <Metric value={progress.current_streak_days} label="Day streak" accent />
      </div>

      <Panel
        eyebrow="Start here"
        title={next.primary?.title ?? "Study queue clear"}
        action={primaryButton}
      >
        <p className="large-copy">{next.primary?.description}</p>
        <p>{next.primary?.reason}</p>
      </Panel>

      <div className="two-column study-evidence-context">
        <Panel
          eyebrow="Exam readiness"
          title={adaptive.readiness.label}
          action={adaptive.readiness.next_gate ? (
            <Link className="button secondary" to={adaptive.readiness.next_gate.action.href}>
              Work on next gate
            </Link>
          ) : null}
        >
          <p className="large-copy">
            {adaptive.readiness.passed_gate_count} of {adaptive.readiness.total_gate_count} evidence gates passed.
          </p>
          {adaptive.readiness.next_gate ? (
            <div className="readiness-next-gate">
              <strong>{adaptive.readiness.next_gate.label}</strong>
              <p>{adaptive.readiness.next_gate.rationale}</p>
            </div>
          ) : <p>All source, learning, recall, retention, hands-on, and fresh-exam gates have direct evidence.</p>}
          <p className="fine-print">{adaptive.readiness.evidence_note}</p>
        </Panel>

        <Panel
          eyebrow="Career connection"
          title={adaptive.career_context.alignment?.relevance === "direct" ? "Directly aligned" : "Supporting knowledge"}
        >
          {adaptive.career_context.alignment ? (
            <>
              <p className="large-copy">
                Supports {adaptive.career_context.alignment.job_families.join(", ")} work.
              </p>
              {adaptive.career_context.alignment.note ? <p>{adaptive.career_context.alignment.note}</p> : null}
              <p className="fine-print">
                Career references: {adaptive.career_context.alignment.claim_ids.join(", ")}. Canonical source {adaptive.career_context.canonical_source.status}.
              </p>
            </>
          ) : <p>No Career claim mapping exists for this certification yet.</p>}
          <p className="fine-print">Career context prioritizes examples and labs; it never removes official exam scope or grants mastery.</p>
        </Panel>
      </div>

      <details className="study-tools">
        <summary>Study tools</summary>
        <div className="study-tool-grid">
          <Link to="/learn"><strong>Learn</strong><span>Lessons and recall</span></Link>
          <Link to="/mastery"><strong>Mastery map</strong><span>Evidence by objective</span></Link>
          <Link to="/analytics"><strong>Analytics</strong><span>Separate evidence signals</span></Link>
          <Link to="/labs"><strong>Labs</strong><span>Repeatable hands-on work</span></Link>
          <Link to="/practice"><strong>Practice exams</strong><span>Timed exam endurance</span></Link>
        </div>
      </details>

      <div className="two-column">
        <Panel eyebrow="Adaptive queue" title="What follows">
          <ol className="task-list">
            {next.items.slice(1).map((item) => (
              <li key={item.id}>
                <span className="task-kind">{item.eyebrow}</span>
                <strong>{item.title}</strong>
                <p>{item.description}</p>
              </li>
            ))}
          </ol>
        </Panel>
        <Panel eyebrow="Seven-day plan" title={adaptive.provisional ? "Adapts after your check" : "Current plan"}>
          <div className="duration-options plan-duration" aria-label="Daily study time">
            {[25, 45, 60, goalMinutes].filter((minutes, index, values) => values.indexOf(minutes) === index).sort((a, b) => a - b).map((minutes) => (
              <button
                key={minutes}
                type="button"
                className={studyMinutes === minutes ? "selected" : ""}
                onClick={() => setStudyMinutesOverride(minutes === goalMinutes ? null : minutes)}
              >
                {minutes} min/day
              </button>
            ))}
            <input
              aria-label="Custom temporary plan minutes"
              type="number"
              min={15}
              max={240}
              value={customMinutes}
              placeholder="Custom"
              onChange={(event) => {
                setCustomMinutes(event.target.value);
                const value = Number(event.target.value);
                if (Number.isInteger(value) && value >= 15 && value <= 240) setStudyMinutesOverride(value);
              }}
            />
          </div>
          <p className="fine-print">
            {studyMinutesOverride === null
              ? `Using your weekly goal: ${goalMinutes} minutes per day.`
              : `Temporary planning override: ${studyMinutes} minutes per day. Your saved weekly goal remains ${goalMinutes}.`}
          </p>
          <ol className="week-plan-list">
            {adaptive.schedule.map((day) => (
              <li key={day.day}>
                <div className="plan-day-heading">
                  <time>{new Date(`${day.date}T12:00:00`).toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric"})}</time>
                  <span>{day.planned_minutes} / {day.target_minutes} min</span>
                </div>
                {day.items.length ? (
                  <ul>
                    {day.items.map((item) => (
                      <li key={item.id}>
                        <Link to={sessionActionPath(item.action)}>
                          <strong>{item.title}</strong>
                          <span>{item.estimated_minutes} min</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                ) : <strong>Flex or catch-up</strong>}
              </li>
            ))}
          </ol>
          <p className="fine-print">
            {adaptive.retention.due} memory reviews due · {adaptive.retention.upcoming} upcoming · {adaptive.unscheduled_item_count} later items remain in the queue.
          </p>
        </Panel>
      </div>

      <Panel eyebrow="Subscription-backed AI" title="Study Coach">
        <div className="coach-actions">
          <button className="button secondary" onClick={() => coach.mutate({mode: "today"})} disabled={coach.isPending}>Today’s lesson</button>
          <button className="button secondary" onClick={() => coach.mutate({mode: "gaps"})} disabled={coach.isPending}>Explain my gaps</button>
          <button className="button secondary" onClick={() => coach.mutate({mode: "practice"})} disabled={coach.isPending}>Practice session</button>
        </div>
        <div className="coach-form">
          <label htmlFor="coach-question">Ask about the current material</label>
          <textarea
            id="coach-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Explain USB connector generations and what I need to recognize."
            maxLength={1000}
          />
          <button
            className="button primary"
            disabled={coach.isPending || !question.trim()}
            onClick={() => coach.mutate({mode: "ask", prompt: question.trim()})}
          >
            {coach.isPending ? "Reading your sources..." : "Ask Coach"}
          </button>
        </div>
        {coach.error ? <ErrorNotice error={coach.error} /> : null}
        {coach.data ? <CoachAnswer response={coach.data} /> : null}
        <p className="fine-print">Book excerpts are bounded and cited. The practice-question bank is excluded from teaching retrieval.</p>
      </Panel>
    </>
  );
}
