'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { computeCoverage, structuresFromTrace, traceAttributesRequest, COVERAGE_BUFFER_M } = require('../../api/src/coverage');
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
  assert.deepEqual(s.map((x) => [x.type, x.wayId, x.coords.length]), [['bridge', 10, 3], ['tunnel', 20, 2]]);
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
    assert.equal(body.trucksil.unverifiedCoverage, undefined);
  } finally { await new Promise((r) => server.close(r)); }
});
