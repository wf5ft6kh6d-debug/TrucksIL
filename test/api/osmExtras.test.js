'use strict';
// OSM extras on the route (ADR-0017): speed limits, lane passthrough, truck POIs. Mocks only.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { createHandler } = require('../../api/src/app');
const { encodePolyline } = require('../../api/src/polyline');
const { speedLimitsFromTrace, laneGuidanceInfo, poiNearRoute } = require('../../api/src/osmExtras');
const { createPoiRepo, parseKinds, NEAR_ROUTE_SQL } = require('../../api/src/poiRepo');
const { traceAttributesRequest } = require('../../api/src/coverage');
const { buildValhallaRouteRequest } = require('../../api/src/lib');

const vehicle = { profileName: 't', heightM: 3.8, widthM: 2.5, lengthM: 10, grossWeightT: 18 };
const shape = [[34.78, 32.08], [34.785, 32.085], [34.79, 32.09], [34.8, 32.1], [34.81, 32.11]];
const U = { source: 'osm', status: 'unverified' };

test('speedLimits: consecutive equal edges merged, unknown edges are gaps, truck speed kept', () => {
  const json = { edges: [
    { begin_shape_index: 0, end_shape_index: 1, speed_limit: 50 },
    { begin_shape_index: 1, end_shape_index: 2, speed_limit: 50 },
    { begin_shape_index: 2, end_shape_index: 3 },                                 // unknown
    { begin_shape_index: 3, end_shape_index: 4, speed_limit: 90, truck_speed: 80 },
    { begin_shape_index: 4, end_shape_index: 5, speed_limit: 90, truck_speed: 80 },
    { begin_shape_index: 5, end_shape_index: 6, speed_limit: 90 },               // truck speed differs
    { begin_shape_index: 6, end_shape_index: 7, speed_limit: 'unlimited', truck_speed: 80 },
    { begin_shape_index: 8, end_shape_index: 9, speed_limit: 50 },               // not contiguous with prev
    { begin_shape_index: 9, end_shape_index: 10, speed_limit: 50 },
  ] };
  assert.deepEqual(speedLimitsFromTrace(json), [
    { fromIndex: 0, toIndex: 2, kmh: 50, ...U },
    { fromIndex: 3, toIndex: 5, kmh: 90, truckKmh: 80, ...U },
    { fromIndex: 5, toIndex: 6, kmh: 90, ...U },
    { fromIndex: 6, toIndex: 7, kmh: null, truckKmh: 80, ...U },
    { fromIndex: 8, toIndex: 10, kmh: 50, ...U },
  ]);
  assert.deepEqual(speedLimitsFromTrace({ edges: [{ begin_shape_index: 0, end_shape_index: 1 }] }), []);
  assert.throws(() => speedLimitsFromTrace({}), /no edges/);
});

test('trace request asks for speed attributes; route request asks for turn lanes', () => {
  const b = traceAttributesRequest(shape);
  assert.ok(b.filters.attributes.includes('edge.speed_limit'));
  assert.ok(b.filters.attributes.includes('edge.truck_speed'));
  assert.equal(buildValhallaRouteRequest({ from: shape[0], to: shape.at(-1), vehicle }).turn_lanes, true);
});

test('laneGuidanceInfo counts maneuvers with lanes', () => {
  const r = { trip: { legs: [{ maneuvers: [{ lanes: [{ directions: 8, active: 8 }] }, {}, { lanes: [] }] }] } };
  assert.deepEqual(laneGuidanceInfo(r), { maneuversWithLanes: 1, where: 'trip.legs[].maneuvers[].lanes', ...U });
  assert.equal(laneGuidanceInfo({}).maneuversWithLanes, 0);
});

const lanes = [{ directions: 8, active: 8, valid: 8 }, { directions: 10, valid: 8 }];
const trace = { shape: encodePolyline(shape), edges: [
  { way_id: 1, begin_shape_index: 0, end_shape_index: 2, speed_limit: 50 },
  { way_id: 2, begin_shape_index: 2, end_shape_index: 4, speed_limit: 90, truck_speed: 80 },
] };

async function routeVia(deps) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    const json = url.endsWith('/trace_attributes') ? trace
      : { trip: { legs: [{ shape: encodePolyline(shape), maneuvers: [{ instruction: 'Turn left.', lanes }] }], summary: { length: 3, time: 300 } } };
    return { ok: true, status: 200, json: async () => json };
  };
  const repo = { findAlongRoute: async () => [], exclusionPolygons: async () => [] };
  const server = http.createServer(createHandler({ db: null, repo, valhallaUrl: 'http://v', fetch, ...deps }));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    const r = await globalThis.fetch(`http://127.0.0.1:${server.address().port}/v1/route`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ from: shape[0], to: shape.at(-1), vehicle }),
    });
    return { status: r.status, body: await r.json(), calls };
  } finally { await new Promise((r) => server.close(r)); }
}

test('HTTP route: speedLimits from the single trace call, lanes passed through, POIs near route', async () => {
  let nearArgs;
  const poi = { id: 'osm-poi-node5-parking', kind: 'parking', name: 'P', position: [34.79, 32.091], status: 'unverified', label: 'OSM, unverified', distanceM: 120 };
  const poiRepo = { nearRoute: async (...a) => { nearArgs = a; return { loaded: true, rows: [poi] }; } };
  const { status, body, calls } = await routeVia({ poiRepo });
  assert.equal(status, 200);
  assert.deepEqual(calls.map((c) => c.url), ['http://v/route', 'http://v/trace_attributes'], 'trace_attributes is memoised');
  assert.equal(calls[0].body.turn_lanes, true);
  assert.deepEqual(body.trip.legs[0].maneuvers[0].lanes, lanes);
  assert.equal(body.trucksil.lanes.maneuversWithLanes, 1);
  assert.deepEqual(body.trucksil.speedLimits, [
    { fromIndex: 0, toIndex: 2, kmh: 50, ...U }, { fromIndex: 2, toIndex: 4, kmh: 90, truckKmh: 80, ...U },
  ]);
  assert.deepEqual(body.trucksil.poiNearRoute, [poi]);
  assert.deepEqual(nearArgs.slice(1), [500, 50]);
  assert.equal(body.trucksil.coverage.status, 'computed');
});

test('HTTP route: no POI table / lookup failure -> poiNearRoute null, route still 200', async () => {
  for (const poiRepo of [null, { nearRoute: async () => ({ loaded: false }) }, { nearRoute: async () => { throw new Error('db'); } }]) {
    const { status, body } = await routeVia({ poiRepo });
    assert.equal(status, 200);
    assert.equal(body.trucksil.poiNearRoute, null);
  }
  assert.equal(await poiNearRoute({ nearRoute: async () => ({ loaded: true, rows: [] }) }, [shape[0]]), null, 'needs a line');
});

test('poiRepo: missing table -> not loaded; rows mapped with OSM label and link', async () => {
  const queries = [];
  const mk = (present, rows) => ({ query: async (sql, p) => { queries.push({ sql, p }); return sql.includes('to_regclass') ? { rows: [{ present }] } : { rows }; } });
  assert.deepEqual(await createPoiRepo(mk(false, [])).nearRoute(shape, 500, 50), { loaded: false });
  const row = { id: 'osm-poi-way30-rest_area', osm_type: 'way', osm_id: '30', kind: 'rest_area', name: null, lon: 35, lat: 31.5, status: 'unverified', distance_m: 99.6 };
  const r = await createPoiRepo(mk(true, [row])).nearRoute(shape, 500, 50);
  assert.deepEqual(r.rows[0], {
    id: 'osm-poi-way30-rest_area', kind: 'rest_area', name: null, position: [35, 31.5], status: 'unverified', label: 'OSM, unverified',
    source: { name: 'OpenStreetMap contributors', license: 'ODbL-1.0', url: 'https://www.openstreetmap.org/way/30' }, distanceM: 100,
  });
  const q = queries.at(-1);
  assert.equal(q.sql, NEAR_ROUTE_SQL);
  assert.deepEqual(q.p.slice(1), [500, 50]);
  assert.equal(JSON.parse(q.p[0]).type, 'LineString');
});

test('parseKinds', () => {
  assert.deepEqual(parseKinds(null).value, ['parking', 'rest_area', 'fuel_hgv']);
  assert.deepEqual(parseKinds('parking, rest_area,parking').value, ['parking', 'rest_area']);
  for (const bad of ['toilets', 'parking,x', ',']) assert.equal(parseKinds(bad).ok, false);
});

async function getPoi(deps, path) {
  const server = http.createServer(createHandler({ valhallaUrl: '', ...deps }));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    const r = await globalThis.fetch(`http://127.0.0.1:${server.address().port}${path}`);
    return { status: r.status, body: await r.json() };
  } finally { await new Promise((r) => server.close(r)); }
}

test('GET /v1/poi: validation, FeatureCollection with OSM unverified label, kinds passed to SQL', async () => {
  let params;
  const db = { query: async (sql, p) => {
    if (sql === 'SELECT 1') return { rows: [] };
    if (sql.includes('to_regclass')) return { rows: [{ present: true }] };
    params = p;
    return { rows: [{ id: 'osm-poi-node8-fuel_hgv', osm_type: 'node', osm_id: 8, kind: 'fuel_hgv', name: 'Fuel', lon: 34.9, lat: 32, status: 'unverified' }] };
  } };
  assert.equal((await getPoi({ db }, '/v1/poi')).status, 400);
  assert.equal((await getPoi({ db }, '/v1/poi?bbox=34.7,31.9,35,32.2&kind=toilets')).status, 400);
  assert.equal((await getPoi({ db: null }, '/v1/poi?bbox=34.7,31.9,35,32.2')).status, 503);
  const r = await getPoi({ db }, '/v1/poi?bbox=34.7,31.9,35,32.2&kind=fuel_hgv');
  assert.equal(r.status, 200);
  assert.deepEqual(params, [34.7, 31.9, 35, 32.2, ['fuel_hgv']]);
  assert.equal(r.body.type, 'FeatureCollection');
  assert.deepEqual(r.body.features[0].geometry, { type: 'Point', coordinates: [34.9, 32] });
  assert.equal(r.body.features[0].properties.label, 'OSM, unverified');
  assert.equal(r.body.features[0].properties.status, 'unverified');
  assert.equal(r.body.trucksil.license, 'ODbL-1.0');
  const missing = await getPoi({ poiRepo: { inBbox: async () => ({ loaded: false }) } }, '/v1/poi?bbox=34.7,31.9,35,32.2');
  assert.deepEqual([missing.status, missing.body.features, missing.body.trucksil.loaded], [200, [], false]);
  const failing = await getPoi({ poiRepo: { inBbox: async () => { throw new Error('x'); } } }, '/v1/poi?bbox=34.7,31.9,35,32.2');
  assert.equal(failing.status, 503);
});
