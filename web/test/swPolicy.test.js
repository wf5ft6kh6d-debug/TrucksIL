import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// sw-policy.js is a classic worker script; evaluate it like importScripts() would.
const ctx = { self: {}, URL };
vm.runInNewContext(fs.readFileSync(new URL('../public/sw-policy.js', import.meta.url), 'utf8'), ctx);
const P = ctx.self.TrucksILSWPolicy;
const O = 'https://trucks.example';
const SHELL = ['/', '/index.html'];

test('sw policy: API is never cached; pmtiles/glyphs/shell classified', () => {
  assert.equal(P.classify(`${O}/api/v1/route`, O, SHELL), 'api');
  assert.equal(P.classify(`${O}/api/v1/reports?bbox=1,2,3,4`, O, SHELL), 'api');
  assert.equal(P.classify(`${O}/tiles/israel.pmtiles`, O, SHELL), 'pmtiles');
  assert.equal(P.classify(`${O}/tiles/fonts/Noto%20Sans%20Regular/0-255.pbf`, O, SHELL), 'glyphs');
  assert.equal(P.classify(`${O}/assets/index-abc.js`, O, SHELL), 'shell');
  assert.equal(P.classify(`${O}/index.html`, O, SHELL), 'shell');
  assert.equal(P.classify(`${O}/tiles/other.txt`, O, SHELL), 'other');
  assert.equal(P.classify('https://tile.openstreetmap.org/1/0/0.png', O, SHELL), 'foreign');
});

test('sw policy: only single closed byte ranges get a cache key', () => {
  assert.deepEqual({ ...P.parseRange('bytes=0-16383') }, { start: 0, end: 16383 });
  for (const bad of [null, '', 'bytes=0-', 'bytes=-500', 'bytes=0-1,5-9', 'items=0-1', 'bytes=10-5', `bytes=0-${P.MAX_RANGE_BYTES}`]) assert.equal(P.parseRange(bad), null, String(bad));
  assert.equal(P.rangeKey('/tiles/israel.pmtiles', O, 'bytes=100-199'), `${O}/tiles/israel.pmtiles?__range=100-199`);
  assert.equal(P.rangeKey('/tiles/israel.pmtiles', O, null), null);
});

test('sw policy: LRU eviction down to the byte budget, oldest first', () => {
  const idx = { etag: null, entries: {} };
  P.touch(idx, 'a', 60, 1);
  P.touch(idx, 'b', 60, 2);
  P.touch(idx, 'c', 60, 3);
  P.touch(idx, 'a', undefined, 4); // a used again -> b is now the oldest
  assert.equal(P.totalBytes(idx), 180);
  assert.deepEqual([...P.planEvictions(idx, 130)], ['b']);
  assert.deepEqual([...P.planEvictions(idx, 50)], ['b', 'c', 'a']);
  assert.deepEqual([...P.planEvictions(idx, 500)], []);
  assert.equal(P.TILE_CACHE_MAX_BYTES, 200 * 1024 * 1024);
});

test('sw policy: rebuilt tile file (new ETag) invalidates cached ranges', () => {
  assert.equal(P.etagChanged('"a"', '"b"'), true);
  assert.equal(P.etagChanged('"a"', '"a"'), false);
  assert.equal(P.etagChanged(null, '"a"'), false);
  assert.equal(P.etagChanged('"a"', null), false);
});

test('sw.js: never caches /api responses and imports the policy', () => {
  const src = fs.readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8');
  assert.match(src, /importScripts\('\/sw-policy\.js'\)/);
  assert.match(src, /kind === 'api'/);
  assert.doesNotMatch(src, /api[^\n]*\.put\(/);
});
