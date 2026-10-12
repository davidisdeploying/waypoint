import {useQuery} from "@tanstack/react-query";
import {Link} from "react-router-dom";
import {queries} from "../api";
import {ErrorNotice, formatDate, Loading, Metric, Panel} from "../components";
import {WeekList} from "../WeekList";

const statusLabels: Record<string, string> = {
  todo: "Not started",
  studying: "Studying now",
  scheduled: "Exam booked",
  passed: "Passed",
};

export function TimelinePage() {
  const timelineQuery = useQuery({queryKey: ["timeline"], queryFn: queries.timeline});

  if (timelineQuery.isLoading) return <Loading label="Projecting your certification timeline" />;
  if (timelineQuery.error) return <ErrorNotice error={timelineQuery.error} />;
  const timeline = timelineQuery.data!;
  const {entries, pace_hours_per_week: pace} = timeline;

  const done = entries.filter((entry) => entry.status === "passed").length;
  const finishLine = [...entries].reverse().find((entry) => entry.projectedFinish || entry.finished);

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Timeline</span>
        <h1>One certification at a time</h1>
        <p>
          Estimated dates for each certification, grounded in researched study-hour ranges and recomputed from
          your real pace -- not a fixed schedule. These move as your actual progress does.
        </p>
      </div>

      <Panel eyebrow="Deadline and safety margin" title={`${formatDate(timeline.buffer_target_date)} working finish line`}>
        <p className="large-copy">
          Certifications project to finish {formatDate(timeline.projected_all_complete)}
          {timeline.buffer_schedule_delta_days == null ? "." : timeline.buffer_schedule_delta_days > 0
            ? ` — ${timeline.buffer_schedule_delta_days} days after the protected finish line.`
            : ` — ${Math.abs(timeline.buffer_schedule_delta_days)} days before the protected finish line.`}
        </p>
        {timeline.required_buffer_pace_hours_per_week != null ? (
          <p>
            Protected pace: {timeline.required_buffer_pace_hours_per_week.toFixed(1)} hours/week. Current assumed pace: {pace.toFixed(1)} hours/week.
            The working finish line preserves {timeline.completion_buffer_days} days before the {formatDate(timeline.target_date)} WGU target for scheduling or a retake.
          </p>
        ) : null}
      </Panel>

      <div className="metric-grid compact">
        <Metric value={`${done} / ${entries.length}`} label="Certifications passed" />
        <Metric
          value={pace > 0 ? `${pace.toFixed(1)} hrs/wk` : "Not set"}
          label="Current assumed pace"
          detail="Your weekly goal, or your trailing actual pace once enough real history exists"
        />
        <Metric
          value={finishLine ? formatDate(finishLine.finished ?? finishLine.projectedFinish) : "—"}
          label="All six certifications by"
          accent
        />
      </div>

      <div className="credential-list">
        {entries.map((entry) => (
          <article className="credential" key={entry.id}>
            <span className="credential-order">{String(entry.order).padStart(2, "0")}</span>
            <div className="credential-main">
              <span className="eyebrow">{entry.kind || statusLabels[entry.status] || entry.status}</span>
              <h2>{entry.name}</h2>
              <p>{entry.code}</p>
              <p>
                {entry.spine.scope_status === "published_pack" ? "Published real curriculum" : "Official-domain projection"}
                {entry.spine.official_source_status === "hash_verified" ? " · source hash verified" : " · source review required"}
                {` · ${entry.spine.exam_sittings ?? 1} exam sitting${entry.spine.exam_sittings === 1 ? "" : "s"}`}
              </p>
              <p>
                Researched estimate: {entry.estHoursLow}&ndash;{entry.estHoursHigh} hours
                {entry.actualHours != null ? ` · ${entry.actualHours} hours banked so far` : ""}
              </p>
              {entry.status === "passed" ? (
                <p>Studied {formatDate(entry.started)} through {formatDate(entry.finished)}</p>
              ) : entry.status === "studying" ? (
                <p>Started {formatDate(entry.started)} &middot; projected finish {formatDate(entry.projectedFinish)}</p>
              ) : (
                <p>
                  Projected {formatDate(entry.projectedStart)} through {formatDate(entry.projectedFinish)}
                </p>
              )}
            </div>
            <div className="credential-status">{statusLabels[entry.status] ?? entry.status}</div>
          </article>
        ))}
      </div>

      {entries.map((entry) => (
        <WeekList key={entry.id} entry={entry} initiallyOpen={entry.status === "studying"} />
      ))}

      <Panel eyebrow="About this estimate" title="What moves these dates">
        <p>
          Each certification's hour range comes from published exam structure and independent study-time
          research, not a guess. The one certification you are actively studying subtracts real hours already
          banked from that range; every certification after it chains from the one before. Pace defaults to
          your weekly study goal and switches to your real trailing average once enough recent history exists.
        </p>
        <p className="fine-print">
          <Link className="text-link" to="/journey">Change certification status on the Journey page</Link> to
          keep this projection accurate.
        </p>
      </Panel>
    </>
  );
}
