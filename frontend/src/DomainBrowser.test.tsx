import {render, screen} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {describe, expect, it} from "vitest";
import {DomainBrowserCard} from "./DomainBrowser";
import type {MasteryDomain} from "./types";

function domain(overrides: Partial<MasteryDomain> = {}): MasteryDomain {
  return {
    id: 1,
    code: "1.0",
    name: "Mobile Devices",
    signal: {
      scope_id: 9,
      scope_name: "Domain 1.0",
      status: "needs_remediation",
      retention_due_at: null,
      latest_raw_score_pct: 62,
      latest_effective_score_pct: 60,
      latest_attempt_at: "2026-08-01T00:00:00Z",
      open_gap_count: 2,
    },
    summary: {not_assessed: 1, studied: 1, practiced: 0, strong_signal: 0, needs_work: 0, total: 2},
    objectives: [
      {
        id: 101,
        code: "1.1",
        description: "Install and configure laptop hardware",
        status: "strong_signal",
        status_rank: 1,
        mastery_score: 90,
        evidence: {
          objective_assessments: 1,
          latest_assessment_pct: 90,
          average_assessment_pct: 90,
          latest_assessment_at: "2026-08-01T00:00:00Z",
          completed_tasks: 1,
          cited_sections_opened: 2,
          lessons_completed: 1,
          recall_completed: 1,
          source_sections_available: 3,
        },
      },
      {
        id: 102,
        code: "1.2",
        description: "Compare and contrast display types",
        status: "not_assessed",
        status_rank: 0,
        mastery_score: null,
        evidence: {
          objective_assessments: 0,
          latest_assessment_pct: null,
          average_assessment_pct: null,
          latest_assessment_at: null,
          completed_tasks: 0,
          cited_sections_opened: 0,
          lessons_completed: 0,
          recall_completed: 0,
          source_sections_available: 4,
        },
      },
    ],
    ...overrides,
  };
}

describe("DomainBrowserCard", () => {
  it("mastery mode shows evidence coverage, objective status pills, and routes into the lesson", () => {
    render(
      <MemoryRouter>
        <DomainBrowserCard domain={domain()} mode="mastery" initiallyOpen />
      </MemoryRouter>,
    );
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.getByText("Objectives with evidence")).toBeInTheDocument();
    expect(screen.getByText("Strong signal")).toBeInTheDocument();
    expect(screen.getByText("Not individually checked")).toBeInTheDocument();
    expect(screen.getByRole("link", {name: /1\.1/})).toHaveAttribute("href", "/learn/101");
    expect(screen.getByText(/Review 2 gaps/)).toBeInTheDocument();
    expect(screen.queryByText("Domain knowledge check")).not.toBeInTheDocument();
  });

  it("learn mode shows lesson-progress coverage, lesson-state badges, and a domain-check link", () => {
    render(
      <MemoryRouter>
        <DomainBrowserCard domain={domain()} mode="learn" initiallyOpen />
      </MemoryRouter>,
    );
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.getByText("Lessons completed")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("Learn")).toBeInTheDocument();
    expect(screen.getByRole("link", {name: /1\.1/})).toHaveAttribute("href", "/learn/101");
    expect(screen.getByText(/Review 2 gaps/)).toBeInTheDocument();
    expect(screen.getByText("Domain knowledge check")).toBeInTheDocument();
  });

  it("omits the gap-review action for either mode when there are no open gaps", () => {
    const clean = domain({signal: {...domain().signal, open_gap_count: 0}});
    render(
      <MemoryRouter>
        <DomainBrowserCard domain={clean} mode="mastery" initiallyOpen />
      </MemoryRouter>,
    );
    expect(screen.queryByText(/Review \d+ gaps/)).not.toBeInTheDocument();
  });
});
