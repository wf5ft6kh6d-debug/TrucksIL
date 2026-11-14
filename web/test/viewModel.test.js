import test from 'node:test';
import assert from 'node:assert/strict';
import { routeViewModel, restrictionItem, markerPosition, markersGeoJSON } from '../src/viewModel.js';
import { encodePolyline } from '../../api/src/polyline.mjs';
import { requestRoute } from '../src/api.js';

const line = [[34.78, 32.08], [34.8, 32.1], [34.82, 32.12]];
const low = { id: 'low-bridge', restrictionType: 'max_height', value: 3.5, unit: 'm', status: 'verified', valueSource: 'posted_sign', reason: 'heightM 4 > limit 3.5 m', geometry: { type: 'Point', coordinates: [34.79, 32.09] } };
const tall = { id: 'tall-bridge', restrictionType: 'max_height', value: 4.55, unit: 'm', status: 'unverified', valueSource: 'posted_sign', geometry: { type: 'LineString', coordinates: [[34.8, 32.1], [34.801, 32.1], [34.802, 32.1]] } };
const ban = { id: 'ban', restrictionType: 'truck_prohibited', value: true, unit: 'boolean', status: 'unverified', valueSource: 'regulation' };
const ok200 = {
  trip: { legs: [{ shape: encodePolyline(line) }], summary: { length: 4.26, time: 600 } },
  trucksil: { disclaimer: 'prototype, not for navigation', avoided: [low], onRoute: [tall, ban], coverage: { verifiedOnRoute: 0, unverifiedOnRoute: 2, note: 'Absence ...' }, unverifiedCoverage: 'unknown', reroutes: 1 },
};

test('vm 200: decodes polyline6 route, maps avoided/onRoute/coverage/summary', () => {
  const vm = routeViewModel(200, ok200);
  assert.equal(vm.kind, 'route');
  assert.deepEqual(vm.route, line);
  assert.deepEqual(vm.summary, { km: '4.3', min: 10, reroutes: 1 });
  assert.deepEqual(vm.coverage, { verified: 0, unverified: 2, note: 'Absence ...' });
  assert.equal(vm.error, null);
  assert.deepEqual(vm.avoided.map((x) => x.id), ['low-bridge']);
  assert.deepEqual(vm.onRoute.map((x) => x.id), ['tall-bridge', 'ban']);
});

test('vm item: value exactly as returned with unit, source label key, status badge key', () => {
  const a = restrictionItem(low, 'avoided');
  assert.equal(a.valueText, '3.5 m');
  assert.equal(a.valueSourceKey, 'source.posted_sign');
  assert.equal(a.statusKey, 'status.verified');
  assert.equal(a.reason, 'heightM 4 > limit 3.5 m');
  assert.deepEqual(a.position, [34.79, 32.09]);
  assert.equal(restrictionItem(tall, 'onRoute').valueText, '4.55 m'); // no rounding
  const b = restrictionItem(ban, 'onRoute');
  assert.equal(b.valueText, null);
  assert.equal(b.valueBoolKey, 'value.true');
  assert.equal(b.position, null);
  assert.equal(restrictionItem({ ...low, valueSource: null }, 'x').valueSourceKey, 'source.unknown');
});

test('vm markers: positions for Point/LineString/Polygon; items without geometry skipped', () => {
  assert.deepEqual(markerPosition(tall.geometry), [34.801, 32.1]);
  assert.deepEqual(markerPosition({ type: 'Polygon', coordinates: [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]] }), [1, 1]);
  assert.equal(markerPosition({ type: 'Point', coordinates: ['x', 1] }), null);
  assert.equal(markerPosition(null), null);
  const fc = markersGeoJSON(routeViewModel(200, ok200));
  assert.deepEqual(fc.features.map((f) => [f.properties.id, f.properties.kind]), [['low-bridge', 'avoided'], ['tall-bridge', 'onRoute']]);
});

test('vm 200 without decodable shape -> error, no route', () => {
  for (const body of [{ trip: { legs: [] } }, { trip: { legs: [{ shape: '\u0001' }] } }, null]) {
    const vm = routeViewModel(200, body);
    assert.equal(vm.kind, 'error');
    assert.equal(vm.route, null);
  }
});

for (const status of [409, 422]) {
  test(`vm ${status}: conflicts shown, NEVER a route even if the body carries one`, () => {
    const vm = routeViewModel(status, { error: 'no route', conflicts: [low], avoided: [tall], trip: ok200.trip });
    assert.equal(vm.kind, 'conflict');
    assert.equal(vm.route, null);
    assert.equal(vm.error.key, `err.${status}`);
    assert.equal(vm.error.message, 'no route');
    assert.deepEqual(vm.conflicts.map((x) => [x.id, x.kind]), [['low-bridge', 'conflict']]);
    assert.deepEqual(vm.avoided.map((x) => x.id), ['tall-bridge']);
  });
}

test('vm 400/502/503/network/other: error with message and details, no route', () => {
  const v400 = routeViewModel(400, { error: 'invalid request', details: ['vehicle/heightM must be <= 6'] });
  assert.deepEqual([v400.kind, v400.route, v400.error.key, v400.error.details], ['error', null, 'err.400', ['vehicle/heightM must be <= 6']]);
  assert.equal(routeViewModel(503, { error: 'routing disabled' }).error.key, 'err.503');
  assert.equal(routeViewModel(502, {}).error.key, 'err.502');
  assert.equal(routeViewModel(null, null).error.key, 'err.network');
  const other = routeViewModel(500, ok200);
  assert.deepEqual([other.error.key, other.error.status, other.route], ['err.other', 500, null]);
});

test('api: requestRoute posts JSON to same-origin /api and handles network failure', async () => {
  let seen;
  const r = await requestRoute({ from: [1, 2], to: [3, 4], vehicle: { a: 1 } }, async (url, init) => { seen = [url, init]; return { status: 422, json: async () => ({ error: 'x' }) }; });
  assert.equal(seen[0], '/api/v1/route');
  assert.equal(seen[1].method, 'POST');
  assert.deepEqual(JSON.parse(seen[1].body), { from: [1, 2], to: [3, 4], vehicle: { a: 1 } });
  assert.deepEqual(r, { status: 422, body: { error: 'x' } });
  assert.deepEqual(await requestRoute({}, async () => { throw new TypeError('offline'); }), { status: null, body: null });
  assert.deepEqual(await requestRoute({}, async () => ({ status: 502, json: async () => { throw new Error('html'); } })), { status: 502, body: null });
});
