import type {DomainSignal, ObjectiveStatus} from "./types";

export const statusLabels: Record<ObjectiveStatus, string> = {
  not_assessed: "Not individually checked",
  studied: "Studied",
  practiced: "Practiced",
  strong_signal: "Strong signal",
  needs_work: "Needs work",
};

export function domainSignalLabel(signal: DomainSignal) {
  if (signal.status === "needs_remediation") return "Review needed";
  if (signal.status === "mastered_after_remediation") return "Retest passed";
  if (signal.status === "provisional_mastery") return "Domain check passed";
  return "Domain not checked";
}

export function objectiveEvidenceCoverage(total: number, notAssessed: number) {
  if (!total) return 0;
  return ((total - notAssessed) / total) * 100;
}

export function sourceCountLabel(count: number) {
  return `${count} cited ${count === 1 ? "section" : "sections"}`;
}
