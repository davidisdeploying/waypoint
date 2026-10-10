import {useEffect, useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {queries} from "./api";
import {activeElapsedMinutes} from "./sessions";
import type {DailySessionOverview, StudyGoal} from "./types";

// Minute-granularity display, so a quarter-minute tick is smooth enough and
// costs far less than re-fetching the goal.
const TICK_MS = 15_000;

function liveMinutes(overview: DailySessionOverview | undefined, goal: StudyGoal | undefined, now: number) {
  const active = overview?.active;
  if (!active || !goal) return 0;
  if (active.tracking_state !== "running") return 0;
  // Compare instants, not date strings: a session started late Sunday local
  // time is already Monday in UTC and would otherwise be filed under this week.
  const started = Date.parse(active.started_at);
  const begin = Date.parse(goal.week_begin_utc);
  const end = Date.parse(goal.week_end_utc);
  if (!Number.isFinite(started) || started < begin || started >= end) return 0;
  return activeElapsedMinutes(active, now);
}

export function WeeklyGoalBar({readOnly = false}: {readOnly?: boolean} = {}) {
  const queryClient = useQueryClient();
  const [now, setNow] = useState(() => Date.now());
  const goal = useQuery({
    queryKey: ["study-goal"],
    queryFn: queries.studyGoal,
    staleTime: 30_000,
  });
  const overview = useQuery({
    queryKey: ["daily-session"],
    queryFn: queries.dailySession,
    staleTime: 15_000,
  });
  const choose = useMutation({
    mutationFn: (minutes: number) => queries.setStudyGoal(minutes),
    onSuccess: (updated) => {
      queryClient.setQueryData<StudyGoal>(["study-goal"], updated);
    },
  });

  const running = overview.data?.active?.tracking_state === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(timer);
  }, [running]);

  if (!goal.data) return null;
  const data = goal.data;

  if (data.needs_selection) {
    return (
      <div className="week-goal week-goal-choose">
        <div className="shell-width week-goal-row">
          <span className="week-goal-label">
            {readOnly ? "This week's study goal isn't set yet" : "Set this week's study goal"}
          </span>
          {readOnly ? null : (
            <div className="week-goal-presets">
              {data.presets.map((minutes) => (
                <button
                  key={minutes}
                  type="button"
                  className="week-goal-preset"
                  disabled={choose.isPending}
                  onClick={() => choose.mutate(minutes)}
                >
                  {minutes} min/day
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  const target = data.weekly_target_minutes ?? 0;
  const done = data.completed_minutes + liveMinutes(overview.data, data, now);
  const percent = target ? Math.min(100, Math.round((done / target) * 100)) : 0;
  const remaining = Math.max(0, target - done);

  return (
    <div className={percent >= 100 ? "week-goal week-goal-met" : "week-goal"}>
      <div className="shell-width week-goal-row">
        <span className="week-goal-label">
          This week
          {data.daily_target_minutes ? <em> · {data.daily_target_minutes} min/day</em> : null}
        </span>
        <div
          className="week-goal-track"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={target}
          aria-valuenow={done}
          aria-label={`Weekly study goal: ${done} of ${target} minutes`}
        >
          <div className="week-goal-fill" style={{width: `${percent}%`}} />
        </div>
        <span className="week-goal-value">
          {done} / {target} min
          <em>{remaining ? `${remaining} to go` : "goal met"}</em>
        </span>
      </div>
    </div>
  );
}
