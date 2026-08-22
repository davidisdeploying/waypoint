import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {MemoryRouter, Route, Routes} from "react-router-dom";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {ApiError} from "./api";
import {DiagnosticPage} from "./pages/DiagnosticPage";
import type {DiagnosticAttempt} from "./types";

const apiMocks = vi.hoisted(() => ({
  diagnosticScope: vi.fn(),
  diagnosticAttempt: vi.fn(),
  startDiagnostic: vi.fn(),
  submitDiagnostic: vi.fn(),
  abandonDiagnostic: vi.fn(),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {ApiError: actual.ApiError, queries: apiMocks, trackStudyEvent: vi.fn()};
});

const attempt = {
  id: 12,
  scope_id: 1,
  mode: "diagnostic",
  state: "in_progress",
  responses: [
    {
      id: 1,
      question_id: 900,
      position: 0,
      prompt_snapshot: "Which accessory avoids replugging every device?",
      options: ["KVM switch", "Docking station"],
      figure: null,
    },
  ],
} as unknown as DiagnosticAttempt;

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
  apiMocks.diagnosticScope.mockResolvedValue({recent_attempts: [{id: 12, state: "in_progress"}]});
  apiMocks.diagnosticAttempt.mockResolvedValue(attempt);
});

afterEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

function renderCheck() {
  const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return render(
    <MemoryRouter initialEntries={["/study/check/1"]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/study/check/:scopeId" element={<DiagnosticPage />} />
          <Route path="/study/results/:id" element={<h1>Results page</h1>} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

async function answerAndSubmit() {
  fireEvent.click(await screen.findByRole("radio", {name: /Docking station/i}));
  fireEvent.click(screen.getByRole("button", {name: /^high$/i}));
  fireEvent.click(screen.getByRole("button", {name: /submit check/i}));
}

describe("DiagnosticPage submission", () => {
  it("goes to the results when the attempt was already submitted", async () => {
    // Scoring happens before the response is written, so a submit whose reply
    // was lost (proxy timeout, dropped connection) has still been recorded.
    // Retrying must land on the results, not strand the user on an error in
    // front of work that already succeeded.
    apiMocks.submitDiagnostic.mockRejectedValue(
      new ApiError(409, "attempt has already been submitted (one submission only)"),
    );
    renderCheck();
    await answerAndSubmit();
    await waitFor(() => expect(screen.getByText("Results page")).toBeTruthy());
    expect(localStorage.getItem("waypoint-diagnostic-draft-12")).toBeNull();
  });

  it("still surfaces other submission failures instead of navigating away", async () => {
    apiMocks.submitDiagnostic.mockRejectedValue(
      new ApiError(502, "Study Library is temporarily unavailable"),
    );
    renderCheck();
    await answerAndSubmit();
    await waitFor(() => expect(screen.getByText(/temporarily unavailable/i)).toBeTruthy());
    expect(screen.queryByText("Results page")).toBeNull();
  });
});
