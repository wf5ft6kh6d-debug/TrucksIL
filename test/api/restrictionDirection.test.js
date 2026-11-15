'use strict';
// Restriction direction and thin exclusion polygons (ADR-0011). Fictional geometry, mock repo/Valhalla.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { encodePolyline } = require('../../api/src/polyline');
const { classify, planRoute } = require('../../api/src/routing');
const G = require('../../api/src/routeGeometry');

const truck = { profileName: 'Test semi', heightM: 4.0, widthM: 2.55, lengthM: 16.5, grossWeightT: 40, axleLoadT: 11.5 };
const now = new Date('2026-11-16T10:00:00Z');

// Route going east along latitude 31.9 (~945 m per 0.01 deg of longitude there).
const east = [[34.99, 31.9], [35.0, 31.9], [35.01, 31.9]];
const line = (coords) => ({ type: 'LineString', coordinates: coords });
const alongEast = line([[34.9998, 31.9], [35.0002, 31.9]]); // ~38 m, digitized eastwards
const alongWest = line([[35.0002, 31.9], [34.9998, 31.9]]);
const crossing = line([[35.0, 31.8998], [35.0, 31.9002]]); // north-south road crossing the route

function row(id, direction, geometry, extra = {}) {
  return {
    id, road_segment_id: 'seg', value_source: 'posted_sign', direction, restriction_type: 'max_height',
    value_numeric: 3.5, value_boolean: null, unit: 'm', time_windows: null, status: 'unverified', geometry, ...extra,
  };
}

test('direction: forward / backward / both against travel direction', () => {
  const applies = (dir, g, shape = east) => G.directionApplies(row('x', dir, g), shape);
  assert.equal(applies('forward', alongEast), true, 'forward, traversed along digitization');
  assert.equal(applies('forward', alongWest), false, 'forward, traversed against digitization');
  assert.equal(applies('backward', alongWest), true);
  assert.equal(applies('backward', alongEast), false);
  assert.equal(applies('both', alongEast), true);
  assert.equal(applies('both', alongWest), true);
  assert.equal(applies(undefined, alongWest), true, 'missing direction = both');
  // Same restriction, route driven westwards.
  const west = [...east].reverse();
  assert.equal(applies('forward', alongEast, west), false);
  assert.equal(applies('backward', alongEast, west), true);
  // 45 deg off still counts as the same direction; a crossing road (90 deg) is neither.
  assert.equal(applies('forward', line([[34.9998, 31.8998], [35.0002, 31.9002]])), true);
  assert.equal(applies('forward', crossing), false);
  assert.equal(applies('backward', crossing), false);
  assert.equal(applies('both', crossing), true);
});

test('direction: undeterminable -> applies (conservative)', () => {
  const applies = (dir, g, shape = east) => G.directionApplies(row('x', dir, g), shape);
  assert.equal(applies('forward', { type: 'Point', coordinates: [35.0, 31.9] }), true, 'points have no direction');
  assert.equal(applies('backward', line([[35.0, 31.9], [35.0, 31.9]])), true, 'zero-length line');
  assert.equal(applies('forward', line([[35.0, 31.9]])), true, 'single-vertex line');
  assert.equal(applies('forward', alongWest, [[35.0, 31.9]]), true, 'one-point route');
  assert.equal(applies('forward', alongWest, [[35.0, 31.9], [35.00002, 31.9]]), true, 'route ~2 m long');
  assert.equal(applies('forward', null), true, 'no geometry');
  assert.equal(applies('forward', { type: 'Polygon', coordinates: [] }), true);
  assert.equal(G.travelAngle(east, alongWest) > 170, true);
});

test('classify(shape): drops restrictions for the other direction only', () => {
  const rows = [row('fwd-along', 'forward', alongEast), row('fwd-against', 'forward', alongWest), row('pt', 'forward', { type: 'Point', coordinates: [35, 31.9] })];
  assert.deepEqual(classify(rows, truck, now, east).conflicts.map((c) => c.id), ['fwd-along', 'pt']);
  assert.deepEqual(classify(rows, truck, now).conflicts.map((c) => c.id), ['fwd-along', 'fwd-against', 'pt'], 'no shape -> unchanged');
});

// --- thin exclusion geometry -------------------------------------------------------------------
function inside([x, y], ring) {
  let c = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}
const inAny = (p, rings) => rings.some((r) => inside(p, r));
const dLatM = (m) => m / 111195; // metres north -> degrees
const dLonM = (m, lat = 31.9) => m / (111195 * Math.cos((lat * Math.PI) / 180));

test('thin exclusion: rectangle around the route edge, not the crossing road', () => {
  const rings = G.thinExclusionRings(east, { type: 'Point', coordinates: [35.0, 31.9] });
  assert.ok(rings && rings.length >= 1);
  for (const r of rings) assert.deepEqual(r[0], r[r.length - 1], 'closed ring');
  const lats = rings.flat().map((p) => p[1]);
  const lons = rings.flat().map((p) => p[0]);
  // Half-width 7 m, along +-30 m (+7 m end caps).
  assert.ok(Math.abs(Math.max(...lats) - (31.9 + dLatM(7))) < dLatM(0.2));
  assert.ok(Math.abs(Math.min(...lats) - (31.9 - dLatM(7))) < dLatM(0.2));
  assert.ok(Math.abs(Math.max(...lons) - (35.0 + dLonM(37))) < dLonM(0.5));
  assert.ok(Math.abs(Math.min(...lons) - (35.0 - dLonM(37))) < dLonM(0.5));
  assert.ok(inAny([35.0 + dLonM(25), 31.9], rings), 'route 25 m on is excluded');
  assert.ok(!inAny([35.0 + dLonM(60), 31.9], rings), 'route 60 m on is not');
  assert.ok(!inAny([35.0, 31.9 + dLatM(12)], rings), 'crossing road 12 m off the route edge is not excluded');
  assert.ok(!inAny([35.0, 31.9 - dLatM(15)], rings), 'parallel carriageway 15 m away is not excluded');
  // The old 20 m polygon would have covered both of those.
});

test('thin exclusion: follows a bend; restriction off the route is located by its closest point', () => {
  const bend = [[34.999, 31.9], [35.0, 31.9], [35.0, 31.901]]; // east then north
  const rings = G.thinExclusionRings(bend, { type: 'Point', coordinates: [35.0 + dLonM(10), 31.9 + dLatM(10)] });
  assert.equal(rings.length, 2, 'one rectangle per leg');
  assert.ok(inAny([35.0 - dLonM(20), 31.9], rings));
  assert.ok(inAny([35.0, 31.9 + dLatM(20)], rings));
  assert.ok(!inAny([35.0 - dLonM(20), 31.9 + dLatM(20)], rings), 'inside of the bend away from both legs');
  assert.equal(G.thinExclusionRings(east, null), null);
  assert.equal(G.thinExclusionRings([[35, 31.9]], { type: 'Point', coordinates: [35, 31.9] }), null, 'zero-length sub-line');
});

// --- planRoute: direction + escalation ----------------------------------------------------------
const shapeA = encodePolyline(east);
const shapeB = encodePolyline([[34.99, 31.9], [35.0, 31.95], [35.01, 31.9]]);
const ok = (shape) => ({ ok: true, status: 200, json: { trip: { status: 0, legs: [{ shape }] } } });
const wideRing = [[35, 31.9], [35.0002, 31.9], [35.0002, 31.9002], [35, 31.9]];

function repoFor(rowsByShape) {
  const calls = { excl: [] };
  return {
    calls,
    async findAlongRoute(coords) { return rowsByShape(encodePolyline(coords)); },
    async exclusionPolygons(ids, bufferM) { calls.excl.push([ids, bufferM]); return ids.map((id) => ({ id, ring: wideRing })); },
  };
}

test('planRoute: forward restriction traversed the other way -> no reroute, not reported', async () => {
  const sent = [];
  const repo = repoFor(() => [row('oneway', 'forward', alongWest)]);
  const { trucksil } = await planRoute({ callValhalla: async (b) => { sent.push(b); return ok(shapeA); }, repo, baseRequest: {}, vehicle: truck, now });
  assert.equal(sent.length, 1);
  assert.equal(trucksil.reroutes, 0);
  assert.deepEqual(trucksil.avoided, []);
  assert.deepEqual(trucksil.onRoute, []);
});

test('planRoute: thin exclusion first; works -> repo polygon never requested', async () => {
  const sent = [];
  const repo = repoFor((s) => (s === shapeA ? [row('oneway', 'forward', alongEast)] : []));
  const { trucksil } = await planRoute({ callValhalla: async (b) => { sent.push(b); return ok(b.exclude_polygons ? shapeB : shapeA); }, repo, baseRequest: {}, vehicle: truck, now });
  assert.equal(trucksil.reroutes, 1);
  assert.deepEqual(trucksil.avoided.map((a) => a.id), ['oneway']);
  assert.deepEqual(repo.calls.excl, []);
  assert.deepEqual(sent[1].exclude_polygons, G.thinExclusionRings(east, alongEast));
});

test('planRoute: escalation thin -> 20 m polygon -> success', async () => {
  const sent = [];
  // Valhalla keeps the same route under the thin exclusion; only the wide polygon moves it.
  const callValhalla = async (b) => { sent.push(b); return ok(b.exclude_polygons && b.exclude_polygons.includes(wideRing) ? shapeB : shapeA); };
  const repo = repoFor((s) => (s === shapeA ? [row('bridge', 'both', { type: 'Point', coordinates: [35, 31.9] })] : []));
  const { trucksil } = await planRoute({ callValhalla, repo, baseRequest: {}, vehicle: truck, now });
  assert.equal(sent.length, 3);
  assert.equal(trucksil.reroutes, 2);
  assert.deepEqual(repo.calls.excl, [[['bridge'], 20]]);
  const thin = G.thinExclusionRings(east, { type: 'Point', coordinates: [35, 31.9] });
  assert.deepEqual(sent[1].exclude_polygons, thin);
  assert.deepEqual(sent[2].exclude_polygons, [...thin, wideRing], 'wide polygon added to the thin rings');
});

test('planRoute: escalation thin -> 20 m -> 409 when nothing helps', async () => {
  const sent = [];
  const repo = repoFor(() => [row('bridge', 'both', { type: 'Point', coordinates: [35, 31.9] })]);
  await assert.rejects(planRoute({ callValhalla: async (b) => { sent.push(b); return ok(shapeA); }, repo, baseRequest: {}, vehicle: truck, now }), (e) => {
    assert.equal(e.status, 409);
    assert.match(e.body.error, /exclusion had no effect/);
    assert.deepEqual(e.body.conflicts.map((c) => c.id), ['bridge']);
    return true;
  });
  assert.equal(sent.length, 3, 'plain, thin, wide');
  assert.deepEqual(repo.calls.excl, [[['bridge'], 20]]);
});
