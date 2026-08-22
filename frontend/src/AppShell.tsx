import {useEffect, useRef, useState} from "react";
import {NavLink, Outlet, useLocation} from "react-router-dom";
import {useIsFetching} from "@tanstack/react-query";
import {SessionPresence, SessionStatus} from "./SessionPresence";
import {WeeklyGoalBar} from "./WeeklyGoalBar";
import {AppAppearanceSettings, useAppAppearance} from "./AppAppearance";

const navigation = [
  {to: "/", label: "Today"},
  {to: "/study", label: "Study"},
  {to: "/mastery", label: "Mastery"},
  {to: "/library", label: "Library"},
  {to: "/journey", label: "Journey"},
  {to: "/more", label: "More"},
];

export function AppShell() {
  const fetching = useIsFetching();
  const [online, setOnline] = useState(navigator.onLine);
  const navRef = useRef<HTMLElement>(null);
  const location = useLocation();
  const appearance = useAppAppearance();

  // The status strip sticks directly beneath the primary nav. Measuring the nav
  // beats hardcoding its height: the two stay flush when it reflows, and the
  // 640px breakpoint that moves the nav to the bottom sets its own offset.
  useEffect(() => {
    const nav = navRef.current;
    if (!nav || typeof ResizeObserver === "undefined") return;
    const apply = () =>
      document.documentElement.style.setProperty("--nav-height", `${nav.offsetHeight}px`);
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(nav);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  return (
    <div className="app">
      <SessionPresence />
      <header className="masthead">
        <div className="shell-width brand-row">
          <img src="/v2/waypoint-lockup.svg" width="209" height="40" alt="Waypoint" />
          <span>Private learning and credential workspace</span>
        </div>
      </header>
      <nav ref={navRef} className="primary-nav" aria-label="Primary navigation">
        <div className="shell-width nav-grid">
          {navigation.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>
      <WeeklyGoalBar />
      <div className={online ? "connection" : "connection warning"}>
        <div className="shell-width">
          <span className="status-dot" />
          <span className="connection-label">{!online ? "Offline snapshot" : fetching ? "Refreshing private data" : "Private services connected"}</span>
          <SessionStatus />
        </div>
      </div>
      <main className="shell-width page">
        <Outlet />
        {location.pathname === "/more" ? (
          <AppAppearanceSettings
            preference={appearance.preference}
            resolvedTheme={appearance.resolvedTheme}
            onChange={appearance.setPreference}
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
