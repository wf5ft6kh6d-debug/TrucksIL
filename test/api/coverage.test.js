'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { computeCoverage, structuresFromTrace, traceAttributesRequest, routeWayIds, COVERAGE_BUFFER_M, UNDERPASS_NEAR_M } = require('../../api/src/coverage');
const { createUnderpassesRepo, PRESENT_SQL, LOADED_SQL, ON_ROUTE_SQL } = require('../../api/src/underpassesRepo');
const { encodePolyline, decodePolyline } = require('../../api/src/polyline');
const { createHandler } = require('../../api/src/app');
const http = require('node:http');

const shape = [[34.78, 32.08], [34.785, 32.085], [34.79, 32.09], [34.795, 32.095], [34.80, 32.10], [34.81, 32.11]];
const trace = {
  shape: encodePolyline(shape),
  edges: [
    { way_id: 1, begin_shape_index: 0, end_shape_index: 1 },
    { way_id: 10, bridge: true, begin_shape_index: 1, end_shape_index: 2 },
    { way_id: 10, bridge: true, begin_shape_index: 2, end_shape_index: 3 }, // same bridge, split edge
    { way_id: 2, begin_shape_index: 3, end_shape_index: 4 },
    { way_id: 20, tunnel: true, begin_shape_index: 4, end_shape_index: 5 },
  ],
};
const ok = (json) => async () => ({ ok: true, status: 200, json });

test('traceAttributesRequest: edge_walk with bridge/tunnel attributes', () => {
  const b = traceAttributesRequest(shape);
  assert.equal(b.shape_match, 'edge_walk');
  assert.ok(b.filters.attributes.includes('edge.bridge') && b.filters.attributes.includes('edge.tunnel'));
  assert.equal(decodePolyline(b.encoded_polyline).length, shape.length);
});

test('structuresFromTrace merges consecutive edges of one way', () => {
  const s = structuresFromTrace(trace, shape);
  assert.deepEqual(s.map((x) => [x.type, x.wayId, x.wayIds, x.coords.length]), [['bridge', 10, [10], 3], ['tunnel', 20, [20], 2]]);
});

test('structuresFromTrace merges adjacent structures of different ways (contiguous or < 20 m gap)', () => {
  // points 0..3 ~5 m apart, then a 1 km jump
  const sh = [[35.2, 31.78], [35.20005, 31.78], [35.2001, 31.78], [35.20015, 31.78], [35.21, 31.78], [35.211, 31.78]];
  const t = { shape: encodePolyline(sh), edges: [
    { way_id: 1, tunnel: true, begin_shape_index: 0, end_shape_index: 1 },
    { way_id: 2, tunnel: true, begin_shape_index: 1, end_shape_index: 2 }, // contiguous index
    { way_id: 3, tunnel: true, begin_shape_index: 3, end_shape_index: 3 }, // ~5 m gap
    { way_id: 4, tunnel: true, begin_shape_index: 4, end_shape_index: 5 }, // ~900 m gap -> new
    { way_id: 5, bridge: true, begin_shape_index: 5, end_shape_index: 5 }, // other type -> new
  ] };
  const s = structuresFromTrace(t, sh);
  assert.deepEqual(s.map((x) => [x.type, x.wayId, x.wayIds, x.coords.length]),
    [['tunnel', 1, [1, 2, 3], 4], ['tunnel', 4, [4], 2], ['bridge', 5, [5], 1]]);
});

test('routeWayIds: every edge way id, unique', () => {
  assert.deepEqual(routeWayIds(trace).sort((a, b) => a - b), [1, 2, 10, 20]);
  assert.deepEqual(routeWayIds({ edges: [{}, { way_id: null }] }), []);
});

test('underpasses: matched by route way ids; no data / OSM candidate; with data', async () => {
  const seen = [];
  const underpassRepo = { findOnRoute: async (ids, sh, near, buf) => {
    seen.push([ids.sort((a, b) => a - b), near, buf]);
    return { loaded: true, rows: [
      { point: [34.79, 32.09], roadRef: '1', osmMaxheightText: '4.2', osmMaxheightM: 4.2, hasData: false },
      { point: [34.80, 32.10], roadRef: null, osmMaxheightText: null, hasData: true },
    ] };
  } };
  const c = await computeCoverage({ callTraceAttributes: ok(trace), repo: { findAlongRoute: async () => [] }, underpassRepo, shape });
  assert.deepEqual(seen, [[[1, 2, 10, 20], UNDERPASS_NEAR_M, COVERAGE_BUFFER_M]]);
  assert.equal(c.underpassStatus, 'computed');
  assert.equal(c.underpassesOnRoute, 2);
  assert.equal(c.underpassesWithData, 1);
  assert.deepEqual(c.noDataUnderpasses, [{ point: [34.79, 32.09], roadRef: '1',
    osmMaxheightCandidate: { text: '4.2', metres: 4.2, note: 'OSM candidate, not used for routing' } }]);
});

test('underpasses: missing/empty table or no repo -> not_loaded (never zero); failure -> unknown', async () => {
  const base = { callTraceAttributes: ok(trace), repo: { findAlongRoute: async () => [] }, shape };
  for (const underpassRepo of [undefined, { findOnRoute: async () => ({ loaded: false }) }]) {
    const c = await computeCoverage({ ...base, underpassRepo });
    assert.deepEqual([c.status, c.underpassStatus, c.underpassesOnRoute, c.noDataUnderpasses], ['computed', 'not_loaded', null, null]);
  }
  const c = await computeCoverage({ ...base, underpassRepo: { findOnRoute: async () => { throw new Error('db'); } } });
  assert.deepEqual([c.status, c.underpassStatus, c.underpassesOnRoute], ['computed', 'unknown', null]);
});

test('underpassesRepo: table absent/empty -> loaded:false; query passes way ids', async () => {
  const mk = (present, loaded, rows = []) => { const q = []; return { q, db: { query: async (sql, p) => {
    q.push([sql, p]);
    if (sql === PRESENT_SQL) return { rows: [{ present }] };
    if (sql === LOADED_SQL) return { rows: [{ loaded }] };
    return { rows };
  } } }; };
  let m = mk(false, false);
  assert.deepEqual(await createUnderpassesRepo(m.db).findOnRoute([1], shape, 15, 30), { loaded: false });
  assert.equal(m.q.length, 1);
  m = mk(true, false);
  assert.deepEqual(await createUnderpassesRepo(m.db).findOnRoute([1], shape, 15, 30), { loaded: false });
  m = mk(true, true, [{ id: 1, osm_road_way_id: '7', osm_bridge_way_id: '9', bridge_kind: 'rail', road_ref: '4', road_class: 'primary', osm_maxheight_text: null, osm_maxheight_m: null, lon: 34.8, lat: 32.1, has_data: false }]);
  const r = await createUnderpassesRepo(m.db).findOnRoute([7, 8], shape, 15, 30);
  assert.equal(m.q[2][0], ON_ROUTE_SQL);
  assert.deepEqual(m.q[2][1][0], ['7', '8']);
  assert.deepEqual([r.loaded, r.rows[0].roadWayId, r.rows[0].point, r.rows[0].hasData], [true, 7, [34.8, 32.1], false]);
});

test('coverage: counts structures with/without TrucksIL data', async () => {
  const calls = [];
  const repo = { findAlongRoute: async (c, m) => { calls.push(m); return c[0][0] === 34.785 ? [{ id: 'b1', status: 'unverified' }] : []; } };
  const c = await computeCoverage({ callTraceAttributes: ok(trace), repo, shape, note: 'n' });
  assert.equal(c.status, 'computed');
  assert.equal(c.structuresOnRoute, 2);
  assert.equal(c.structuresWithData, 1);
  assert.deepEqual(c.noDataSegments.map((s) => [s.type, s.wayId, s.from, s.to]), [['tunnel', 20, [34.8, 32.1], [34.81, 32.11]]]);
  assert.deepEqual(calls, [COVERAGE_BUFFER_M, COVERAGE_BUFFER_M]);
  assert.equal(c.note, 'n');
});

test('coverage: no structures -> computed with zeros (not "safe")', async () => {
  const c = await computeCoverage({ callTraceAttributes: ok({ edges: [{ way_id: 1, begin_shape_index: 0, end_shape_index: 5 }] }), repo: { findAlongRoute: async () => [] }, shape });
  assert.deepEqual([c.status, c.structuresOnRoute, c.structuresWithData, c.noDataSegments], ['computed', 0, 0, []]);
});

test('coverage: failures -> unknown, never computed', async () => {
  const repo = { findAlongRoute: async () => [] };
  for (const call of [
    async () => ({ ok: false, status: 400, json: { error: 'no match' } }),
    async () => { throw new Error('down'); },
    ok({ trip: {} }),
    ok({ edges: [{ bridge: true, begin_shape_index: 0, end_shape_index: 99 }] }),
  ]) {
    const c = await computeCoverage({ callTraceAttributes: call, repo, shape });
    assert.equal(c.status, 'unknown');
    assert.equal(c.structuresOnRoute, null);
  }
  const c = await computeCoverage({ callTraceAttributes: ok(trace), repo: { findAlongRoute: async () => { throw new Error('db'); } }, shape });
  assert.equal(c.status, 'unknown');
});

test('HTTP: /v1/route calls trace_attributes and returns no-data segments', async () => {
  const urls = [];
  const fetch = async (url) => {
    urls.push(url);
    const json = url.endsWith('/trace_attributes') ? trace : { trip: { legs: [{ shape: encodePolyline(shape) }], summary: { length: 3, time: 300 } } };
    return { ok: true, status: 200, json: async () => json };
  };
  const repo = { findAlongRoute: async () => [], exclusionPolygons: async () => [] };
  const server = http.createServer(createHandler({ db: null, repo, valhallaUrl: 'http://v', fetch }));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    const vehicle = { profileName: 't', heightM: 3.8, widthM: 2.5, lengthM: 10, grossWeightT: 18 };
    const r = await globalThis.fetch(`http://127.0.0.1:${server.address().port}/v1/route`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ from: shape[0], to: shape.at(-1), vehicle }) });
    const body = await r.json();
    assert.equal(r.status, 200);
    assert.deepEqual(urls, ['http://v/route', 'http://v/trace_attributes']);
    assert.equal(body.trucksil.coverage.status, 'computed');
    assert.equal(body.trucksil.coverage.structuresOnRoute, 2);
    assert.equal(body.trucksil.coverage.noDataSegments.length, 2);
    assert.equal(body.trucksil.coverage.verifiedOnRoute, 0);
    assert.equal(body.trucksil.coverage.underpassStatus, 'not_loaded');
    assert.equal(body.trucksil.unverifiedCoverage, undefined);
  } finally { await new Promise((r) => server.close(r)); }
});

test('coverage: verified split — OSM candidates count as data but not as verified data', async () => {
  // bridge has only an unverified OSM candidate; tunnel has a verified restriction plus a candidate.
  const repo = { findAlongRoute: async (c) => (c[0][0] === 34.785
    ? [{ id: 'osm-maxheight-way10-crossing1', status: 'unverified' }]
    : [{ id: 'osm-maxheight-way20', status: 'unverified' }, { id: 'mot-1', status: 'verified' }]) };
  const underpassRepo = { findOnRoute: async () => ({ loaded: true, rows: [
    { point: [34.79, 32.09], hasData: true, hasVerifiedData: false },
    { point: [34.80, 32.10], hasData: true, hasVerifiedData: true },
    { point: [34.80, 32.105], hasData: false },
  ] }) };
  const c = await computeCoverage({ callTraceAttributes: ok(trace), repo, underpassRepo, shape });
  assert.deepEqual([c.structuresOnRoute, c.structuresWithData, c.structuresWithVerifiedData], [2, 2, 1]);
  assert.deepEqual([c.underpassesOnRoute, c.underpassesWithData, c.underpassesWithVerifiedData], [3, 2, 1]);
  const u = await computeCoverage({ callTraceAttributes: async () => ({ ok: false, status: 500 }), repo, shape });
  assert.deepEqual([u.status, u.structuresWithVerifiedData, u.underpassesWithVerifiedData], ['unknown', null, null]);
  const n = await computeCoverage({ callTraceAttributes: ok(trace), repo, shape });
  assert.equal(n.underpassesWithVerifiedData, null); // not loaded -> null, never 0
});

test('underpassesRepo: has_verified_data mapped; SQL checks status verified', async () => {
  assert.match(ON_ROUTE_SQL, /r\.status = 'verified'[\s\S]*AS has_verified_data/);
  const db = { query: async (sql) => (sql === PRESENT_SQL ? { rows: [{ present: true }] } : sql === LOADED_SQL ? { rows: [{ loaded: true }] }
    : { rows: [{ id: 1, osm_road_way_id: '7', osm_bridge_way_id: '9', lon: 34.8, lat: 32.1, has_data: true, has_verified_data: true }] }) };
  const r = await createUnderpassesRepo(db).findOnRoute([7], shape, 15, 30);
  assert.deepEqual([r.rows[0].hasData, r.rows[0].hasVerifiedData], [true, true]);
});
