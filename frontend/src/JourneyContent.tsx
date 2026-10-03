import type {ReactNode} from "react";
import {Link} from "react-router-dom";
import {formatDate, Panel, ProgressBar} from "./components";
import {WeekList} from "./WeekList";
import type {Credential, TimelineResponse, WaypointStateEnvelope} from "./types";

const courseLabels = {
  todo: "Not started",
  in_progress: "In progress",
  done: "Completed",
} as const;

export function JourneyContent({
  envelope,
  timeline,
  renderStatus,
  showTimelineLink = false,
}: {
  envelope: WaypointStateEnvelope;
  timeline: TimelineResponse;
  renderStatus: (credential: Credential) => ReactNode;
  showTimelineLink?: boolean;
}) {
  const passed = envelope.state.certs.filter((item) => item.status === "passed");
  const banked = passed.reduce((total, item) => total + item.cu, 0);
  const accounted = 50 + banked;
  const percent = Math.round((accounted / 109) * 1000) / 10;
  const targetLate = (timeline.schedule_delta_days ?? 0) > 0;
  const bufferLate = (timeline.buffer_schedule_delta_days ?? 0) > 0;

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">Journey</span>
        <h1>Credentials before enrollment</h1>
        <p>One plan for certifications, credit value, target windows, and the remaining degree work.</p>
        {showTimelineLink ? <Link className="text-link" to="/timeline">Open the certification timeline</Link> : null}
      </div>

      <Panel eyebrow="Degree progress" title={`${accounted} of 109 CU accounted for`}>
        <ProgressBar value={percent} />
        <div className="legend">
          <span><i className="ink" />50 awarded</span>
          <span><i className="red" />{banked} banked from credentials</span>
          <span><i />{109 - accounted} remaining</span>
        </div>
        <p className="fine-print">Planned WGU start: <strong>{formatDate(envelope.state.meta.wguStartDate)}</strong>.</p>
      </Panel>

      <Panel eyebrow="Enrollment readiness" title={`Protected finish ${formatDate(timeline.buffer_target_date)}`}>
        <p className="large-copy">
          Current projection: <strong>{formatDate(timeline.projected_all_complete)}</strong>
          {timeline.schedule_delta_days == null ? "" : targetLate
            ? ` · ${timeline.schedule_delta_days} days after target`
            : ` · ${Math.abs(timeline.schedule_delta_days)} days before target`}.
        </p>
        <p>
          Current pace is {timeline.pace_hours_per_week.toFixed(1)} hours/week. The protected finish preserves {timeline.completion_buffer_days} days before the {formatDate(timeline.target_date)} WGU start.
        </p>
        {timeline.required_buffer_pace_hours_per_week != null ? (
          <div className="pace-choices">
            <div><strong>Keep the current pace</strong><span>Projection remains {bufferLate ? `${timeline.buffer_schedule_delta_days} days after the protected finish` : "inside the protected finish"}.</span></div>
            <div><strong>Protect a retake window</strong><span>Aim for about {timeline.required_buffer_pace_hours_per_week.toFixed(1)} hours/week and let the projection recalculate from real activity.</span></div>
          </div>
        ) : null}
      </Panel>

      <div className="credential-list">
        {envelope.state.certs.slice().sort((a, b) => a.order - b.order).map((credential) => (
          <article className="credential" key={credential.id}>
            <span className="credential-order">{String(credential.order).padStart(2, "0")}</span>
            <div className="credential-main">
              <span className="eyebrow">{credential.kind}</span>
              <h2>{credential.name}</h2>
              <p>{credential.code} · {credential.cu} CU · ${credential.price}</p>
              <p>{credential.clears}</p>
              {credential.exam ? <p>Exam: {formatDate(credential.exam)}</p> : null}
            </div>
            {renderStatus(credential)}
          </article>
        ))}
      </div>

      <Panel eyebrow="52-week plan" title="Every certification, week by week">
        <p className="fine-print">
          A+ shows real ingested study content. Every certification after it is projected from that exam's
          official domain list until its own content is built — a real topic, not a guess, but no progress
          until real study evidence exists for it.
        </p>
      </Panel>
      {timeline.entries.map((entry) => (
        <WeekList key={entry.id} entry={entry} initiallyOpen={entry.status === "studying"} />
      ))}

      <Panel eyebrow="Remaining WGU plan" title="Courses after credential transfer">
        <div className="course-list">
          {envelope.state.courses.map((course) => (
            <div key={course.code}>
              <strong>{course.code}</strong>
              <span>{course.name}</span>
              <span>{course.cu} CU</span>
              <span>{courseLabels[course.status]}</span>
            </div>
          ))}
        </div>
        <p className="fine-print">Course and paired-credential assumptions remain pending counselor confirmation where noted.</p>
      </Panel>
    </>
  );
}
