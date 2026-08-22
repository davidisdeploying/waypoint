import type {ObjectiveDossierSummaryItem} from "./types";

export function dossierStatusLabel(status: ObjectiveDossierSummaryItem["status"]) {
  if (status === "complete") return "Source-complete";
  if (status === "thin") return "Needs depth";
  if (status === "conflicted") return "Review conflict";
  return "Missing instruction";
}

export function dossierEvidenceLabel(item: ObjectiveDossierSummaryItem) {
  return [
    `${item.primary_source_count} primary`,
    `${item.supplemental_source_count} supplemental`,
    `${item.assessment_source_count} assessment`,
  ].join(" · ");
}
