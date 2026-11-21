'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createServer } = require('../../api/src/app');
const { encodePolyline } = require('../../api/src/polyline');
const trip = { status: 0, legs: [{ shape: encodePolyline([[34.78, 32.08], [35.21, 31.77]]) }] };

const truck = { profileName: 'Test rigid', heightM: 3.8, widthM: 2.5, lengthM: 10, grossWeightT: 18 };
const okDb = { query: async (sql) => (sql === 'SELECT 1' ? { rows: [{ '?column?': 1 }] } : { rows: [] }) };
const downDb = { query: async () => { throw new Error('ECONNREFUSED'); } };

function jsonResponse(status, obj) {
  return { ok: status >= 200 && status < 300, status, json: async () => obj };
}

async function withServer(deps, fn) {
  const server = createServer(deps);
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try { return await fn(base); } finally { await new Promise((r) => server.close(r)); }
}

async function call(base, path, init) {
  const r = await fetch(base + path, init);
  return { status: r.status, body: await r.json() };
}
const post = (body) => ({ method: 'POST', headers: { 'content-type': 'application/json' }, body: typeof body === 'string' ? body : JSON.stringify(body) });

test('health: db ok, valhalla disabled', async () => {
  await withServer({ db: okDb, valhallaUrl: '' }, async (base) => {
    assert.deepEqual(await call(base, '/health'), { status: 200, body: { status: 'ok', db: 'ok', valhalla: 'disabled' } });
  });
});

test('health: db down, valhalla ok', async () => {
  const fakeFetch = async (url) => { assert.equal(url, 'http://valhalla:8002/status'); return jsonResponse(200, {}); };
  await withServer({ db: downDb, valhallaUrl: 'http://valhalla:8002/', fetch: fakeFetch }, async (base) => {
    assert.deepEqual(await call(base, '/health'), { status: 503, body: { status: 'degraded', db: 'down', valhalla: 'ok' } });
  });
});

test('health: valhalla unreachable', async () => {
  const fakeFetch = async () => { throw new TypeError('fetch failed'); };
  await withServer({ db: okDb, valhallaUrl: 'http://valhalla:8002', fetch: fakeFetch }, async (base) => {
    const r = await call(base, '/health');
    assert.equal(r.body.valhalla, 'down');
    assert.equal(r.status, 503);
  });
});

test('restrictions: bad bbox -> 400, empty table -> empty FeatureCollection', async () => {
  let params;
  const db = { query: async (_sql, p) => { params = p; return { rows: [] }; } };
  await withServer({ db }, async (base) => {
    assert.equal((await call(base, '/v1/restrictions')).status, 400);
    assert.equal((await call(base, '/v1/restrictions?bbox=1,2,3')).status, 400);
    const r = await call(base, '/v1/restrictions?bbox=34.7,32.0,34.9,32.2');
    assert.deepEqual(r, { status: 200, body: { type: 'FeatureCollection', features: [] } });
    assert.deepEqual(params, [34.7, 32.0, 34.9, 32.2]);
  });
});

test('restrictions: rows become GeoJSON features', async () => {
  const row = {
    id: 'r1', road_segment_id: 'seg1', geometry: { type: 'Point', coordinates: [34.8, 32.1] }, value_source: 'posted_sign',
    direction: 'both', restriction_type: 'max_height', value_numeric: 4.2, value_boolean: null, unit: 'm', time_windows: null,
    status: 'unverified', source: { name: 'test', reference: 'x' }, observed_at: new Date('2026-01-01T00:00:00Z'),
    verified_by: null, verified_at: null, review_due_at: null,
  };
  await withServer({ db: { query: async () => ({ rows: [row] }) } }, async (base) => {
    const { body } = await call(base, '/v1/restrictions?bbox=34,31,35,33');
    assert.equal(body.features.length, 1);
    assert.deepEqual(body.features[0].properties, {
      id: 'r1', roadSegmentId: 'seg1', valueSource: 'posted_sign', direction: 'both', restrictionType: 'max_height',
      value: 4.2, unit: 'm', status: 'unverified', source: { name: 'test', reference: 'x' }, observedAt: '2026-01-01T00:00:00.000Z',
    });
  });
});

test('route: invalid vehicle -> 400', async () => {
  await withServer({ db: okDb, valhallaUrl: 'http://v' }, async (base) => {
    const r = await call(base, '/v1/route', post({ from: [34.78, 32.08], to: [35.21, 31.77], vehicle: { ...truck, heightM: 'tall' } }));
    assert.equal(r.status, 400);
    assert.ok(r.body.details.some((d) => d.startsWith('vehicle/heightM')));
    assert.equal((await call(base, '/v1/route', post('{not json'))).status, 400);
  });
});

test('route: valhalla disabled -> 503', async () => {
  await withServer({ db: okDb, valhallaUrl: '' }, async (base) => {
    const r = await call(base, '/v1/route', post({ from: [34.78, 32.08], to: [35.21, 31.77], vehicle: truck }));
    assert.equal(r.status, 503);
    assert.match(r.body.error, /routing disabled/);
  });
});

test('route: valhalla unreachable -> 503', async () => {
  const fakeFetch = async () => { throw new TypeError('fetch failed'); };
  await withServer({ db: okDb, valhallaUrl: 'http://valhalla:8002', fetch: fakeFetch }, async (base) => {
    const r = await call(base, '/v1/route', post({ from: [34.78, 32.08], to: [35.21, 31.77], vehicle: truck }));
    assert.equal(r.status, 503);
    assert.match(r.body.error, /unreachable/);
  });
});

test('route: proxies to valhalla with truck costing and adds trucksil block', async () => {
  let sent;
  const fakeFetch = async (url, init) => { if (!sent) sent = { url, body: JSON.parse(init.body) }; return jsonResponse(200, { trip }); };
  await withServer({ db: okDb, valhallaUrl: 'http://valhalla:8002', fetch: fakeFetch }, async (base) => {
    const r = await call(base, '/v1/route', post({ from: [34.78, 32.08], to: [35.21, 31.77], vehicle: truck }));
    assert.equal(r.status, 200);
    assert.deepEqual(r.body.trip, trip);
    assert.equal(r.body.trucksil.disclaimer, 'prototype, not for navigation');
    assert.equal(r.body.trucksil.coverage.status, 'unknown'); // mock has no trace_attributes edges
    assert.deepEqual(r.body.trucksil.avoided, []);
    assert.equal(sent.url, 'http://valhalla:8002/route');
    assert.equal(sent.body.costing, 'truck');
    assert.deepEqual(sent.body.costing_options.truck, { height: 3.8, width: 2.5, length: 10, weight: 18, hgv_no_access_penalty: 43200 });
  });
});

test('route: valhalla 400 (no route) is passed through', async () => {
  const fakeFetch = async () => jsonResponse(400, { error_code: 442, error: 'No path could be found for input' });
  await withServer({ db: okDb, valhallaUrl: 'http://v', fetch: fakeFetch }, async (base) => {
    const r = await call(base, '/v1/route', post({ from: [34.78, 32.08], to: [35.21, 31.77], vehicle: truck }));
    assert.equal(r.status, 400);
    assert.equal(r.body.valhalla.error_code, 442);
  });
});

test('unknown path -> 404, wrong method -> 405', async () => {
  await withServer({ db: okDb }, async (base) => {
    assert.equal((await call(base, '/nope')).status, 404);
    assert.equal((await call(base, '/v1/route')).status, 405);
  });
});
