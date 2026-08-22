import {useEffect, useRef, useState} from "react";
import {useQuery, useQueryClient} from "@tanstack/react-query";
import {Link, useLocation} from "react-router-dom";
import {queries} from "./api";
import {activeElapsedMinutes, idleTimeoutMs, isTimedStudyPath} from "./sessions";
import type {DailySessionOverview, DailyStudySession} from "./types";

const AUTO_SESSION_TARGET_MINUTES = 25;
// Must stay well inside the server's grace window, so one dropped ping does
// not cost credited time.
const HEARTBEAT_INTERVAL_MS = 60 * 1000;

function markerKey(sessionId: number) {
  return `waypoint:session-paused-at:${sessionId}`;
}

function readMarker(sessionId: number) {
  try {
    return localStorage.getItem(markerKey(sessionId));
  } catch {
    return null;
  }
}

function rememberPausedAt(sessionId: number, occurredAt = new Date().toISOString()) {
  const existing = readMarker(sessionId);
  if (existing) return existing;
  try {
    localStorage.setItem(markerKey(sessionId), occurredAt);
  } catch {
    // The immediate keepalive request still handles normal private-mode use.
  }
  return occurredAt;
}

function clearMarker(sessionId: number) {
  try {
    localStorage.removeItem(markerKey(sessionId));
  } catch {
    // Storage can be unavailable in hardened browser modes.
  }
}

export function SessionPresence() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const startingRef = useRef(false);
  const transitionsRef = useRef<Promise<void>>(Promise.resolve());
  const timedStudyPath = isTimedStudyPath(location.pathname);
  const overview = useQuery({
    queryKey: ["daily-session"],
    queryFn: queries.dailySession,
    refetchOnWindowFocus: false,
    staleTime: 15_000,
  });
  const sessionId = overview.data?.active?.id;

  useEffect(() => {
    if (
      overview.isLoading ||
      sessionId ||
      !timedStudyPath ||
      document.visibilityState !== "visible" ||
      startingRef.current
    ) return;
    startingRef.current = true;
    void queries.startDailySession(AUTO_SESSION_TARGET_MINUTES)
      .then((active) => {
        queryClient.setQueryData<DailySessionOverview>(["daily-session"], (current) =>
          current ? {...current, active} : current
        );
      })
      .catch(() => queryClient.invalidateQueries({queryKey: ["daily-session"]}))
      .finally(() => {
        startingRef.current = false;
      });
  }, [overview.isLoading, queryClient, sessionId, timedStudyPath]);

  useEffect(() => {
    if (!sessionId) return;
    let disposed = false;
    let idle = false;
    let idleTimer = 0;
    let heartbeatTimer = 0;

    const updateActive = (active: DailyStudySession) => {
      if (disposed) return;
      queryClient.setQueryData<DailySessionOverview>(["daily-session"], (current) =>
        current ? {...current, active} : current
      );
    };
    const enqueue = (transition: () => Promise<void>) => {
      transitionsRef.current = transitionsRef.current.then(transition).catch(() => {
        if (!disposed) void queryClient.invalidateQueries({queryKey: ["daily-session"]});
      });
    };
    const pause = (occurredAt = new Date().toISOString()) => {
      const pausedAt = rememberPausedAt(sessionId, occurredAt);
      enqueue(async () => {
        const active = await queries.pauseDailySession(sessionId, pausedAt);
        updateActive(active);
      });
    };
    const resume = () => {
      enqueue(async () => {
        const pausedAt = readMarker(sessionId);
        if (pausedAt) await queries.pauseDailySession(sessionId, pausedAt);
        const active = await queries.resumeDailySession(sessionId);
        clearMarker(sessionId);
        updateActive(active);
      });
    };
    const clearIdleTimer = () => {
      window.clearTimeout(idleTimer);
      idleTimer = 0;
    };
    // Proof the tab is still alive. Presence is the idle timer's job; this
    // only stops a killed browser from banking time it never spent.
    const stopHeartbeat = () => {
      window.clearInterval(heartbeatTimer);
      heartbeatTimer = 0;
    };
    const startHeartbeat = () => {
      stopHeartbeat();
      heartbeatTimer = window.setInterval(() => {
        if (document.visibilityState !== "visible") return;
        void queries.heartbeatDailySession(sessionId).catch(() => undefined);
      }, HEARTBEAT_INTERVAL_MS);
    };
    const scheduleIdlePause = () => {
      clearIdleTimer();
      if (!timedStudyPath || document.visibilityState !== "visible") return;
      idleTimer = window.setTimeout(() => {
        idle = true;
        pause();
      }, idleTimeoutMs(location.pathname));
    };
    const syncPresence = () => {
      if (timedStudyPath && document.visibilityState === "visible" && !idle) {
        resume();
        scheduleIdlePause();
        startHeartbeat();
      } else {
        clearIdleTimer();
        stopHeartbeat();
        pause();
      }
    };
    const syncVisibility = () => {
      if (document.visibilityState === "hidden") {
        clearIdleTimer();
        stopHeartbeat();
        pause();
      } else {
        idle = false;
        syncPresence();
      }
    };
    const registerActivity = () => {
      if (!timedStudyPath || document.visibilityState !== "visible") return;
      if (idle) {
        idle = false;
        resume();
      }
      scheduleIdlePause();
    };
    const handlePageHide = () => pause();

    syncPresence();
    document.addEventListener("visibilitychange", syncVisibility);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pointerdown", registerActivity, {passive: true});
    window.addEventListener("keydown", registerActivity);
    window.addEventListener("scroll", registerActivity, {passive: true});
    window.addEventListener("touchstart", registerActivity, {passive: true});
    return () => {
      disposed = true;
      clearIdleTimer();
      stopHeartbeat();
      document.removeEventListener("visibilitychange", syncVisibility);
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pointerdown", registerActivity);
      window.removeEventListener("keydown", registerActivity);
      window.removeEventListener("scroll", registerActivity);
      window.removeEventListener("touchstart", registerActivity);
    };
  }, [location.pathname, queryClient, sessionId, timedStudyPath]);

  return null;
}

// Matches the cadence the session page already uses. The goal is expressed in
// minutes per day, so a per-second counter would only turn a background
// reassurance into a stopwatch worth watching instead of studying.
const CLOCK_TICK_MS = 30 * 1000;

export function SessionStatus() {
  const overview = useQuery({
    queryKey: ["daily-session"],
    queryFn: queries.dailySession,
    staleTime: 15_000,
  });
  const active = overview.data?.active;
  const running = active?.tracking_state === "running";
  const [now, setNow] = useState(Date.now());

  // Credited time only advances while the session runs, so the clock ticks on a
  // running session and holds its last value when paused. What it reports is
  // what actually lands in the ledger, not wall-clock time spent on the page.
  useEffect(() => {
    if (!running) return;
    // Resuming banks a fresh resumed_at; re-read the clock now so the first
    // rendered value is not up to one tick behind.
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), CLOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, [running]);

  if (!active) return null;
  return (
    <Link className={running ? "session-status recording" : "session-status paused"} to="/session">
      {activeElapsedMinutes(active, now)} min studied · {running ? "recording" : "paused"}
    </Link>
  );
}
