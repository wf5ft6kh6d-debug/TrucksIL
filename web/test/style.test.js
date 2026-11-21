import test from 'node:test';
import assert from 'node:assert/strict';
import { vectorStyle, rasterFallbackStyle, isPmtilesHeader, nameExpr, PMTILES_PATH } from '../src/map/style.js';

test('style: PMTiles source + self-hosted glyphs on the same origin, labels in UI language', () => {
  const s = vectorStyle({ origin: 'http://localhost:8081', lang: 'ar' });
  assert.equal(s.version, 8);
  assert.equal(s.sources.omt.url, `pmtiles://http://localhost:8081${PMTILES_PATH}`);
  assert.equal(s.glyphs, 'http://localhost:8081/tiles/fonts/{fontstack}/{range}.pbf');
  const ids = s.layers.map((l) => l.id);
  assert.equal(new Set(ids).size, ids.length, 'unique layer ids');
  for (const l of s.layers) if (l.source) assert.equal(l.source, 'omt');
  const place = s.layers.find((l) => l.id === 'place');
  assert.deepEqual(place.layout['text-field'], nameExpr('ar'));
  assert.deepEqual(nameExpr('he'), ['coalesce', ['get', 'name:he'], ['get', 'name']]);
  assert.match(s.sources.omt.attribution, /OpenStreetMap/);
  for (const u of JSON.stringify(s).match(/https?:\/\/[^"]+/g)) assert.ok(u.startsWith('http://localhost:8081') || /openstreetmap\.org\/copyright|openmaptiles\.org/.test(u), u);
});

test('style: raster fallback and PMTiles magic check', () => {
  assert.equal(rasterFallbackStyle().sources.osm.type, 'raster');
  assert.equal(isPmtilesHeader(new Uint8Array([0x50, 0x4d, 0x54, 0x69, 0x6c, 0x65, 0x73, 3])), true);
  assert.equal(isPmtilesHeader(new Uint8Array([0x50, 0x4d, 0x54, 0x69, 0x6c, 0x65, 0x73, 2])), false);
  assert.equal(isPmtilesHeader(new TextEncoder().encode('<!doctype html>')), false);
  assert.equal(isPmtilesHeader(null), false);
});
