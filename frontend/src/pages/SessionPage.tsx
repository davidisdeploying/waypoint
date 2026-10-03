import {useEffect, useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Link, useNavigate} from "react-router-dom";
import {queries} from "../api";
import {ErrorNotice, Loading, Panel, ProgressBar} from "../components";
import {activeElapsedMinutes, sessionActionPath} from "../sessions";
import type {DailyStudySession} from "../types";

const eventLabels: Record<string, string> = {
  reading_opened: "Book section opened",
  gap_reviewed: "Missed question reviewed",
  knowledge_check_completed: "Knowledge check completed",
  task_completed: "Curriculum task completed",
  coach_used: "Study Coach used",
};

export function SessionPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const overview = useQuery({
    queryKey: ["daily-session"],
    queryFn: queries.dailySession,
    refetchInterval: 60_000,
    refetchOnMount: "always",
  });
  const [now, setNow] = useState(Date.now());
  const [notes, setNotes] = useState("");
  const [completed, setCompleted] = useState<DailyStudySession | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const finish = useMutation({
    mutationFn: ({id, sessionNotes}: {id: number; sessionNotes: string}) =>
      queries.finishDailySession(id, sessionNotes),
    onSuccess: (result) => {
      setCompleted(result);
      void queryClient.invalidateQueries({queryKey: ["daily-session"]});
      void queryClient.invalidateQueries({queryKey: ["study-goal"]});
      void queryClient.invalidateQueries({queryKey: ["study-dashboard"]});
      void queryClient.invalidateQueries({queryKey: ["study-progress"]});
      void queryClient.invalidateQueries({queryKey: ["study-next"]});
    },
  });
  const abandon = useMutation({
    mutationFn: (id: number) => queries.abandonDailySession(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: ["daily-session"]});
      navigate("/");
    },
  });

  if (overview.isLoading) return <Loading label="Opening today’s study session" />;
  if (overview.error) return <ErrorNotice error={overview.error} />;

  if (completed) {
    return (
      <>
        <div className="page-title">
          <span className="eyebrow">Session complete</span>
          <h1>Useful work recorded</h1>
          <p>{completed.duration_minutes} minutes were added to your progress.</p>
        </div>
        <Panel eyebrow="Recap" title={completed.task_title}>
          <ul className="recap-list">
            {completed.recap?.lines.map((line) => <li key={line}>{line}</li>)}
          </ul>
          {completed.notes ? <p className="session-note">Your note: {completed.notes}</p> : null}
          <Link className="button primary" to="/">See what’s next</Link>
        </Panel>
      </>
    );
  }

  const active = overview.data!.active;
  if (!active) {
    return (
      <>
        <div className="page-title">
          <span className="eyebrow">Daily study</span>
          <h1>No session in progress</h1>
          <p>Start from Today so Waypoint can connect the session to your next useful task.</p>
        </div>
        <Link className="button primary" to="/">Go to Today</Link>
      </>
    );
  }

  const elapsed = activeElapsedMinutes(active, now);
  const progress = Math.min(100, (elapsed / active.target_minutes) * 100);
  const staleDays = Math.floor((now - new Date(active.started_at).getTime()) / 86_400_000);
  const stalePaused = active.tracking_state === "paused" && staleDays >= 1;

  return (
    <>
      <div className="page-title session-title">
        <span className="eyebrow">Session underway</span>
        <h1>{active.task_title}</h1>
        <p>Study tasks start or resume timing automatically. Waypoint pauses on non-study screens, after five idle minutes, when you switch apps, or when you lock your phone.</p>
      </div>

      {stalePaused ? (
        <Panel eyebrow="Paused session recovery" title={`This session began ${staleDays} day${staleDays === 1 ? "" : "s"} ago`}>
          <p>Choose deliberately: resume the task, save the real time already captured, or abandon this unfinished session.</p>
          <div className="action-row">
            <Link className="button primary" to={sessionActionPath(active.task_action)}>Resume task</Link>
            <button className="button secondary" disabled={finish.isPending} onClick={() => finish.mutate({id: active.id, sessionNotes: notes})}>Finish and save</button>
            <button className="button secondary" disabled={abandon.isPending} onClick={() => abandon.mutate(active.id)}>Abandon session</button>
          </div>
        </Panel>
      ) : null}

      <div className="session-clock">
        <div><strong>{elapsed}</strong><span>minutes studied</span></div>
        <div><strong>{active.target_minutes}</strong><span>minute target</span></div>
        <div><strong>{active.events.length}</strong><span>activities captured</span></div>
      </div>
      <ProgressBar value={progress} />

      <Panel
        eyebrow="Current focus"
        title="Continue today’s task"
        action={<Link className="button primary" to={sessionActionPath(active.task_action)}>Open task</Link>}
      >
        <p className="large-copy">{active.task_title}</p>
        <p>Waypoint will capture supported activity while this session remains open.</p>
      </Panel>

      <Panel eyebrow="Captured automatically" title="What you’ve done">
        {active.events.length ? (
          <ol className="session-events">
            {active.events.map((event) => (
              <li key={event.id}>
                <span>{eventLabels[event.event_type] ?? event.event_type}</span>
                <strong>{event.label}</strong>
              </li>
            ))}
          </ol>
        ) : (
          <p className="notice">No activity yet. Open today’s task and begin; this list will fill as you work.</p>
        )}
      </Panel>

      <Panel eyebrow="Finish" title="Close the loop">
        <label className="session-notes">
          Optional note
          <textarea
            value={notes}
            maxLength={2000}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Anything you want to remember from this session?"
          />
        </label>
        {finish.error ? <ErrorNotice error={finish.error} /> : null}
        {abandon.error ? <ErrorNotice error={abandon.error} /> : null}
        <div className="action-row">
          <button
            className="button primary"
            disabled={finish.isPending}
            onClick={() => finish.mutate({id: active.id, sessionNotes: notes})}
          >
            {finish.isPending ? "Saving recap..." : "Finish and save session"}
          </button>
          <button
            className="button secondary"
            disabled={abandon.isPending}
            onClick={() => abandon.mutate(active.id)}
          >
            End without recording
          </button>
        </div>
      </Panel>
    </>
  );
}
