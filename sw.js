// Keep release pages and the catalog on the network so sync updates stay current.
self.addEventListener("fetch", event => {
  if (event.request.mode !== "navigate" || new URL(event.request.url).origin !== self.location.origin) return;

  event.respondWith(fetch(event.request).catch(() => new Response(
    '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Stewart Productions</title><h1>Stewart Productions</h1><p>Reconnect to open the music catalog.</p></html>',
    { headers: { "Content-Type": "text/html; charset=utf-8" }, status: 503 },
  )));
});
