import {render, screen} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {describe, expect, it} from "vitest";
import {JourneyContent} from "./JourneyContent";
import type {TimelineResponse, WaypointStateEnvelope} from "./types";

const envelope = {
  schema_version: 1,
  revision: 1,
  updated_at: "2026-08-14T00:00:00Z",
  migration_id: null,
  state: {
    meta: {name: "David", startDate: "2026-08-10", wguStartDate: "2027-08-01"},
    certs: [{
      id: "aplus", order: 1, name: "A+", kind: "CompTIA", code: "220-1201 / 220-1202",
      clears: "D316 + D317", exam: "", pass: "", status: "studying", price: 548, cu: 8,
      wlo: 5, whi: 6, started: "2026-08-10", actualHours: 1, estHoursLow: 140, estHoursHigh: 200,
    }],
    courses: [{code: "D197", name: "Version Control", note: "", cu: 1, status: "todo"}],
    log: [], studyEndpoint: "", studySummary: null, studySummaryReceivedAt: null,
  },
} satisfies WaypointStateEnvelope;

const timeline = {
  entries: [{
    ...envelope.state.certs[0], started: "2026-08-10", finished: null,
    projectedStart: "2026-08-10", projectedFinish: "2026-11-14", weeks: [],
    spine: {registry_version: "2026-08-14.1", scope_status: "published_pack", exam_sittings: 2, official_source_status: "hash_verified"},
  }],
  pace_hours_per_week: 12.83,
  target_date: "2027-08-01",
  projected_all_complete: "2027-08-09",
  schedule_delta_days: 8,
  required_pace_hours_per_week: 13.11,
  completion_buffer_days: 28,
  buffer_target_date: "2027-07-04",
  buffer_schedule_delta_days: 36,
  required_buffer_pace_hours_per_week: 14.2,
  registry: {version: "2026-08-14.1", sha256: "a".repeat(64)},
} satisfies TimelineResponse;

describe("JourneyContent parity surface", () => {
  it("renders every field shared by the private and public Journey pages", () => {
    render(
      <MemoryRouter>
        <JourneyContent envelope={envelope} timeline={timeline} renderStatus={() => <span>Studying</span>} />
      </MemoryRouter>,
    );
    expect(screen.getByText((_, element) =>
      element?.tagName === "P" && element.textContent === "Planned WGU start: Aug 1, 2027."
    )).toBeInTheDocument();
    expect(screen.getByText(/8 days after target/)).toBeInTheDocument();
    expect(screen.getByText(/Aim for about 14.2 hours\/week/)).toBeInTheDocument();
    expect(screen.getByText("A+")).toBeInTheDocument();
    expect(screen.getByText("Version Control")).toBeInTheDocument();
    expect(screen.getByText("Not started")).toBeInTheDocument();
  });
});
