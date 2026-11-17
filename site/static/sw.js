// Offline helper for the installed app (and any browser that supports it).
// It keeps copies of pages, data and files already viewed, only in this device's browser, so the site
// opens quickly and shows what was last seen when there's no signal. Nothing is sent anywhere: it only
// handles this site's own requests, and the network always comes first so figures are never stale
// when online. Bump VERSION to clear old copies.
const VERSION = "v1";
const PAGES = `cc-pages-${VERSION}`, DATA = `cc-data-${VERSION}`, FILES = `cc-files-${VERSION}`;
const LIMITS = { [PAGES]: 80, [DATA]: 300, [FILES]: 120 };
const OFFLINE = "/offline.html";

self.addEventListener("install", event => {
  event.waitUntil(caches.open(FILES).then(c => c.addAll([OFFLINE, "/site.css", "/site.js", "/cards.js", "/favicon.svg"]))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("cc-") && !(k in LIMITS)).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function trim(name) {
  const cache = await caches.open(name), keys = await cache.keys();
  for (const k of keys.slice(0, Math.max(0, keys.length - LIMITS[name]))) await cache.delete(k);
}

// Network first; a copy is kept for when there's no connection.
async function networkFirst(request, name, fallback) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const copy = response.clone();
      caches.open(name).then(c => c.put(request, copy)).then(() => trim(name));
    }
    return response;
  } catch (err) {
    const kept = await caches.match(request, { ignoreVary: true });
    if (kept) return kept;
    if (fallback) return (await caches.match(fallback)) || Response.error();
    throw err;
  }
}

self.addEventListener("fetch", event => {
  const { request } = event, url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== location.origin) return;   // other sites: untouched
  if (url.pathname === "/sw.js") return;
  if (request.mode === "navigate") event.respondWith(networkFirst(request, PAGES, OFFLINE));
  else if (url.pathname.startsWith("/api/")) event.respondWith(networkFirst(request, DATA));
  else event.respondWith(networkFirst(request, FILES));
});
