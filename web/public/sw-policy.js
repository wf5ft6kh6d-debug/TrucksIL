// TrucksIL service-worker cache policy (ADR-0008, ADR-0015). Pure helpers, no Cache API calls,
// so they are unit-tested in node (web/test/swPolicy.test.js loads this file in a vm).
// Classic script: loaded by sw.js with importScripts(); exposes self.TrucksILSWPolicy.
(function (root) {
  'use strict';
  var TILE_CACHE_MAX_BYTES = 200 * 1024 * 1024;
  var MAX_RANGE_BYTES = 8 * 1024 * 1024; // a single range larger than this is not cached

  /** 'api' | 'pmtiles' | 'glyphs' | 'shell' | 'other' | 'foreign' */
  function classify(url, origin, shellPaths) {
    var u = new URL(url, origin);
    if (u.origin !== origin) return 'foreign';
    var p = u.pathname;
    if (p.indexOf('/api/') === 0) return 'api'; // routes/restrictions: never cached as valid
    if (p.indexOf('/tiles/fonts/') === 0 && /\.pbf$/.test(p)) return 'glyphs';
    if (p.indexOf('/tiles/') === 0 && /\.pmtiles$/.test(p)) return 'pmtiles';
    if (p.indexOf('/assets/') === 0 || (shellPaths || []).indexOf(p) >= 0) return 'shell';
    return 'other';
  }

  /** Single closed byte range "bytes=a-b" -> {start, end}; anything else -> null (not cached). */
  function parseRange(h) {
    var m = /^bytes=(\d+)-(\d+)$/.exec(String(h || '').trim());
    if (!m) return null;
    var start = Number(m[1]); var end = Number(m[2]);
    if (!(end >= start) || end - start + 1 > MAX_RANGE_BYTES) return null;
    return { start: start, end: end };
  }

  /** Synthetic cache key for one byte range of a file. */
  function rangeKey(url, origin, rangeHeader) {
    var r = parseRange(rangeHeader);
    if (!r) return null;
    var u = new URL(url, origin);
    return u.origin + u.pathname + '?__range=' + r.start + '-' + r.end;
  }

  /** Records use of a cache entry. index = {etag, entries: {key: {size, lastUsed}}} */
  function touch(index, key, size, now) {
    var e = index.entries[key];
    if (e) { e.lastUsed = now; if (size !== undefined) e.size = size; } else index.entries[key] = { size: size || 0, lastUsed: now };
    return index;
  }

  function totalBytes(index) {
    var t = 0;
    for (var k in index.entries) t += index.entries[k].size || 0;
    return t;
  }

  /** Least-recently-used keys to delete so the total fits maxBytes. Does not mutate. */
  function planEvictions(index, maxBytes) {
    var total = totalBytes(index);
    if (total <= maxBytes) return [];
    var keys = Object.keys(index.entries).sort(function (a, b) { return index.entries[a].lastUsed - index.entries[b].lastUsed; });
    var out = [];
    for (var i = 0; i < keys.length && total > maxBytes; i += 1) { out.push(keys[i]); total -= index.entries[keys[i]].size || 0; }
    return out;
  }

  /** The tile file was rebuilt (ETag changed): cached ranges of the old file must all go. */
  function etagChanged(stored, fresh) { return Boolean(stored && fresh && stored !== fresh); }

  var api = { TILE_CACHE_MAX_BYTES: TILE_CACHE_MAX_BYTES, MAX_RANGE_BYTES: MAX_RANGE_BYTES, classify: classify, parseRange: parseRange, rangeKey: rangeKey, touch: touch, totalBytes: totalBytes, planEvictions: planEvictions, etagChanged: etagChanged };
  root.TrucksILSWPolicy = api;
})(typeof self !== 'undefined' ? self : this);
