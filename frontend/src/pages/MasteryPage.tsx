import {useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {Link, useParams} from "react-router-dom";
import {queries, trackStudyEvent} from "../api";
import {ErrorNotice, Loading, Metric, Panel} from "../components";
import {DomainBrowserCard} from "../DomainBrowser";
import {domainSignalLabel, sourceCountLabel, statusLabels} from "../mastery";

export function MasteryPage() {
  const [exam, setExam] = useState("220-1201");
  const mapQuery = useQuery({
    queryKey: ["mastery-map", exam],
    queryFn: () => queries.masteryMap(exam),
  });

  if (mapQuery.isLoading) return <Loading label="Building objective mastery map" />;
  if (mapQuery.error) return <ErrorNotice error={mapQuery.error} />;
  const map = mapQuery.data!;
  const examData = map.exams[0];

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Objective mastery</span>
        <h1>Know exactly what the evidence supports</h1>
        <p>
          Explore every A+ objective. Domain checks stay visible as broad signals;
          an objective changes only when objective-linked study or practice exists.
        </p>
      </div>

      <div className="exam-switch" role="group" aria-label="A+ exam">
        <button
          className={exam === "220-1201" ? "selected" : ""}
          onClick={() => setExam("220-1201")}
        >
          Core 1 <span>220-1201</span>
        </button>
        <button
          className={exam === "220-1202" ? "selected" : ""}
          onClick={() => setExam("220-1202")}
        >
          Core 2 <span>220-1202</span>
        </button>
      </div>

      <div className="metric-grid compact mastery-metrics">
        <Metric value={map.totals.objectives} label="Objectives" />
        <Metric value={`${map.totals.evidence_coverage_pct}%`} label="Evidence coverage" />
        <Metric value={map.totals.strong_signal} label="Strong signals" accent />
        <Metric value={map.totals.needs_work} label="Needs work" />
        <Metric value={map.totals.not_assessed} label="Not assessed" />
      </div>

      <Panel eyebrow="How to read this" title="Broad scores are not copied onto objectives">
        <p>{map.evidence_note}</p>
        <p className="fine-print">{map.mapping_note}</p>
      </Panel>

      <div className="mastery-domains">
        {examData?.domains.map((domain, index) => (
          <DomainBrowserCard key={domain.id} domain={domain} mode="mastery" initiallyOpen={index === 0} />
        ))}
      </div>
    </>
  );
}

export function ObjectivePage() {
  const {objectiveId} = useParams();
  const id = Number(objectiveId);
  const [openSection, setOpenSection] = useState("");
  const objectiveQuery = useQuery({
    queryKey: ["objective", id],
    queryFn: () => queries.objective(id),
    enabled: Number.isInteger(id) && id > 0,
  });

  if (objectiveQuery.isLoading) return <Loading label="Opening objective evidence" />;
  if (objectiveQuery.error) return <ErrorNotice error={objectiveQuery.error} />;
  const objective = objectiveQuery.data!;
  const mastery = objective.mastery;

  return (
    <>
      <div className="page-title objective-title">
        <span className="eyebrow">{objective.exam_code} · Domain {objective.domain_code}</span>
        <h1>{objective.code}</h1>
        <p>{objective.description}</p>
      </div>

      <div className="two-column">
        <Panel eyebrow="Objective status" title={statusLabels[mastery.status]}>
          <dl className="status-list">
            <div><dt>Objective checks</dt><dd>{mastery.evidence.objective_assessments}</dd></div>
            <div><dt>Cited sections opened</dt><dd>{mastery.evidence.cited_sections_opened}</dd></div>
            <div><dt>Completed linked tasks</dt><dd>{mastery.evidence.completed_tasks}</dd></div>
            <div><dt>Latest objective score</dt><dd>{mastery.evidence.latest_assessment_pct ?? "Not checked"}</dd></div>
          </dl>
        </Panel>
        <Panel eyebrow="Domain signal" title={domainSignalLabel(mastery.domain_signal)}>
          <p className="large-copy">{mastery.domain.name}</p>
          <dl className="status-list">
            <div><dt>Latest domain score</dt><dd>{mastery.domain_signal.latest_raw_score_pct ?? "Not checked"}</dd></div>
            <div><dt>Open domain gaps</dt><dd>{mastery.domain_signal.open_gap_count}</dd></div>
          </dl>
          <p className="fine-print">This broad domain result is context, not an individual score for objective {objective.code}.</p>
        </Panel>
      </div>

      {mastery.domain_signal.open_gap_count > 0 && mastery.domain_signal.scope_id ? (
        <Panel
          eyebrow="Recommended"
          title="Resolve the current domain gaps"
          action={
            <Link className="button primary" to={`/study/remediate/${mastery.domain_signal.scope_id}`}>
              Start guided review
            </Link>
          }
        >
          <p>Review the questions already missed before adding broad reading.</p>
        </Panel>
      ) : null}

      <Panel eyebrow="Book evidence" title={sourceCountLabel(objective.evidence.length)}>
        {objective.evidence.length ? (
          <div className="objective-sources">
            {objective.evidence.map((source) => (
              <article key={`${source.book_slug}:${source.stable_id}`}>
                <div>
                  <span className="eyebrow">{source.book_title}</span>
                  <h3>{source.title}</h3>
                  <p>{source.snippet}</p>
                </div>
                <button
                  className="text-button"
                  onClick={() => {
                    const opening = openSection !== source.stable_id;
                    setOpenSection(opening ? source.stable_id : "");
                    if (opening) {
                      trackStudyEvent(
                        "reading_opened",
                        `${objective.exam_code} ${objective.code}: ${source.title}`,
                        `section:${source.stable_id}`,
                        {
                          section_stable_id: source.stable_id,
                          objective_id: objective.id,
                          objective_code: objective.code,
                        },
                      );
                    }
                  }}
                >
                  {openSection === source.stable_id ? "Close reading" : "Read cited section"}
                </button>
                {openSection === source.stable_id ? (
                  <div className="full-source objective-source-reader">
                    {source.focused_excerpt}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <p className="notice">No cited section is linked to this objective yet.</p>
        )}
      </Panel>

      <Link className="text-link" to="/mastery">Back to mastery map</Link>
    </>
  );
}
