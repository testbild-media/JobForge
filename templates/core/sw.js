/* JobForge Service Worker – App-Shell-Cache und Offline-Seite. */
const CACHE = "jobforge-{{ version }}";
const ASSETS = ["/static/css/app.css", "/static/js/app.js", "/static/js/scanner.js", "/static/icons/icon-192.png", "/static/branding/logo_light.svg", "/static/branding/logo_dark.svg", "/offline/"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    // Stale-while-revalidate: sofort aus dem Cache, im Hintergrund aktualisieren
    event.respondWith(caches.open(CACHE).then((cache) => cache.match(req).then((hit) => {
      const update = fetch(req).then((res) => {
        if (res.ok) cache.put(req, res.clone());
        return res;
      }).catch(() => hit);
      return hit || update;
    })));
    return;
  }
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/offline/")));
  }
});
