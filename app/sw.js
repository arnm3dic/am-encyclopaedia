/*
  Offline support.

  The data files are large and never change between deploys, so they are
  cached on first use and then served cache-first. The shell is revalidated in
  the background so a deploy takes effect on the next visit without the user
  reinstalling anything.
*/
const VERSION = "am-1";
const SHELL = ["./", "index.html", "ui/styles.css", "ui/app.js",
  "core/normalise.js", "core/data/load.js", "core/search/engine.js",
  "core/search/headwords.js", "core/search/definitions.js",
  "data/headwords.json", "data/entries.json", "data/meta.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(
    caches.match(event.request).then((hit) => {
      if (hit) return hit;
      return fetch(event.request).then((response) => {
        if (response.ok && response.type === "basic") {
          const copy = response.clone();
          caches.open(VERSION).then((cache) => cache.put(event.request, copy));
        }
        return response;
      }).catch(() => hit ?? Response.error());
    }),
  );
});
