import {describe, expect, it} from "vitest";
import {expectedSelections, serializeDiagnostic} from "./diagnostics";
import type {DiagnosticAttempt} from "./types";

const attempt: DiagnosticAttempt = {
  id: 7,
  scope_id: 1,
  mode: "diagnostic",
  state: "in_progress",
  started_at: "2026-07-30T00:00:00Z",
  submitted_at: null,
  raw_score_pct: null,
  effective_score_pct: null,
  passed: null,
  bucket_result: null,
  selection_disclosure: "",
  answers_redacted: true,
  responses: [
    {
      id: 1,
      question_id: 10,
      position: 0,
      prompt_snapshot: "Choose one.",
      options: ["A", "B"],
      submitted_answer: null,
      confidence: null,
      is_correct: null,
      effective_score: null,
    },
    {
      id: 2,
      question_id: 11,
      position: 1,
      prompt_snapshot: "Pick the settings. (Choose two.)",
      options: ["A", "B", "C", "D"],
      submitted_answer: null,
      confidence: null,
      is_correct: null,
      effective_score: null,
    },
  ],
};

describe("diagnostic runner helpers", () => {
  it("detects single and multiple selection counts", () => {
    expect(expectedSelections("Question")).toBe(1);
    expect(expectedSelections("Question (Choose two.)")).toBe(2);
    expect(expectedSelections("Question (Choose three)")).toBe(3);
  });

  it("serializes every answer without exposing answer keys", () => {
    expect(serializeDiagnostic(attempt, {
      10: {selected: [1], confidence: "medium"},
      11: {selected: [2, 0], confidence: "high"},
    })).toEqual([
      {question_id: 10, selected: [1], confidence: "medium"},
      {question_id: 11, selected: [0, 2], confidence: "high"},
    ]);
  });

  it("refuses incomplete submissions", () => {
    expect(() => serializeDiagnostic(attempt, {
      10: {selected: [1], confidence: "high"},
      11: {selected: [0], confidence: "high"},
    })).toThrow(/Every question/);
  });
});
