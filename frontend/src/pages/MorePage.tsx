import {useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {getWaypointState, queries} from "../api";
import {ErrorNotice, Loading, Panel} from "../components";
import type {DailyStudySession} from "../types";
import {Link} from "react-router-dom";

function sessionMinutes(session: DailyStudySession) {
  return session.duration_minutes ?? Math.floor(session.elapsed_seconds / 60);
}

export function MorePage() {
  const queryClient = useQueryClient();
  const [confirmingDelete, setConfirmingDelete] = useState<number | null>(null);
  const stateQuery = useQuery({queryKey: ["waypoint-state"], queryFn: getWaypointState});
  const healthQuery = useQuery({queryKey: ["study-health"], queryFn: queries.health, refetchInterval: 60_000});
  const historyQuery = useQuery({queryKey: ["daily-session-history"], queryFn: queries.dailySessionHistory});
  const deleteSession = useMutation({
    mutationFn: queries.deleteDailySession,
    onSuccess: () => {
      setConfirmingDelete(null);
      void queryClient.invalidateQueries({queryKey: ["daily-session-history"]});
      void queryClient.invalidateQueries({queryKey: ["daily-session"]});
      void queryClient.invalidateQueries({queryKey: ["study-dashboard"]});
      void queryClient.invalidateQueries({queryKey: ["analytics"]});
    },
  });

  if (stateQuery.isLoading || healthQuery.isLoading || historyQuery.isLoading) return <Loading label="Checking private services" />;
  const error = stateQuery.error || healthQuery.error || historyQuery.error;
  if (error) return <ErrorNotice error={error} />;

  const standalone = window.matchMedia("(display-mode: standalone)").matches ||
    ("standalone" in navigator && Boolean((navigator as Navigator & {standalone?: boolean}).standalone));

  return (
    <>
      <div className="page-title">
        <span className="eyebrow">More</span>
        <h1>App, data, and privacy</h1>
        <p>Operational state is visible here without exposing internal infrastructure to the public internet.</p>
      </div>

      <div className="two-column">
        <Panel eyebrow="Waypoint" title="Milestone state">
          <dl className="status-list">
            <div><dt>Status</dt><dd>{stateQuery.data ? "Synced" : "Not initialized"}</dd></div>
            <div><dt>Revision</dt><dd>{stateQuery.data?.revision ?? "-"}</dd></div>
            <div><dt>Updated</dt><dd>{stateQuery.data?.updated_at ?? "-"}</dd></div>
            <div><dt>Install mode</dt><dd>{standalone ? "Home Screen app" : "Browser preview"}</dd></div>
          </dl>
        </Panel>
        <Panel eyebrow="Study Core" title="Learning evidence">
          <dl className="status-list">
            <div><dt>Status</dt><dd>{healthQuery.data?.status}</dd></div>
            <div><dt>Schema</dt><dd>{healthQuery.data?.schema_version}</dd></div>
            <div><dt>Transport</dt><dd>Private Waypoint gateway</dd></div>
            <div><dt>Runtime</dt><dd>Co-located on Alpha</dd></div>
          </dl>
        </Panel>
      </div>

      <Panel eyebrow="Architecture" title="One product, bounded internal services">
        <div className="architecture-flow" aria-label="Waypoint architecture">
          <span>Installed PWA</span><b>→</b><span>Cloudflare Access</span><b>→</b>
          <span>Alpha gateway</span><b>→</b><span>Co-located Study Core</span>
        </div>
        <p>
          Cloudflare Access and TLS protect the public origin. Study Core is reachable only through the
          same Alpha host through its local-only service boundary. The study database is not exposed as a
          separate public service.
        </p>
      </Panel>

      <Panel eyebrow="Your data" title="Export a portable copy">
        <div className="action-row">
          <a className="button secondary" href="/api/v2/study/export">Download study export</a>
        </div>
        <p className="fine-print">
          The export includes your books, study plan, sessions, attempts, and learning evidence.
        </p>
      </Panel>

      <Panel eyebrow="Career bridge" title="Learning requests from Prospect">
        <p>Review planning-only skill proposals imported from job listing audits. They never count as progress, mastery, or credential evidence.</p>
        <Link className="button secondary" to="/learning-requests">Review learning requests</Link>
      </Panel>

      <Panel eyebrow="Study logging" title="Recorded sessions">
        <p>
          Timing starts automatically on active study screens. It pauses on other Waypoint pages, after five
          idle minutes, when the app is backgrounded, or when your phone is locked.
        </p>
        {historyQuery.data!.sessions.length ? (
          <ol className="session-history-list">
            {historyQuery.data!.sessions.map((session) => (
              <li key={session.id}>
                <div className="session-history-summary">
                  <time dateTime={session.ended_at ?? session.started_at}>
                    {new Intl.DateTimeFormat(undefined, {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(session.ended_at ?? session.started_at))}
                  </time>
                  <strong>{session.task_title}</strong>
                  <span>
                    {sessionMinutes(session)} minute{sessionMinutes(session) === 1 ? "" : "s"} · {session.events.length} recorded activit{session.events.length === 1 ? "y" : "ies"}
                  </span>
                </div>
                {confirmingDelete === session.id ? (
                  <div className="session-delete-confirmation" role="alert">
                    <p>Delete this session from study totals and analytics? Learning evidence recorded elsewhere will remain.</p>
                    <div className="action-row">
                      <button className="button secondary" type="button" onClick={() => setConfirmingDelete(null)}>
                        Keep session
                      </button>
                      <button
                        className="button danger"
                        type="button"
                        disabled={deleteSession.isPending}
                        onClick={() => deleteSession.mutate(session.id)}
                      >
                        {deleteSession.isPending ? "Deleting..." : "Delete session"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button className="text-button session-delete-button" type="button" onClick={() => setConfirmingDelete(session.id)}>
                    Delete
                  </button>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p className="notice">No completed study sessions have been recorded yet.</p>
        )}
        {deleteSession.error ? <ErrorNotice error={deleteSession.error} /> : null}
        <p className="fine-print">Deleted sessions are excluded from the app and its totals while a private recovery marker is retained.</p>
      </Panel>

      <Panel eyebrow="Install" title="Use Waypoint on iPhone">
        <p>Open this private page in Safari, tap Share, choose Add to Home Screen, and keep Open as Web App enabled.</p>
        <p className="fine-print">The Home Screen app opens the same private production workspace as Safari.</p>
      </Panel>
    </>
  );
}
