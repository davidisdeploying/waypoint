import type {DailyStudySession, StudyAction} from "./types";

const timedStudyRoutes = [
  /^\/study\/check\/\d+$/,
  /^\/study\/remediate\/\d+$/,
  /^\/study\/results\/\d+$/,
  /^\/study\/review\/\d+$/,
  /^\/learn\/\d+$/,
  /^\/mastery\/\d+$/,
  /^\/practice\/\d+$/,
  /^\/labs(?:\/|$)/,
];

export function isTimedStudyPath(pathname: string) {
  return timedStudyRoutes.some((pattern) => pattern.test(pathname));
}

// Reading legitimately involves long still stretches -- a dense page can hold
// attention for minutes without a scroll -- while an unanswered question does
// not. Pausing both at five minutes undercounted real reading time.
const readingRoutes = [
  /^\/learn\/\d+$/,
  /^\/mastery\/\d+$/,
  /^\/study\/remediate\/\d+$/,
  /^\/study\/review\/\d+$/,
  /^\/labs(?:\/|$)/,
];

export const READING_IDLE_TIMEOUT_MS = 10 * 60 * 1000;
export const ANSWERING_IDLE_TIMEOUT_MS = 5 * 60 * 1000;

export function idleTimeoutMs(pathname: string) {
  return readingRoutes.some((pattern) => pattern.test(pathname))
    ? READING_IDLE_TIMEOUT_MS
    : ANSWERING_IDLE_TIMEOUT_MS;
}

// daily_sessions.start() rejects anything that is not a whole number of
// minutes from 5 to 240, so the picker enforces the same rule rather than
// letting the origin be the one to say no.
export const SESSION_PRESET_MINUTES = [25, 45, 60];
export const MIN_SESSION_MINUTES = 5;
export const MAX_SESSION_MINUTES = 240;

/** A usable session length, or null if this text is not one yet. */
export function parseSessionMinutes(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  // Number, not parseInt: "45min" and "4.5" should be rejected outright rather
  // than silently becoming 45 and 4.
  const minutes = Number(trimmed);
  if (!Number.isInteger(minutes)) return null;
  if (minutes < MIN_SESSION_MINUTES || minutes > MAX_SESSION_MINUTES) return null;
  return minutes;
}


export function sessionActionPath(action: StudyAction | null | undefined) {
  if (action?.type === "diagnostic" && action.scope_id) {
    const mode = action.mode ?? "diagnostic";
    return `/study/check/${action.scope_id}?mode=${encodeURIComponent(mode)}`;
  }
  if (action?.scope_id && (action.type === "remediation" || action.type === "scope_detail")) {
    return `/study/remediate/${action.scope_id}`;
  }
  if (action?.type === "objective_retention" && action.objective_id) {
    return `/study/review/${action.objective_id}`;
  }
  if (action?.type === "objective" && action.objective_id) {
    return `/learn/${action.objective_id}`;
  }
  if (action?.type === "task") {
    return "/study";
  }
  return "/study";
}

export function elapsedMinutes(startedAt: string, now = Date.now()) {
  const started = Date.parse(startedAt);
  if (!Number.isFinite(started)) return 0;
  return Math.max(0, Math.floor((now - started) / 60_000));
}

export function activeElapsedMinutes(session: DailyStudySession, now = Date.now()) {
  let seconds = Math.max(0, session.active_seconds ?? session.elapsed_seconds ?? 0);
  if (session.tracking_state === "running" && session.resumed_at) {
    const resumed = Date.parse(session.resumed_at);
    if (Number.isFinite(resumed)) seconds += Math.max(0, (now - resumed) / 1000);
  }
  return Math.floor(seconds / 60);
}
