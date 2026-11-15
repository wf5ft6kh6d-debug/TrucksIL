'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { decodePolyline, encodePolyline, routeShape } = require('../../api/src/polyline');
const { violation, classify, isActiveNow, planRoute, RouteError, COVERAGE_NOTE } = require('../../api/src/routing');
const { createServer } = require('../../api/src/app');
const { createRestrictionsRepo, ALONG_ROUTE_SQL, EXCLUSION_SQL } = require('../../api/src/restrictionsRepo');

// Fictional vehicle and restrictions; not real data.
const truck = { profileName: 'Test semi', heightM: 4.0, widthM: 2.55, lengthM: 16.5, grossWeightT: 40, axleLoadT: 11.5 };
const now = new Date('2026-11-16T10:00:00Z'); // Monday 12:00 Israel time

function row(type, value, extra = {}) {
  const unit = type.startsWith('max_') ? (type.includes('weight') ? 't' : 'm') : 'boolean';
  return {
    id: `r-${type}`, road_segment_id: 'seg', value_source: 'posted_sign', direction: 'both', restriction_type: type,
    value_numeric: unit === 'boolean' ? null : value, value_boolean: unit === 'boolean' ? value : null, unit,
    time_windows: null, status: 'unverified', ...extra,
  };
}

test('polyline: Google reference vector (precision 5) and polyline6', () => {
  assert.deepEqual(decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@', 5), [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]]);
  const pts = [[34.781807, 32.085299], [34.9, 31.9], [35.213711, 31.768319], [-0.000001, -0.5]];
  assert.deepEqual(decodePolyline(encodePolyline(pts)), pts);
  assert.deepEqual(decodePolyline(''), []);
  assert.throws(() => decodePolyline('_p~iF~ps|U_'), /truncated/);
  const shape = routeShape({ trip: { legs: [{ shape: encodePolyline(pts.slice(0, 2)) }, { shape: encodePolyline(pts.slice(2)) }] } });
  assert.deepEqual(shape, pts);
  assert.deepEqual(routeShape({}), []);
});

test('conflict detection: each restriction type', () => {
  const cases = [
    ['max_height', 3.9, 3.8, 4.0],
    ['max_width', 2.5, 2.4, 2.55],
    ['max_length', 15, 12, 16.5],
    ['max_gross_weight', 32, 30, 40],
    ['max_axle_weight', 10, 9, 11.5],
  ];
  for (const [type, lower, alsoLower, equal] of cases) {
    assert.ok(violation(row(type, lower), truck), `${type} ${lower} should conflict`);
    assert.ok(violation(row(type, alsoLower), truck));
    assert.equal(violation(row(type, equal), truck), null, `${type} equal to vehicle is not a violation`);
    assert.equal(violation(row(type, equal + 1), truck), null);
  }
  const { axleLoadT, ...noAxle } = truck;
  assert.match(violation(row('max_axle_weight', 20), noAxle), /not given/);
  assert.ok(violation(row('truck_prohibited', true), truck));
  assert.equal(violation(row('truck_prohibited', false), truck), null);
  assert.equal(violation(row('hazmat_restriction', true), truck), null, 'no hazmat on board');
  assert.ok(violation(row('hazmat_restriction', true), { ...truck, hazmat: { adrClasses: ['3'] } }));
});

test('conflicts are avoided regardless of status; expired is ignored', () => {
  const rows = ['verified', 'unverified', 'disputed', 'expired'].map((status) => row('max_height', 3.5, { id: status, status }));
  const { conflicts, onRoute } = classify(rows, truck, now);
  assert.deepEqual(conflicts.map((c) => c.id), ['verified', 'unverified', 'disputed']);
  assert.deepEqual(onRoute, []);
});

test('time windows', () => {
  assert.equal(isActiveNow(null, now), true);
  assert.equal(isActiveNow([{ days: ['mon'], startTime: '07:00', endTime: '19:00' }], now), true);
  assert.equal(isActiveNow([{ days: ['fri', 'sat'] }], now), false);
  assert.equal(isActiveNow([{ startTime: '13:00', endTime: '15:00' }], now), false);
  assert.equal(isActiveNow([{ startTime: '22:00', endTime: '13:00' }], now), true, 'overnight window');
  assert.equal(isActiveNow([{ validUntil: '2026-11-15' }], now), false);
  assert.equal(isActiveNow([{ validFrom: '2026-11-16' }], now), true);
  const r = row('max_height', 3.5, { time_windows: [{ days: ['sat'] }] });
  assert.equal(classify([r], truck, now).conflicts.length, 0);
  assert.equal(classify([r], truck, now).onRoute.length, 1);
});

// --- re-route loop ---------------------------------------------------------------------------
const shapeA = encodePolyline([[34.78, 32.08], [35.0, 31.9], [35.21, 31.77]]);
const shapeB = encodePolyline([[34.78, 32.08], [34.95, 31.8], [35.21, 31.77]]);
const okTrip = (shape) => ({ ok: true, status: 200, json: { trip: { status: 0, legs: [{ shape }] } } });
const low = row('max_height', 3.5, { id: 'low-bridge', status: 'verified' });
const fine = row('max_height', 4.5, { id: 'tall-bridge', status: 'unverified' });
const ring = [[35, 31.9], [35.0002, 31.9], [35.0002, 31.9002], [35, 31.9]];

function fakeRepo(byShape) {
  const calls = { find: [], excl: [] };
  return {
    calls,
    async findAlongRoute(coords, bufferM) { calls.find.push(bufferM); return byShape(encodePolyline(coords)); },
    async exclusionPolygons(ids, bufferM) { calls.excl.push([ids, bufferM]); return ids.map((id) => ({ id, ring })); },
  };
}

test('re-route: conflict on first route, clean second route', async () => {
  const sent = [];
  const callValhalla = async (b) => { sent.push(b); return okTrip(b.exclude_polygons ? shapeB : shapeA); };
  const repo = fakeRepo((s) => (s === shapeA ? [low, fine] : [fine]));
  const { result, trucksil } = await planRoute({ callValhalla, repo, baseRequest: { costing: 'truck' }, vehicle: truck, now });
  assert.equal(sent.length, 2);
  assert.equal(sent[0].exclude_polygons, undefined);
  assert.deepEqual(sent[1].exclude_polygons, [ring]);
  assert.deepEqual(repo.calls.excl, [[['low-bridge'], 20]]);
  assert.equal(repo.calls.find[0], 50);
  assert.equal(result.trip.legs[0].shape, shapeB);
  assert.deepEqual(trucksil, {
    disclaimer: 'prototype, not for navigation',
    avoided: [{ id: 'low-bridge', restrictionType: 'max_height', value: 3.5, unit: 'm', status: 'verified', valueSource: 'posted_sign', reason: 'heightM 4 > limit 3.5 m' }],
    onRoute: [{ id: 'tall-bridge', restrictionType: 'max_height', value: 4.5, unit: 'm', status: 'unverified', valueSource: 'posted_sign' }],
    coverage: { verifiedOnRoute: 0, unverifiedOnRoute: 1, note: COVERAGE_NOTE },
    unverifiedCoverage: 'unknown',
    reroutes: 1,
  });
});

test('re-route: conflict persists -> 409 with conflicts', async () => {
  let n = 0;
  const callValhalla = async () => { n += 1; return okTrip(shapeA); };
  let excl = 0;
  const repo = {
    async findAlongRoute() { return [{ ...low, id: `low-${n}` }]; }, // a new conflict each time
    async exclusionPolygons(ids) { excl += 1; return ids.map((id) => ({ id, ring })); },
  };
  await assert.rejects(planRoute({ callValhalla, repo, baseRequest: {}, vehicle: truck, now }), (e) => {
    assert.ok(e instanceof RouteError);
    assert.equal(e.status, 409);
    assert.equal(e.body.conflicts[0].id, 'low-4');
    return true;
  });
  assert.equal(n, 4, 'initial route + 3 re-routes');
  assert.equal(excl, 3);
});

test('re-route: Valhalla finds no route once conflicts are excluded -> 422', async () => {
  const callValhalla = async (b) => (b.exclude_polygons
    ? { ok: false, status: 400, json: { error_code: 442, error: 'No path could be found for input' } }
    : okTrip(shapeA));
  const repo = fakeRepo(() => [low]);
  await assert.rejects(planRoute({ callValhalla, repo, baseRequest: {}, vehicle: truck, now }), (e) => {
    assert.equal(e.status, 422);
    assert.deepEqual(e.body.conflicts.map((c) => c.id), ['low-bridge']);
    return true;
  });
});

test('re-route: same conflict after exclusion -> 409, no endless loop', async () => {
  const callValhalla = async () => okTrip(shapeA);
  const repo = fakeRepo(() => [low]);
  await assert.rejects(planRoute({ callValhalla, repo, baseRequest: {}, vehicle: truck, now }), (e) => e.status === 409);
});

// --- HTTP layer --------------------------------------------------------------------------------
async function withServer(deps, fn) {
  const server = createServer(deps);
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try { return await fn(`http://127.0.0.1:${server.address().port}`); } finally { await new Promise((r) => server.close(r)); }
}
const req = { from: [34.78, 32.08], to: [35.21, 31.77], vehicle: truck };
const postRoute = (base) => fetch(`${base}/v1/route`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(req) })
  .then(async (r) => ({ status: r.status, body: await r.json() }));
const fetchJson = (fn) => async (url, init) => {
  const { status, json } = await fn(JSON.parse(init.body));
  return { ok: status < 300, status, json: async () => json };
};

test('HTTP: avoided restriction appears in response; exclude_polygons sent', async () => {
  const bodies = [];
  const fetch = fetchJson(async (b) => { bodies.push(b); return { status: 200, json: okTrip(b.exclude_polygons ? shapeB : shapeA).json }; });
  const repo = fakeRepo((s) => (s === shapeA ? [low] : []));
  await withServer({ db: {}, repo, valhallaUrl: 'http://valhalla:8002', fetch }, async (base) => {
    const r = await postRoute(base);
    assert.equal(r.status, 200);
    assert.deepEqual(r.body.trucksil.avoided.map((a) => a.id), ['low-bridge']);
    assert.deepEqual(r.body.trucksil.coverage, { verifiedOnRoute: 0, unverifiedOnRoute: 0, note: COVERAGE_NOTE });
    assert.equal(r.body.trucksil.unverifiedCoverage, 'unknown');
    assert.equal(bodies[1].costing, 'truck');
    assert.equal(bodies[1].exclude_polygons.length, 1);
  });
});

test('HTTP: persistent conflict -> 409, route not returned', async () => {
  const fetch = fetchJson(async () => ({ status: 200, json: okTrip(shapeA).json }));
  await withServer({ db: {}, repo: fakeRepo(() => [low]), valhallaUrl: 'http://v', fetch }, async (base) => {
    const r = await postRoute(base);
    assert.equal(r.status, 409);
    assert.equal(r.body.trip, undefined);
    assert.equal(r.body.conflicts[0].id, 'low-bridge');
    assert.equal(r.body.trucksil.disclaimer, 'prototype, not for navigation');
  });
});

test('HTTP: repository failure -> 503, no unchecked route', async () => {
  const fetch = fetchJson(async () => ({ status: 200, json: okTrip(shapeA).json }));
  const repo = { async findAlongRoute() { throw new Error('ECONNREFUSED'); }, async exclusionPolygons() { return []; } };
  await withServer({ db: {}, repo, valhallaUrl: 'http://v', fetch }, async (base) => {
    const r = await postRoute(base);
    assert.equal(r.status, 503);
    assert.equal(r.body.trip, undefined);
  });
  await withServer({ db: null, valhallaUrl: 'http://v', fetch }, async (base) => assert.equal((await postRoute(base)).status, 503));
});

test('HTTP: Valhalla response without shape -> 502', async () => {
  const fetch = fetchJson(async () => ({ status: 200, json: { trip: { status: 0 } } }));
  await withServer({ db: {}, repo: fakeRepo(() => []), valhallaUrl: 'http://v', fetch }, async (base) => {
    assert.equal((await postRoute(base)).status, 502);
  });
});

test('repository passes route line and buffers to SQL', async () => {
  const seen = [];
  const db = { async query(sql, params) { seen.push([sql, params]); return { rows: sql === EXCLUSION_SQL ? [{ id: 'a', polygon: { type: 'Polygon', coordinates: [ring] } }] : [] }; } };
  const repo = createRestrictionsRepo(db);
  assert.deepEqual(await repo.findAlongRoute([], 50), []);
  await repo.findAlongRoute([[34.78, 32.08], [35.21, 31.77]], 50);
  assert.equal(seen[0][0], ALONG_ROUTE_SQL);
  assert.deepEqual(JSON.parse(seen[0][1][0]), { type: 'LineString', coordinates: [[34.78, 32.08], [35.21, 31.77]] });
  assert.equal(seen[0][1][1], 50);
  assert.deepEqual(await repo.exclusionPolygons(['a'], 20), [{ id: 'a', ring }]);
  assert.deepEqual(seen[1][1], [['a'], 20]);
});

test('classify: GeoJSON geometry is passed through to avoided/onRoute items (for map markers)', () => {
  const geometry = { type: 'Point', coordinates: [35.0001, 31.9001] };
  const { conflicts, onRoute } = classify([
    { ...low, geometry },
    { ...fine, geometry: { type: 'LineString', coordinates: [[35, 31.9], [35.001, 31.9]] } },
    { ...fine, id: 'no-geom' },
  ], truck, now);
  assert.deepEqual(conflicts[0].geometry, geometry);
  assert.equal(onRoute[0].geometry.type, 'LineString');
  assert.equal('geometry' in onRoute[1], false);
});

test('ALONG_ROUTE_SQL selects geometry as GeoJSON', () => {
  assert.match(ALONG_ROUTE_SQL, /ST_AsGeoJSON\(r\.geometry, 7\)::json AS geometry/);
});
