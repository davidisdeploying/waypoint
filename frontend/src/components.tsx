import type {ReactNode} from "react";

import type {QuestionFigure as QuestionFigureData} from "./types";

export function QuestionFigure({figure}: {figure?: QuestionFigureData | null}) {
  if (!figure?.url) return null;
  return (
    <figure className="question-figure">
      <img src={figure.url} alt="Figure this question refers to" loading="eager" decoding="async" />
    </figure>
  );
}

export function Metric({value, label, detail, accent = false}: {
  value: ReactNode;
  label: string;
  detail?: ReactNode;
  accent?: boolean;
}) {
  return (
    <div className="metric">
      <strong className={accent ? "metric-value accent" : "metric-value"}>{value}</strong>
      <span className="metric-label">{label}</span>
      {detail ? <span className="metric-detail">{detail}</span> : null}
    </div>
  );
}

export function Panel({eyebrow, title, children, action}: {
  eyebrow?: string;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel-head">
        <div>
          {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
          <h2>{title}</h2>
        </div>
        {action ? <div>{action}</div> : null}
      </header>
      {children}
    </section>
  );
}

export function Loading({label = "Loading"}: {label?: string}) {
  return <p className="notice">{label}...</p>;
}

export function ErrorNotice({error}: {error: unknown}) {
  return (
    <p className="notice error" role="alert">
      {error instanceof Error ? error.message : "Something went wrong."}
    </p>
  );
}

export function ProgressBar({value}: {value: number}) {
  const safeValue = Math.max(0, Math.min(100, value));
  return (
    <div className="progress" aria-label={`${safeValue}% complete`}>
      <span style={{width: `${safeValue}%`}} />
    </div>
  );
}

export function formatDate(value?: string | null) {
  if (!value) return "Not set";
  return new Intl.DateTimeFormat("en-US", {month: "short", day: "numeric", year: "numeric"})
    .format(new Date(`${value.slice(0, 10)}T12:00:00`));
}
