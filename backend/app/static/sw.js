/* Library of Alexandria — service worker.
   Shell cached for offline launch; API is network-first (fresh data, graceful offline). */
const CACHE = 'loa-v58';
const SHELL = [
  '/', '/static/css/app.css', '/static/css/tokens.css', '/static/css/fonts.css',
  '/static/js/app.js', '/manifest.json',
  '/static/icons/icon-192.png', '/static/icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);

  // API: network-first, fail soft.
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(req).catch(() =>
      new Response(JSON.stringify({ error: 'offline' }),
        { status: 503, headers: { 'Content-Type': 'application/json' } })));
    return;
  }
  // Same-origin shell: stale-while-revalidate.
  if (url.origin === self.location.origin) {
    e.respondWith(caches.match(req).then((cached) => {
      const net = fetch(req).then((resp) => {
        if (resp && resp.status === 200 && resp.type === 'basic') {
          const clone = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, clone));
        }
        return resp;
      }).catch(() => cached);
      return cached || net;
    }));
  }
});
