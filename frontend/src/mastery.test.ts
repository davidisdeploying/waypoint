import {describe, expect, it} from "vitest";
import {
  domainSignalLabel,
  objectiveEvidenceCoverage,
  sourceCountLabel,
  statusLabels,
} from "./mastery";
import type {DomainSignal} from "./types";

function signal(status: string): DomainSignal {
  return {
    scope_id: 1,
    scope_name: "Domain check",
    status,
    retention_due_at: null,
    latest_raw_score_pct: null,
    latest_effective_score_pct: null,
    latest_attempt_at: null,
    open_gap_count: 0,
  };
}

describe("objective mastery presentation", () => {
  it("keeps broad domain results explicitly separate", () => {
    expect(domainSignalLabel(signal("needs_remediation"))).toBe("Review needed");
    expect(domainSignalLabel(signal("provisional_mastery"))).toBe("Domain check passed");
    expect(statusLabels.not_assessed).toBe("Not individually checked");
  });

  it("computes conservative evidence coverage", () => {
    expect(objectiveEvidenceCoverage(10, 7)).toBe(30);
    expect(objectiveEvidenceCoverage(0, 0)).toBe(0);
    expect(sourceCountLabel(1)).toBe("1 cited section");
    expect(sourceCountLabel(2)).toBe("2 cited sections");
  });
});
