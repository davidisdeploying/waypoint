import {useQuery} from "@tanstack/react-query";
import {Link} from "react-router-dom";
import {queries} from "../api";
import {ErrorNotice, Loading, Metric, Panel, formatDate} from "../components";
import type {Analytics, AnalyticsScoreRow} from "../types";

type TimelineKey =
  | "study_minutes"
  | "learning_events"
  | "assessments"
  | "retention_reviews"
  | "annotations"
  | "lab_completions";

const trends: Array<{key: TimelineKey; label: string}> = [
  {key: "study_minutes", label: "Study minutes"},
  {key: "learning_events", label: "Learning activity"},
  {key: "assessments", label: "Assessments"},
  {key: "retention_reviews", label: "Memory reviews"},
  {key: "annotations", label: "Notes & highlights"},
  {key: "lab_completions", label: "Labs completed"},
];

function value(value: number | null, suffix = "") {
  return value === null ? "No evidence" : `${value}${suffix}`;
}

function TrendRow({analytics, metric, label}: {
  analytics: Analytics;
  metric: TimelineKey;
  label: string;
}) {
  const maximum = Math.max(...analytics.timeline.map((day) => day[metric]), 1);
  const total = analytics.timeline.reduce((sum, day) => sum + day[metric], 0);
  return (
    <div className="trend-row">
      <div className="trend-label">
        <strong>{label}</strong>
        <span>{total} in {analytics.window_days} days</span>
      </div>
      <div className="trend-bars" aria-label={`${label}: ${total} in ${analytics.window_days} days`}>
        {analytics.timeline.map((day) => (
          <span
            key={day.date}
            className={day[metric] ? "has-value" : ""}
            style={{height: `${Math.max(day[metric] ? 12 : 3, day[metric] / maximum * 100)}%`}}
            title={`${formatDate(day.date)}: ${day[metric]}`}
          />
        ))}
      </div>
    </div>
  );
}

function AttemptList({title, rows}: {title: string; rows: AnalyticsScoreRow[]}) {
  return (
    <div className="analytics-attempts">
      <h3>{title}</h3>
      {rows.length ? (
        <ol>
          {rows.map((row) => (
            <li key={row.id}>
              <span>
                <strong>{row.scope_name ?? row.exam_code}</strong>
                <small>{formatDate(row.occurred_at)}</small>
              </span>
              <b>{row.score_pct}%</b>
            </li>
          ))}
        </ol>
      ) : <p className="empty-evidence">No submitted attempts yet.</p>}
    </div>
  );
}

export function AnalyticsPage() {
  const analyticsQuery = useQuery({
    queryKey: ["analytics", 30],
    queryFn: queries.analytics,
  });
  if (analyticsQuery.isLoading) return <Loading label="Reading your learning evidence" />;
  if (analyticsQuery.error) return <ErrorNotice error={analyticsQuery.error} />;
  const data = analyticsQuery.data!;
  const recentScope = data.assessment.diagnostic.recent[0]?.scope_name;
  const sameScopeTrend = data.assessment.diagnostic.recent
    .filter((row) => row.scope_name === recentScope)
    .slice(0, 3)
    .reverse();
  const trendDelta = sameScopeTrend.length > 1
    ? sameScopeTrend[sameScopeTrend.length - 1].score_pct - sameScopeTrend[0].score_pct
    : null;

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Analytics</span>
        <h1>Your evidence, kept honest</h1>
        <p>
          See how you are studying, practicing, remembering, and building skills.
          Each signal stays separate so activity never masquerades as mastery.
        </p>
      </div>

      <section className="hero-action analytics-next">
        <div>
          <span className="eyebrow">Recommended next</span>
          <h2>{data.next_action.title}</h2>
          <p>{data.next_action.reason}</p>
        </div>
        <Link className="button primary" to={data.next_action.href}>Do this next</Link>
      </section>

      <div className="metric-grid analytics-summary">
        <Metric value={data.current_state.open_gaps} label="Open gaps" accent />
        <Metric value={data.current_state.retention_due} label="Reviews due" />
        <Metric value={data.current_state.lessons_completed} label="Lessons completed" />
        <Metric value={data.current_state.labs_completed} label="Labs completed" />
        <Metric value={data.current_state.full_exam_attempts} label="Full exams" />
      </div>

      <Panel eyebrow="30-day activity" title="Six signals, never one blended score">
        <div className="trend-list">
          {trends.map((trend) => (
            <TrendRow key={trend.key} analytics={data} metric={trend.key} label={trend.label} />
          ))}
        </div>
        <p className="fine-print">{data.no_composite_note}</p>
      </Panel>

      <div className="analytics-lanes">
        <Panel eyebrow="Assessment" title="What checks and exams showed">
          <div className="lane-metrics">
            <Metric value={data.assessment.diagnostic.submitted} label="Knowledge checks" />
            <Metric value={value(data.assessment.diagnostic.latest_score_pct, "%")} label="Latest check" />
            <Metric value={data.assessment.full_exams.submitted} label="Full exams" />
            <Metric value={value(data.assessment.full_exams.latest_score_pct, "%")} label="Latest full exam" />
          </div>
          {sameScopeTrend.length > 1 ? (
            <div className="assessment-trend">
              <span>Same-scope assessment trend · {recentScope}</span>
              <strong>{sameScopeTrend.map((row) => `${row.score_pct}%`).join(" → ")}</strong>
              <span>{trendDelta! >= 0 ? "+" : ""}{trendDelta} percentage points across these checks</span>
            </div>
          ) : null}
        </Panel>
        <Panel eyebrow="Learning" title="What you opened and completed">
          <div className="lane-metrics">
            <Metric value={data.learning.objectives_started} label="Objectives started" />
            <Metric value={data.learning.lessons_completed} label="Lessons completed" />
            <Metric value={data.learning.recall_completed} label="Recall completed" />
            <Metric value={data.learning.coach_uses} label="Coach uses" />
          </div>
        </Panel>
        <Panel eyebrow="Retention" title="What memory practice scheduled">
          <div className="lane-metrics">
            <Metric value={data.retention.scheduled} label="Scheduled" />
            <Metric value={data.retention.due} label="Due now" />
            <Metric value={data.retention.reviews} label="Reviews logged" />
            <Metric value={data.retention.ratings.again} label="Again ratings" />
          </div>
        </Panel>
        <Panel eyebrow="Notebook" title="What you marked for yourself">
          <div className="lane-metrics">
            <Metric value={data.notebook.highlights} label="Highlights" />
            <Metric value={data.notebook.notes} label="Notes" />
            <Metric value={data.notebook.bookmarks} label="Bookmarks" />
            <Metric value={data.notebook.objectives_with_annotations} label="Objectives annotated" />
          </div>
        </Panel>
        <Panel eyebrow="Hands-on labs" title="What you can reproduce">
          <div className="lane-metrics">
            <Metric value={data.labs.planned} label="Planned" />
            <Metric value={data.labs.in_progress} label="In progress" />
            <Metric value={data.labs.completed} label="Completed" />
            <Metric value={data.labs.unaided} label="Completed unaided" />
          </div>
        </Panel>
      </div>

      <div className="two-column analytics-history">
        <Panel eyebrow="Recent evidence" title="Assessment history">
          <AttemptList title="Knowledge checks" rows={data.assessment.diagnostic.recent} />
          <AttemptList title="Full practice exams" rows={data.assessment.full_exams.recent} />
        </Panel>
        <Panel eyebrow="Latest full exam" title="Domain breakdown">
          {data.assessment.full_exams.latest_domain_breakdown.length ? (
            <ol className="domain-score-list">
              {data.assessment.full_exams.latest_domain_breakdown.map((domain) => (
                <li key={domain.domain_code}>
                  <span><strong>{domain.domain_code}. {domain.domain_name}</strong>
                    <small>{domain.correct} of {domain.total} correct</small></span>
                  <b>{domain.score_pct}%</b>
                </li>
              ))}
            </ol>
          ) : <p className="empty-evidence">Submit a full practice exam to see its governed domain breakdown.</p>}
          <p className="fine-print">{data.assessment.full_exams.mapping_note}</p>
        </Panel>
      </div>

      <p className="analytics-policy">{data.evidence_note} {data.no_composite_note}</p>
    </>
  );
}
