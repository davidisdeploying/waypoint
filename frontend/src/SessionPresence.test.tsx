import {act, render, screen, waitFor} from "@testing-library/react";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {SessionPresence, SessionStatus} from "./SessionPresence";
import {ANSWERING_IDLE_TIMEOUT_MS, READING_IDLE_TIMEOUT_MS} from "./sessions";
import type {DailyStudySession} from "./types";

const apiMocks = vi.hoisted(() => ({
  dailySession: vi.fn(),
  startDailySession: vi.fn(),
  pauseDailySession: vi.fn(),
  resumeDailySession: vi.fn(),
  heartbeatDailySession: vi.fn(() => Promise.resolve()),
}));

vi.mock("./api", () => ({queries: apiMocks}));

const running = {
  id: 7,
  status: "active",
  started_at: "2026-08-09T12:00:00Z",
  ended_at: null,
  target_minutes: 25,
  duration_minutes: null,
  elapsed_minutes: 5,
  elapsed_seconds: 300,
  active_seconds: 300,
  tracking_state: "running",
  resumed_at: "2026-08-09T12:05:00Z",
  exam_id: null,
  week_id: null,
  task_kind: null,
  task_title: "Review",
  task_action: null,
  notes: null,
  recap: null,
  events: [],
} satisfies DailyStudySession;

beforeEach(() => {
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    },
  });
});

afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  Object.defineProperty(document, "visibilityState", {configurable: true, value: "visible"});
});

describe("SessionPresence", () => {
  function renderPresence(initialEntry = "/study/results/1") {
    const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}}});
    render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <QueryClientProvider client={queryClient}>
          <SessionPresence />
        </QueryClientProvider>
      </MemoryRouter>,
    );
    return queryClient;
  }

  it("pauses on background and reconciles that timestamp before resuming", async () => {
    Object.defineProperty(document, "visibilityState", {configurable: true, value: "visible"});
    apiMocks.dailySession.mockResolvedValue({
      active: running,
      suggested: null,
      today: {minutes: 0, sessions: 0},
      recent: [],
    });
    apiMocks.pauseDailySession.mockResolvedValue({...running, tracking_state: "paused", resumed_at: null});
    apiMocks.resumeDailySession.mockResolvedValue(running);
    renderPresence();
    await waitFor(() => expect(apiMocks.resumeDailySession).toHaveBeenCalledWith(7));
    apiMocks.pauseDailySession.mockClear();

    Object.defineProperty(document, "visibilityState", {configurable: true, value: "hidden"});
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(apiMocks.pauseDailySession).toHaveBeenCalledTimes(1));
    const hiddenAt = apiMocks.pauseDailySession.mock.calls[0][1];
    expect(Date.parse(hiddenAt)).not.toBeNaN();

    Object.defineProperty(document, "visibilityState", {configurable: true, value: "visible"});
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(apiMocks.pauseDailySession).toHaveBeenCalledWith(7, hiddenAt));
    await waitFor(() => expect(apiMocks.resumeDailySession).toHaveBeenCalledTimes(2));
    expect(localStorage.getItem("waypoint:session-paused-at:7")).toBeNull();
  });

  it("starts a session automatically when a focused study route opens", async () => {
    apiMocks.dailySession.mockResolvedValue({
      active: null,
      suggested: null,
      today: {minutes: 0, sessions: 0},
      recent: [],
    });
    apiMocks.startDailySession.mockResolvedValue(running);
    renderPresence("/learn/12");
    await waitFor(() => expect(apiMocks.startDailySession).toHaveBeenCalledWith(25));
  });

  it("pauses an active session on a non-study route", async () => {
    apiMocks.dailySession.mockResolvedValue({
      active: running,
      suggested: null,
      today: {minutes: 0, sessions: 0},
      recent: [],
    });
    apiMocks.pauseDailySession.mockResolvedValue({...running, tracking_state: "paused", resumed_at: null});
    apiMocks.resumeDailySession.mockResolvedValue(running);
    renderPresence("/more");
    await waitFor(() => expect(apiMocks.pauseDailySession).toHaveBeenCalledWith(7, expect.any(String)));
    expect(apiMocks.resumeDailySession).not.toHaveBeenCalled();
  });

  it("pauses a visible study screen after five minutes without activity", async () => {
    vi.useFakeTimers();
    apiMocks.dailySession.mockResolvedValue({
      active: running,
      suggested: null,
      today: {minutes: 0, sessions: 0},
      recent: [],
    });
    apiMocks.pauseDailySession.mockResolvedValue({...running, tracking_state: "paused", resumed_at: null});
    apiMocks.resumeDailySession.mockResolvedValue(running);
    renderPresence("/study/results/1");
    await act(async () => {
      await vi.waitFor(() => expect(apiMocks.resumeDailySession).toHaveBeenCalledWith(7));
    });
    apiMocks.pauseDailySession.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ANSWERING_IDLE_TIMEOUT_MS);
    });
    expect(apiMocks.pauseDailySession).toHaveBeenCalledWith(7, expect.any(String));
  });

  it("gives a reading screen longer than five minutes before pausing", async () => {
    vi.useFakeTimers();
    apiMocks.dailySession.mockResolvedValue({
      active: running,
      suggested: null,
      today: {minutes: 0, sessions: 0},
      recent: [],
    });
    apiMocks.pauseDailySession.mockResolvedValue({...running, tracking_state: "paused", resumed_at: null});
    apiMocks.resumeDailySession.mockResolvedValue(running);
    renderPresence("/learn/1");
    await act(async () => {
      await vi.waitFor(() => expect(apiMocks.resumeDailySession).toHaveBeenCalledWith(7));
    });
    apiMocks.pauseDailySession.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ANSWERING_IDLE_TIMEOUT_MS);
    });
    expect(apiMocks.pauseDailySession).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(READING_IDLE_TIMEOUT_MS - ANSWERING_IDLE_TIMEOUT_MS);
    });
    expect(apiMocks.pauseDailySession).toHaveBeenCalledWith(7, expect.any(String));
  });

  it("keeps proving the client is alive while a study screen is open", async () => {
    vi.useFakeTimers();
    apiMocks.dailySession.mockResolvedValue({
      active: running,
      suggested: null,
      today: {minutes: 0, sessions: 0},
      recent: [],
    });
    apiMocks.pauseDailySession.mockResolvedValue({...running, tracking_state: "paused", resumed_at: null});
    apiMocks.resumeDailySession.mockResolvedValue(running);
    renderPresence("/learn/1");
    await act(async () => {
      await vi.waitFor(() => expect(apiMocks.resumeDailySession).toHaveBeenCalledWith(7));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3 * 60 * 1000);
    });
    expect(apiMocks.heartbeatDailySession).toHaveBeenCalledWith(7);
  });
});


describe("SessionStatus", () => {
  function renderStatus() {
    const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}}});
    return render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <SessionStatus />
        </QueryClientProvider>
      </MemoryRouter>,
    );
  }

  function overview(active: DailyStudySession | null) {
    return {active, suggested: null, today: {minutes: 0, sessions: 0}, recent: []};
  }

  it("reports the minutes credited so far while recording", async () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-08-09T12:08:00Z"));
    apiMocks.dailySession.mockResolvedValue(overview(running));
    const {findByRole} = renderStatus();
    // 300s already banked, plus the 180s running since resumed_at.
    expect((await findByRole("link")).textContent).toBe("8 min studied · recording");
  });

  it("counts credited time only, never wall clock, while paused", async () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-08-09T14:00:00Z"));
    apiMocks.dailySession.mockResolvedValue(
      overview({...running, tracking_state: "paused", resumed_at: null}),
    );
    const {findByRole} = renderStatus();
    // Two hours of wall clock later it still reports only the banked 300s, so
    // the strip can never claim more time than the ledger credits.
    expect((await findByRole("link")).textContent).toBe("5 min studied · paused");
  });

  it("advances a running clock on its own, without refetching the session", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-09T12:08:00Z"));
    apiMocks.dailySession.mockResolvedValue(overview(running));
    renderStatus();
    await act(async () => {
      await vi.waitFor(() =>
        expect(screen.getByRole("link").textContent).toBe("8 min studied · recording"));
    });
    apiMocks.dailySession.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2 * 60 * 1000);
    });
    expect(screen.getByRole("link").textContent).toBe("10 min studied · recording");
    expect(apiMocks.dailySession).not.toHaveBeenCalled();
  });

  it("stays out of the way when no session is active", async () => {
    apiMocks.dailySession.mockResolvedValue(overview(null));
    const {queryByRole} = renderStatus();
    await waitFor(() => expect(apiMocks.dailySession).toHaveBeenCalled());
    expect(queryByRole("link")).toBeNull();
  });
});
