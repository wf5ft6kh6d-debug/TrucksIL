// TrucksIL service worker (ADR-0008, ADR-0015).
//   app shell          : cache-first (hashed assets) / network-first (page)
//   /tiles/*.pmtiles    : network-first per byte range; ranges are cached (LRU, 200 MB) so areas
//                         viewed and tiles warmed along the current route work offline
//   /tiles/fonts/*.pbf  : cache-first (same LRU cache)
//   /api/*              : network only, NEVER cached. The page keeps its own copy of the last
//                         route and shows it offline only as "outdated" (web/src/nav/offline.js).
//   other origins       : untouched (OSM raster fallback tiles are never cached: OSM tile policy).
importScripts('/sw-policy.js');
const P = self.TrucksILSWPolicy;
const CACHE = 'trucksil-shell-v2';
const TILES = 'trucksil-tiles-v1';
const INDEX_URL = '/__trucksil/tile-index.json';
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/sw-policy.js', '/icons/icon.svg', '/icons/icon-192.png', '/icons/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE && k !== TILES).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// ---- tile cache index (LRU bookkeeping), persisted inside the tile cache itself ----
let indexP = null;
let saveTimer = null;
function loadIndex() {
  if (!indexP) {
    indexP = caches.open(TILES).then((c) => c.match(INDEX_URL)).then((r) => (r ? r.json() : null))
      .catch(() => null).then((v) => (v && v.entries ? v : { etag: null, entries: {} }));
  }
  return indexP;
}
function saveIndexSoon(index) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    caches.open(TILES).then((c) => c.put(INDEX_URL, new Response(JSON.stringify(index), { headers: { 'content-type': 'application/json' } }))).catch(() => {});
  }, 2000);
}
async function evict(index) {
  const c = await caches.open(TILES);
  for (const k of P.planEvictions(index, P.TILE_CACHE_MAX_BYTES)) { delete index.entries[k]; await c.delete(k); }
}
async function purgeTiles(index) {
  const c = await caches.open(TILES);
  for (const k of Object.keys(index.entries)) await c.delete(k);
  index.entries = {};
}

async function pmtilesRange(req) {
  const key = P.rangeKey(req.url, self.location.origin, req.headers.get('range'));
  if (!key) return fetch(req); // no/odd range: pass through, not cached
  const index = await loadIndex();
  try {
    const res = await fetch(req);
    if (res.status === 206) {
      const etag = res.headers.get('etag');
      if (P.etagChanged(index.etag, etag)) await purgeTiles(index);
      if (etag) index.etag = etag;
      const buf = await res.clone().arrayBuffer();
      const headers = { 'content-type': res.headers.get('content-type') || 'application/octet-stream', 'x-trucksil-content-range': res.headers.get('content-range') || '' };
      if (etag) headers.etag = etag;
      const c = await caches.open(TILES);
      await c.put(key, new Response(buf, { status: 200, headers }));
      P.touch(index, key, buf.byteLength, Date.now());
      await evict(index);
      saveIndexSoon(index);
    }
    return res;
  } catch (err) {
    const hit = await (await caches.open(TILES)).match(key);
    if (!hit) throw err;
    P.touch(index, key, undefined, Date.now());
    saveIndexSoon(index);
    const h = new Headers(hit.headers);
    h.set('content-range', h.get('x-trucksil-content-range'));
    h.delete('x-trucksil-content-range');
    return new Response(await hit.arrayBuffer(), { status: 206, headers: h });
  }
}

async function glyphs(req) {
  const c = await caches.open(TILES);
  const index = await loadIndex();
  const hit = await c.match(req.url);
  if (hit) { P.touch(index, req.url, undefined, Date.now()); saveIndexSoon(index); return hit; }
  const res = await fetch(req);
  if (res.ok) {
    const buf = await res.clone().arrayBuffer();
    await c.put(req.url, new Response(buf, { headers: { 'content-type': 'application/x-protobuf' } }));
    P.touch(index, req.url, buf.byteLength, Date.now());
    await evict(index);
    saveIndexSoon(index);
  }
  return res;
}

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  const kind = P.classify(e.request.url, self.location.origin, SHELL);
  if (kind === 'foreign' || kind === 'api' || kind === 'other') {
    if (kind === 'other' && e.request.mode === 'navigate') e.respondWith(fetch(e.request).catch(() => caches.match('/index.html')));
    return; // network only
  }
  if (kind === 'pmtiles') return e.respondWith(pmtilesRange(e.request));
  if (kind === 'glyphs') return e.respondWith(glyphs(e.request));
  if (e.request.mode === 'navigate') return e.respondWith(fetch(e.request).catch(() => caches.match('/index.html')));
  // shell: cache first, filled on first use
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return res;
  })));
});
