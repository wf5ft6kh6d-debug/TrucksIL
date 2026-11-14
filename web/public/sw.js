// TrucksIL service worker: caches the APP SHELL ONLY (ADR-0008).
// Never cached: /api/* (routes, restrictions: stale safety data must not be served) and map
// tiles (other origins; OSM tile policy forbids bulk/offline caching).
const CACHE = 'trucksil-shell-v1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icons/icon.svg', '/icons/icon-192.png', '/icons/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return; // tiles etc.: network only
  if (url.pathname.startsWith('/api/')) return; // API: network only, never cached
  if (e.request.mode === 'navigate') {
    // Network first for the page so updates arrive; cached shell when offline.
    e.respondWith(fetch(e.request).catch(() => caches.match('/index.html')));
    return;
  }
  if (url.pathname.startsWith('/assets/') || SHELL.includes(url.pathname)) {
    // Hashed build assets and shell files: cache first, filled on first use.
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
      return res;
    })));
  }
});
