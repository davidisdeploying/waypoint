import React from "react";
import ReactDOM from "react-dom/client";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {RouterProvider} from "react-router-dom";
import {router} from "./router";
import {SharedJourneyPage} from "./SharedJourneyPage";
import "@fontsource-variable/archivo";
import "./styles.css";

// waypointjourney.example.com serves the same built bundle as waypoint.example.com (same
// origin process, ops/server.py) but is a separate, unauthenticated hostname for a second person's
// read-only live view -- checked client-side rather than by path, since it isn't part of the
// authenticated app's router at all.
const isSharedJourneyHost = window.location.hostname.startsWith("waypointjourney");

const root = (
  <React.StrictMode>
    {isSharedJourneyHost ? (
      <QueryClientProvider
        client={new QueryClient({
          defaultOptions: {
            queries: {staleTime: 20_000, refetchInterval: 20_000, retry: 1},
          },
        })}
      >
        <SharedJourneyPage />
      </QueryClientProvider>
    ) : (
      <QueryClientProvider
        client={new QueryClient({
          defaultOptions: {
            queries: {staleTime: 30_000, retry: 1},
            mutations: {retry: 0},
          },
        })}
      >
        <RouterProvider router={router} />
      </QueryClientProvider>
    )}
  </React.StrictMode>
);

ReactDOM.createRoot(document.getElementById("root")!).render(root);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/v2/sw.js", {scope: "/v2/"}).catch(() => undefined);
  });
}
