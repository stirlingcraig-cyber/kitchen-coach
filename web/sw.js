// Kitchen Coach service worker: makes the iPhone / web build work fully offline.
const CACHE = "kitchen-coach-v1.0.0";
const ASSETS = [
  "./", "index.html", "styles.css", "app.js", "parser.js", "manifest.webmanifest",
  "icons/logo.svg", "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png",
  "icons/apple-touch-icon.png", "vendor/pdf.min.js", "vendor/pdf.worker.min.js", "vendor/jszip.min.js",
  "samples/beef_ragu.pdf",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.includes("/api/")) return;
  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(req, { ignoreSearch: true }) ||
        (req.mode === "navigate" ? await cache.match("index.html") : undefined);
      const network = fetch(req).then((res) => {
        if (res.ok && res.type === "basic") cache.put(req, res.clone());
        return res;
      }).catch(() => cached);
      return cached || network; // cached first (instant + offline), refreshed in the background
    }),
  );
});
