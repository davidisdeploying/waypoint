import {ProgressBar, formatDate} from "./components";
import type {TimelineEntry} from "./types";

export function WeekList({entry, initiallyOpen = false}: {entry: TimelineEntry; initiallyOpen?: boolean}) {
  if (!entry.weeks.length) return null;
  const real = entry.weeks[0].source === "real";

  return (
    <details className="mastery-domain" open={initiallyOpen}>
      <summary>
        <div>
          <span className="eyebrow">{entry.weeks.length}-week plan</span>
          <h2>{entry.name}</h2>
          <p>{real ? "From your ingested study content" : "Projected from official exam domains"}</p>
        </div>
      </summary>
      <ol className="week-list">
        {entry.weeks.map((week) => (
          <li key={week.week_number}>
            <time>Week {week.week_number}<br />{formatDate(week.date)}</time>
            <span className="week-topic">{week.topic}</span>
            <ProgressBar value={week.progress_percent} />
            <span className="week-projected-badge">{week.source === "projected" ? "Projected" : ""}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}
