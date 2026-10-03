import {useState} from "react";
import {useMutation, useQuery} from "@tanstack/react-query";
import {Link, useNavigate} from "react-router-dom";
import {getWaypointState, queries} from "../api";
import {ErrorNotice, Loading, Metric, Panel, ProgressBar} from "../components";
import {
  MAX_SESSION_MINUTES,
  MIN_SESSION_MINUTES,
  SESSION_PRESET_MINUTES,
  parseSessionMinutes,
  sessionActionPath,
} from "../sessions";

export function HomePage() {
  const navigate = useNavigate();
  const [targetMinutes, setTargetMinutes] = useState(25);
  const [customOpen, setCustomOpen] = useState(false);
  const [customMinutes, setCustomMinutes] = useState("");
  const stateQuery = useQuery({queryKey: ["waypoint-state"], queryFn: getWaypointState});
  const studyQuery = useQuery({queryKey: ["study-dashboard"], queryFn: queries.dashboard});
  const nextQuery = useQuery({queryKey: ["study-next"], queryFn: queries.studyNext});
  const sessionQuery = useQuery({queryKey: ["daily-session"], queryFn: queries.dailySession});
  const goalQuery = useQuery({queryKey: ["study-goal"], queryFn: queries.studyGoal});
  const planMinutes = goalQuery.data?.daily_target_minutes ?? 45;
  const planQuery = useQuery({
    queryKey: ["adaptive-plan", planMinutes],
    queryFn: () => queries.adaptive(planMinutes),
    enabled: goalQuery.isSuccess,
  });
  const startSession = useMutation({
    mutationFn: queries.startDailySession,
    onSuccess: () => {
      void sessionQuery.refetch();
      navigate("/session");
    },
  });

  if (stateQuery.isLoading || studyQuery.isLoading || nextQuery.isLoading || sessionQuery.isLoading || goalQuery.isLoading || planQuery.isLoading) {
    return <Loading label="Assembling your Waypoint" />;
  }
  if (stateQuery.error) return <ErrorNotice error={stateQuery.error} />;
  if (studyQuery.error) return <ErrorNotice error={studyQuery.error} />;
  if (nextQuery.error) return <ErrorNotice error={nextQuery.error} />;
  if (sessionQuery.error) return <ErrorNotice error={sessionQuery.error} />;
  if (goalQuery.error) return <ErrorNotice error={goalQuery.error} />;
  if (planQuery.error) return <ErrorNotice error={planQuery.error} />;

  const state = stateQuery.data?.state;
  const hasMilestoneState = Boolean(state?.certs.length);
  const study = studyQuery.data!;
  const next = nextQuery.data!;
  const daily = sessionQuery.data!;
  const plan = planQuery.data!;
  const todayPlan = plan.schedule[0];
  const passed = state?.certs.filter((cert) => cert.status === "passed") ?? [];
  const current = state?.certs.find((cert) => cert.status === "scheduled") ??
    state?.certs.find((cert) => cert.status === "studying") ??
    state?.certs.find((cert) => cert.status === "todo");
  const banked = passed.reduce((total, cert) => total + cert.cu, 0);
  const accounted = 50 + banked;
  const degreePct = Math.round((accounted / 109) * 1000) / 10;
  const taskPct = study.total_tasks
    ? Math.round((study.completed_tasks / study.total_tasks) * 100)
    : 0;
  // null means "not a usable length yet", which is what disables Start.
  const customTargetMinutes = parseSessionMinutes(customMinutes);
  const sessionMinutes = customOpen ? customTargetMinutes : targetMinutes;

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Today</span>
        <h1>{daily.active ? "Continue where you left off" : "One useful study session"}</h1>
        <p>Waypoint chooses the next task, records supported activity, and turns it into a useful recap.</p>
      </div>

      <div className="hero-action">
        <div>
          <span className="eyebrow">{daily.active ? "Session underway" : next.primary?.eyebrow ?? "Study next"}</span>
          <h2>{daily.active?.task_title ?? next.primary?.title ?? "Choose the next study task"}</h2>
          <p>
            {daily.active
              ? `${daily.active.elapsed_minutes ?? 0} of ${daily.active.target_minutes} target minutes recorded so far.`
              : next.primary?.description ?? "Your adaptive queue is clear."}
          </p>
        </div>
        {daily.active ? (
          <Link className="button primary" to="/session">
            {daily.active.tracking_state === "paused" && Date.now() - new Date(daily.active.started_at).getTime() > 86_400_000
              ? "Review paused session" : "Continue session"}
          </Link>
        ) : (
          <div className="session-start">
            <div className="duration-options session-length-options" aria-label="Session length">
              {SESSION_PRESET_MINUTES.map((minutes) => (
                <button
                  key={minutes}
                  type="button"
                  className={!customOpen && targetMinutes === minutes ? "selected" : ""}
                  onClick={() => {
                    setCustomOpen(false);
                    setTargetMinutes(minutes);
                  }}
                >
                  {minutes} min
                </button>
              ))}
              <button
                type="button"
                className={customOpen ? "selected" : ""}
                onClick={() => setCustomOpen(true)}
              >
                Custom
              </button>
            </div>
            {customOpen ? (
              <>
                <label className="custom-duration">
                  <span className="sr-only">Session length in minutes</span>
                  <input
                    type="number"
                    inputMode="numeric"
                    min={MIN_SESSION_MINUTES}
                    max={MAX_SESSION_MINUTES}
                    step={1}
                    autoFocus
                    value={customMinutes}
                    placeholder={`${MIN_SESSION_MINUTES}-${MAX_SESSION_MINUTES}`}
                    onChange={(event) => setCustomMinutes(event.target.value)}
                  />
                  <span aria-hidden="true">min</span>
                </label>
                {customMinutes && customTargetMinutes === null ? (
                  <p className="notice error">
                    Enter a whole number of minutes between {MIN_SESSION_MINUTES} and{" "}
                    {MAX_SESSION_MINUTES}.
                  </p>
                ) : null}
              </>
            ) : null}
            <button
              className="button primary"
              disabled={startSession.isPending || sessionMinutes === null}
              onClick={() => {
                if (sessionMinutes !== null) startSession.mutate(sessionMinutes);
              }}
            >
              {startSession.isPending ? "Starting..." : "Start study session"}
            </button>
          </div>
        )}
      </div>
      {startSession.error ? <ErrorNotice error={startSession.error} /> : null}

      <Panel
        eyebrow="Today’s adaptive plan"
        title={`${todayPlan.planned_minutes} of ${todayPlan.target_minutes} minutes planned`}
        action={<Link className="text-link" to="/study">Open full week</Link>}
      >
        {todayPlan.items.length ? (
          <ol className="today-plan-list">
            {todayPlan.items.map((item) => (
              <li key={item.id}>
                <div>
                  <span className="task-kind">{item.eyebrow}</span>
                  <strong>{item.title}</strong>
                  <p>{item.estimated_minutes} minutes · {item.reason}</p>
                </div>
                <Link className="button secondary" to={sessionActionPath(item.action)}>
                  Open
                </Link>
              </li>
            ))}
          </ol>
        ) : (
          <p className="notice">{todayPlan.note}</p>
        )}
        {plan.retention.due || plan.retention.upcoming ? (
          <p className="fine-print">
            {plan.retention.due} memory review{plan.retention.due === 1 ? "" : "s"} due now · {plan.retention.upcoming} scheduled this week.
          </p>
        ) : null}
      </Panel>

      <div className="metric-grid">
        <Metric value={accounted} label="CU accounted for" detail={`${degreePct}% of 109 CU`} />
        <Metric value={`${passed.length} / ${state?.certs.length ?? 6}`} label="Credentials passed" />
        <Metric value={daily.today.minutes} label="Minutes today" detail={`${daily.today.sessions} completed session${daily.today.sessions === 1 ? "" : "s"}`} />
        <Metric value={`${study.diagnostics.diagnostic_checks_passed} / ${study.diagnostics.diagnostic_checks_available}`} label="Domain checks passed" accent />
        <Metric value={study.diagnostics.current_gap_count} label="Open focused gaps" />
      </div>

      <div className="two-column">
        <Panel
          eyebrow="Current credential"
          title={current?.name ?? (hasMilestoneState ? "Credential path complete" : "Milestone data not initialized")}
        >
          <p className="large-copy">
            {current?.code ?? (hasMilestoneState ? "All planned credentials passed" : "Open Journey to review the credential path.")}
          </p>
          <p>
            {current
              ? `${current.cu} CU · ${current.status}`
              : hasMilestoneState
                ? "Confirm enrollment readiness."
                : "Your Study Library data is connected; credential milestones still need their first sync."}
          </p>
          <Link className="text-link" to="/journey">Open Journey</Link>
        </Panel>
        <Panel eyebrow="Next curriculum section" title={study.week_title}>
          <p className="large-copy">{study.readiness_label}</p>
          <ProgressBar value={taskPct} />
          <p>{study.completed_tasks} of {study.total_tasks} curriculum tasks complete.</p>
        </Panel>
      </div>

      <Panel
        eyebrow="Evidence"
        title="What the system currently knows"
        action={<Link className="text-link" to="/mastery">Open mastery map</Link>}
      >
        <div className="evidence-grid">
          <div><strong>{study.diagnostics.domain_mastery_pct}%</strong><span>Diagnostic domain mastery</span></div>
          <div><strong>{Math.round(study.objective_coverage)}%</strong><span>Objective evidence coverage</span></div>
          <div><strong>{study.practice_average_recent ?? "N/A"}</strong><span>Recent held-out practice</span></div>
          <div><strong>{next.counts.retention_due}</strong><span>Retention reviews due</span></div>
        </div>
        <p className="fine-print">These are evidence summaries, not a guarantee of exam readiness or hands-on ability.</p>
      </Panel>
    </>
  );
}
