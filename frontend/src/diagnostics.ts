import type {
  Confidence,
  DiagnosticAttempt,
  DiagnosticSubmissionEntry,
} from "./types";

export interface DraftAnswer {
  selected: number[];
  confidence: Confidence | null;
}

export function expectedSelections(prompt: string) {
  const match = /\(Choose (two|three|four)\.?\)/i.exec(prompt);
  if (!match) return 1;
  return {two: 2, three: 3, four: 4}[match[1].toLowerCase()] ?? 1;
}

export function serializeDiagnostic(
  attempt: DiagnosticAttempt,
  answers: Record<number, DraftAnswer>,
): DiagnosticSubmissionEntry[] {
  return attempt.responses.map((response) => {
    const answer = answers[response.question_id];
    if (!answer?.confidence || answer.selected.length !== expectedSelections(response.prompt_snapshot)) {
      throw new Error("Every question needs an answer and confidence level.");
    }
    return {
      question_id: response.question_id,
      selected: [...answer.selected].sort((a, b) => a - b),
      confidence: answer.confidence,
    };
  });
}

export function draftStorageKey(attemptId: number) {
  return `waypoint-diagnostic-draft-${attemptId}`;
}

export function readDraft(attemptId: number): Record<number, DraftAnswer> {
  try {
    const raw = localStorage.getItem(draftStorageKey(attemptId));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function writeDraft(attemptId: number, answers: Record<number, DraftAnswer>) {
  localStorage.setItem(draftStorageKey(attemptId), JSON.stringify(answers));
}

export function clearDraft(attemptId: number) {
  localStorage.removeItem(draftStorageKey(attemptId));
}
