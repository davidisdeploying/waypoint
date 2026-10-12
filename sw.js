/* Waypoint authenticated application shell service worker. */

const SHELL_VERSION = "waypoint-shell-v4";
const SHELL_URL = "/v2/";
const STATIC_ASSETS = [
  "/v2/",
  "/site.webmanifest",
  "/favicon.ico",
  "/favicon.svg",
  "/apple-touch-icon.png",
  "/apple-touch-icon-dark.png",
  "/icon-192.png",
  "/icon-512.png",
  "/assets/brand/waypoint-lockup.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_VERSION).then(async (cache) => {
      for (const url of STATIC_ASSETS) {
        const response = await fetch(url, { credentials: "same-origin", cache: "reload" });
        const isShell = url === SHELL_URL;
        const validShell = response.headers.get("X-Waypoint-App") === "2";
        if (response.ok && (!isShell || validShell)) {
          await cache.put(url, response);
        }
      }
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== SHELL_VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/study-library/") ||
    url.pathname.startsWith("/v2/") ||
    url.pathname.startsWith("/cdn-cgi/")
  ) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).then(async (response) => {
        if (response.ok && response.headers.get("X-Waypoint-App") === "2") {
          const cache = await caches.open(SHELL_VERSION);
          await cache.put(SHELL_URL, response.clone());
        }
        return response;
      }).catch(async () => {
        const cached = await caches.match(SHELL_URL);
        return cached || Response.error();
      })
    );
    return;
  }

  if (STATIC_ASSETS.includes(url.pathname)) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request))
    );
  }
});
