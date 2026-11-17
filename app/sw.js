/*
  Offline support.

  Two things the first version got wrong, both of which strand a reader on a
  broken copy:

  - The cache name never changed between deploys, and every request was served
    cache-first, so a fix could never reach anyone who had already visited.
  - install used cache.addAll, which rejects as a whole if any one file is
    missing. A single bad path left the worker uninstalled and silent.

  Now: the cache name carries a build stamp, files are cached individually so
  one failure cannot sink the rest, and responses are served stale while being
  revalidated. A reader offline gets the cached copy at once; a reader online
  gets it too, and the next visit has the update.
*/

const VERSION = "am-3";
const CACHE = `am-encyclopaedia-${VERSION}`;

// Paths are resolved against the worker's own scope, so they hold wherever
// the app is served from.
const SHELL = [
  "./",
  "index.html",
  "ui/styles.css",
  "ui/app.js",
  "core/normalise.js",
  "core/data/load.js",
  "core/search/engine.js",
  "core/search/headwords.js",
  "core/search/definitions.js",
  "data/headwords.json",
  "data/entries.json",
  "data/meta.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // Individually, so one missing file cannot fail the install.
    await Promise.allSettled(SHELL.map(async (path) => {
      const url = new URL(path, self.registration.scope).href;
      const response = await fetch(url, { cache: "reload" });
      if (response.ok) await cache.put(url, response);
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names
      .filter((name) => name.startsWith("am-encyclopaedia-") && name !== CACHE)
      .map((name) => caches.delete(name)));
    // Older builds used a bare version string as the cache name.
    await caches.delete("am-1");
    await caches.delete("am-2");
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(request);

    const network = fetch(request).then((response) => {
      if (response && response.ok && response.type === "basic") {
        cache.put(request, response.clone()).catch(() => {});
      }
      return response;
    }).catch(() => undefined);

    // Serve what we have, update behind it. With nothing cached, wait for the
    // network; if that fails too, say so rather than returning an opaque error.
    if (cached) return cached;
    const response = await network;
    if (response) return response;
    return new Response("Offline and not cached yet.", {
      status: 503,
      headers: { "Content-Type": "text/plain" },
    });
  })());
});
