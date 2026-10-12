const CACHE = "waypoint-v2-shell-8";
const SHELL = [
  "/v2/",
  "/v2/site.webmanifest",
  "/v2/favicon.svg",
  "/v2/favicon.ico",
  "/v2/apple-touch-icon.png",
  "/v2/apple-touch-icon-dark.png",
  "/v2/icon-192.png",
  "/v2/icon-192-dark.png",
  "/v2/icon-512.png",
  "/v2/icon-512-dark.png",
];

function cacheable(response) {
  return response.ok &&
    (response.headers.get("X-Waypoint-App") === "2" ||
      response.headers.get("X-Waypoint-Asset") === "2");
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    for (const url of SHELL) {
      const response = await fetch(url, {credentials: "same-origin"});
      if (cacheable(response)) await cache.put(url, response);
    }
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith("waypoint-v2-") && key !== CACHE).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== location.origin ||
      url.pathname.startsWith("/api/") || url.pathname.startsWith("/cdn-cgi/")) return;
  if (!url.pathname.startsWith("/v2/")) return;

  if (request.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (cacheable(response)) {
          const cache = await caches.open(CACHE);
          await cache.put("/v2/", response.clone());
        }
        return response;
      } catch {
        return (await caches.match("/v2/")) || Response.error();
      }
    })());
    return;
  }

  event.respondWith((async () => {
    const cached = await caches.match(request);
    if (cached) return cached;
    const response = await fetch(request);
    if (cacheable(response)) {
      const cache = await caches.open(CACHE);
      await cache.put(request, response.clone());
    }
    return response;
  })());
});
