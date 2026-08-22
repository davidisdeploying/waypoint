import {describe, expect, it} from "vitest";
import {
  MAX_SESSION_MINUTES,
  MIN_SESSION_MINUTES,
  activeElapsedMinutes,
  elapsedMinutes,
  isTimedStudyPath,
  parseSessionMinutes,
  sessionActionPath,
} from "./sessions";
import type {DailyStudySession} from "./types";

describe("daily study-session helpers", () => {
  it("routes diagnostic and remediation actions into native flows", () => {
    expect(sessionActionPath({type: "diagnostic", scope_id: 4, mode: "retest"}))
      .toBe("/study/check/4?mode=retest");
    expect(sessionActionPath({type: "scope_detail", scope_id: 7}))
      .toBe("/study/remediate/7");
    expect(sessionActionPath({type: "objective", objective_id: 12}))
      .toBe("/learn/12");
    expect(sessionActionPath({type: "objective_retention", objective_id: 12}))
      .toBe("/study/review/12");
    expect(sessionActionPath({type: "plan_task", task_id: 2})).toBe("/study");
  });

  it("calculates elapsed whole minutes without going negative", () => {
    expect(elapsedMinutes("2026-07-30T00:00:00Z", Date.parse("2026-07-30T00:26:30Z"))).toBe(26);
    expect(elapsedMinutes("2026-07-30T01:00:00Z", Date.parse("2026-07-30T00:00:00Z"))).toBe(0);
  });

  it("adds foreground time only while the session is running", () => {
    const session = {
      active_seconds: 300,
      elapsed_seconds: 300,
      tracking_state: "running",
      resumed_at: "2026-08-09T12:00:00Z",
    } as DailyStudySession;
    expect(activeElapsedMinutes(session, Date.parse("2026-08-09T12:02:30Z"))).toBe(7);
    expect(activeElapsedMinutes({...session, tracking_state: "paused", resumed_at: null})).toBe(5);
  });

  it("times focused study routes but excludes dashboards and settings", () => {
    expect(isTimedStudyPath("/study/results/4")).toBe(true);
    expect(isTimedStudyPath("/study/check/2")).toBe(true);
    expect(isTimedStudyPath("/learn/12")).toBe(true);
    expect(isTimedStudyPath("/mastery/12")).toBe(true);
    expect(isTimedStudyPath("/practice/9")).toBe(true);
    expect(isTimedStudyPath("/labs")).toBe(true);
    expect(isTimedStudyPath("/study")).toBe(false);
    expect(isTimedStudyPath("/library")).toBe(false);
    expect(isTimedStudyPath("/journey")).toBe(false);
    expect(isTimedStudyPath("/more")).toBe(false);
  });
});

describe("parseSessionMinutes", () => {
  it("accepts whole minutes inside the range the origin allows", () => {
    expect(parseSessionMinutes("90")).toBe(90);
    expect(parseSessionMinutes(" 30 ")).toBe(30);
    expect(parseSessionMinutes(String(MIN_SESSION_MINUTES))).toBe(MIN_SESSION_MINUTES);
    expect(parseSessionMinutes(String(MAX_SESSION_MINUTES))).toBe(MAX_SESSION_MINUTES);
  });

  it("rejects anything the origin would reject, rather than sending it", () => {
    // daily_sessions.start() requires an int in [5, 240]; a picker that can
    // compose 0, 500, or 4.5 just moves the error to the server.
    expect(parseSessionMinutes("")).toBeNull();
    expect(parseSessionMinutes("   ")).toBeNull();
    expect(parseSessionMinutes("0")).toBeNull();
    expect(parseSessionMinutes(String(MIN_SESSION_MINUTES - 1))).toBeNull();
    expect(parseSessionMinutes(String(MAX_SESSION_MINUTES + 1))).toBeNull();
    expect(parseSessionMinutes("-30")).toBeNull();
    expect(parseSessionMinutes("4.5")).toBeNull();
    expect(parseSessionMinutes("45.0000001")).toBeNull();
    expect(parseSessionMinutes("abc")).toBeNull();
    expect(parseSessionMinutes("45min")).toBeNull();
    expect(parseSessionMinutes("Infinity")).toBeNull();
  });
});
