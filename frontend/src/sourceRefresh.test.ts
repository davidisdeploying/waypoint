import {describe, expect, it} from "vitest";
import {sourceRefreshMessage} from "./sourceRefresh";
import type {CertificationPackSource} from "./types";

const source = {
  source_key: "official",
  title: "Official",
  publisher: "Vendor",
  source_type: "official_objectives",
  authority_tier: 1,
  version_label: "current",
  exam_codes: ["EX-1"],
  source_url: "https://vendor.test/objectives.pdf",
  source_sha256: "a".repeat(64),
  status: "active",
  status_reason: "Pinned.",
  verified_at: null,
  disposition: "active",
  use_role: "authoritative_scope",
  required: true,
} satisfies CertificationPackSource;

describe("source refresh status", () => {
  it("explains matching and drift without implying automatic replacement", () => {
    expect(sourceRefreshMessage({...source, refresh_status: "match"}))
      .toContain("matches the pinned");
    expect(sourceRefreshMessage({...source, refresh_status: "drift"}))
      .toContain("review required");
  });

  it("does not describe local books as remotely checked", () => {
    expect(sourceRefreshMessage({...source, source_url: null})).toBeNull();
  });
});
