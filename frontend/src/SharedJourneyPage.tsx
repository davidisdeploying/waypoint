import {useEffect, useState} from "react";
import {useIsFetching, useQuery} from "@tanstack/react-query";
import {getWaypointState, queries} from "./api";
import {ErrorNotice, Loading} from "./components";
import {JourneyContent} from "./JourneyContent";
import {WeeklyGoalBar} from "./WeeklyGoalBar";

const statusLabels = {
  todo: "Not started",
  studying: "Studying",
  scheduled: "Exam booked",
  passed: "Passed",
};

// Read-only mirror of JourneyPage for the public waypointjourney.example.com host: same
// components, same CSS, no primary nav, no SessionPresence (no session side effects should
// ever run from an unauthenticated visitor's browser), and no mutation path anywhere --
// status renders as a badge, WeeklyGoalBar renders readOnly.
export function SharedJourneyPage() {
  const fetching = useIsFetching();
  const [online, setOnline] = useState(navigator.onLine);
  const stateQuery = useQuery({queryKey: ["waypoint-state"], queryFn: getWaypointState});
  const timelineQuery = useQuery({queryKey: ["timeline"], queryFn: queries.timeline});

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  const loading = stateQuery.isLoading || timelineQuery.isLoading;
  const error = stateQuery.error || timelineQuery.error;
  const envelope = stateQuery.data;

  return (
    <div className="app">
      <header className="masthead">
        <div className="shell-width brand-row">
          <img src="/v2/waypoint-lockup.svg" width="209" height="40" alt="Waypoint" />
          <span>Shared credential journey</span>
        </div>
      </header>
      <WeeklyGoalBar readOnly />
      <div className={online ? "connection" : "connection warning"}>
        <div className="shell-width">
          <span className="status-dot" />
          <span>{!online ? "Offline snapshot" : fetching ? "Refreshing shared view" : "Live shared view"}</span>
        </div>
      </div>
      <main className="shell-width page">
        {loading ? <Loading label="Mapping the journey" /> : null}
        {!loading && error ? <ErrorNotice error={error} /> : null}
        {!loading && !error && !envelope ? (
          <ErrorNotice error={new Error("Waypoint milestone state has not been initialized.")} />
        ) : null}
        {!loading && !error && envelope && timelineQuery.data ? (
          <JourneyContent
            envelope={envelope}
            timeline={timelineQuery.data}
            renderStatus={(credential) => (
              <div className="credential-status">{statusLabels[credential.status]}</div>
            )}
          />
        ) : null}
      </main>
      <footer className="footer">
        <div className="shell-width">
          <strong>Waypoint</strong>
          <span>Your private study and credential workspace.</span>
        </div>
      </footer>
    </div>
  );
}
