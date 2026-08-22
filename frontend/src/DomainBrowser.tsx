import {Link} from "react-router-dom";
import {ProgressBar} from "./components";
import {domainSignalLabel, objectiveEvidenceCoverage, statusLabels} from "./mastery";
import type {MasteryDomain, MasteryObjective} from "./types";

// Mastery and Learn browse the same objectives with the same accordion shape --
// evidence-framed (mastery) vs action-framed (learn) -- so the structure lives
// here once and each page supplies only the framing that actually differs.
export type DomainBrowserMode = "mastery" | "learn";

function domainProgress(domain: MasteryDomain, mode: DomainBrowserMode) {
  if (mode === "learn") {
    const completed = domain.objectives.filter((o) => o.evidence.lessons_completed > 0).length;
    const started = domain.objectives.filter((o) =>
      o.evidence.cited_sections_opened + o.evidence.lessons_completed + o.evidence.recall_completed > 0
    ).length;
    return {
      covered: completed,
      label: "Lessons completed",
      summaryLine: `${started} started · ${completed} lessons completed`,
      coverage: objectiveEvidenceCoverage(domain.summary.total, domain.summary.total - completed),
    };
  }
  const covered = domain.summary.total - domain.summary.not_assessed;
  return {
    covered,
    label: "Objectives with evidence",
    summaryLine: domain.signal.latest_raw_score_pct != null
      ? `${domain.signal.latest_raw_score_pct}% domain check · ${domain.signal.open_gap_count} open gaps`
      : "No domain knowledge check yet",
    coverage: objectiveEvidenceCoverage(domain.summary.total, domain.summary.not_assessed),
  };
}

function ObjectiveRow({objective, mode}: {objective: MasteryObjective; mode: DomainBrowserMode}) {
  if (mode === "mastery") {
    return (
      <li>
        <Link to={`/learn/${objective.id}`}>
          <span className="objective-code">{objective.code}</span>
          <span className="objective-copy">
            <strong>{objective.description}</strong>
            <small>
              {objective.evidence.source_sections_available} cited source
              {objective.evidence.source_sections_available === 1 ? "" : "s"}
              {objective.evidence.cited_sections_opened
                ? ` · ${objective.evidence.cited_sections_opened} opened`
                : ""}
            </small>
          </span>
          <span className={`objective-status ${objective.status}`}>
            {statusLabels[objective.status]}
          </span>
        </Link>
      </li>
    );
  }
  const lessonComplete = objective.evidence.lessons_completed > 0;
  const hasStarted = (
    objective.evidence.cited_sections_opened
    + objective.evidence.lessons_completed
    + objective.evidence.recall_completed
  ) > 0;
  return (
    <li>
      <Link to={`/learn/${objective.id}`}>
        <span className="objective-code">{objective.code}</span>
        <span className="objective-copy">
          <strong>{objective.description}</strong>
          <small>
            {lessonComplete
              ? "Lesson completed"
              : hasStarted
                ? "Continue lesson"
                : `${objective.evidence.source_sections_available} approved reading source${objective.evidence.source_sections_available === 1 ? "" : "s"}`}
          </small>
        </span>
        <span className={`lesson-state ${lessonComplete ? "complete" : hasStarted ? "started" : ""}`}>
          {lessonComplete ? "Complete" : hasStarted ? "Continue" : "Learn"}
        </span>
      </Link>
    </li>
  );
}

export function DomainBrowserCard({domain, mode, initiallyOpen}: {
  domain: MasteryDomain;
  mode: DomainBrowserMode;
  initiallyOpen: boolean;
}) {
  const progress = domainProgress(domain, mode);
  return (
    <details className={mode === "learn" ? "learning-domain" : "mastery-domain"} open={initiallyOpen}>
      <summary>
        <div>
          <span className="eyebrow">Domain {domain.code}</span>
          <h2>{domain.name}</h2>
          <p>{progress.summaryLine}</p>
        </div>
        <div className="domain-summary">
          <strong>{progress.covered} / {domain.summary.total}</strong>
          <span>{progress.label}</span>
          <span className={`mastery ${domain.signal.status}`}>
            {domainSignalLabel(domain.signal)}
          </span>
        </div>
      </summary>
      <ProgressBar value={progress.coverage} />
      {mode === "learn" ? (
        <div className="learning-domain-actions">
          {domain.signal.open_gap_count > 0 && domain.signal.scope_id ? (
            <Link className="button primary" to={`/study/remediate/${domain.signal.scope_id}`}>
              Review {domain.signal.open_gap_count} gaps
            </Link>
          ) : null}
          {domain.signal.scope_id ? (
            <Link className="button secondary" to={`/study/check/${domain.signal.scope_id}?mode=diagnostic`}>
              Domain knowledge check
            </Link>
          ) : null}
        </div>
      ) : domain.signal.open_gap_count > 0 && domain.signal.scope_id ? (
        <div className="domain-action">
          <p>The domain check found focused gaps. Review those before treating this domain as understood.</p>
          <Link className="button primary" to={`/study/remediate/${domain.signal.scope_id}`}>
            Review {domain.signal.open_gap_count} gaps
          </Link>
        </div>
      ) : null}
      <ol className={mode === "learn" ? "learning-objectives" : "objective-list"}>
        {domain.objectives.map((objective) => (
          <ObjectiveRow key={objective.id} objective={objective} mode={mode} />
        ))}
      </ol>
    </details>
  );
}
