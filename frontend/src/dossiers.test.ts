import {describe, expect, it} from "vitest";
import {dossierEvidenceLabel, dossierStatusLabel} from "./dossiers";
import type {ObjectiveDossierSummaryItem} from "./types";

const item = {
  objective_id: 1,
  status: "complete",
  quality_score: 100,
  primary_source_count: 1,
  supplemental_source_count: 1,
  assessment_source_count: 1,
  direct_question_count: 0,
  domain_question_count: 42,
  code: "1.1",
  description: "Example",
  exam_code: "220-1201",
  domain_code: "1",
  domain_name: "Mobile Devices",
} satisfies ObjectiveDossierSummaryItem;

describe("objective dossier labels", () => {
  it("describes source roles without claiming measured mastery", () => {
    expect(dossierStatusLabel(item.status)).toBe("Source-complete");
    expect(dossierEvidenceLabel(item)).toBe(
      "1 primary · 1 supplemental · 1 assessment",
    );
  });

  it("makes review states actionable", () => {
    expect(dossierStatusLabel("thin")).toBe("Needs depth");
    expect(dossierStatusLabel("conflicted")).toBe("Review conflict");
    expect(dossierStatusLabel("missing")).toBe("Missing instruction");
  });
});
