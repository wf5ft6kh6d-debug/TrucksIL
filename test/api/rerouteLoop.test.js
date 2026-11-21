'use strict';
// Re-route loop at scale (ADR-0016): progressive reveal, pre-exclusion, perimeter/count caps,
// way match, diagnostics. Mock Valhalla + in-memory repo; all restrictions are FICTIONAL.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { encodePolyline } = require('../../api/src/polyline');
const {
  planRoute, RouteError, ringPerimeterM, gateWayId, splitByWay, preExclusionRings, routingConfig,
} = require('../../api/src/routing');
const { distanceToShapeM } = require('../scenarios/lib');

const truck = { profileName: 'Test semi', heightM: 4.0, widthM: 2.55, lengthM: 16.5, grossWeightT: 40, axleLoadT: 11.5 };
const now = new Date('2026-11-16T10:00:00Z');

// Candidate route i bulges north by i*0.003 deg (~330 m) in the middle; conflict i sits on its middle vertex.
const N_ROUTES = 7;
const routeCoords = (i) => Array.from({ length: 21 }, (_, k) => {
  const t = k / 20;
  return [+(34.8 + 0.2 * t).toFixed(6), +(32.0 + i * 0.003 * Math.sin(Math.PI * t)).toFixed(6)];
});
const conflictPoint = (i) => routeCoords(i)[10];

function inRing([x, y], ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function heightRow(i, extra = {}) {
  return {
    id: `c${i}`, road_segment_id: 'seg', value_source: 'posted_sign', direction: 'both', restriction_type: 'max_height',
    value_numeric: 3.5, value_boolean: null, value_text: null, unit: 'm', time_windows: null, status: 'unverified',
    geometry: { type: 'Point', coordinates: conflictPoint(i) },
    source: { name: 'e2e-fictional', url: `https://example.invalid/${i}` },
    ...extra,
  };
}

/** Valhalla mock: first candidate route whose conflict point is not excluded; route N_ROUTES is clean. */
function mockValhalla({ n = N_ROUTES - 1, failWhen = null } = {}) {
  const calls = [];
  const fn = async (body) => {
    calls.push(body);
    const rings = body.exclude_polygons || [];
    if (failWhen) { const f = failWhen(rings); if (f) return f; }
    let i = 0;
    while (i < n && rings.some((r) => inRing(conflictPoint(i), r))) i += 1;
    return { ok: true, status: 200, json: { trip: { status: 0, legs: [{ shape: encodePolyline(routeCoords(i)) }] } } };
  };
  fn.calls = calls;
  return fn;
}

function memRepo(rows) {
  const calls = [];
  return {
    calls,
    async findAlongRoute(coords, bufferM) {
      calls.push(bufferM);
      const pts = (g) => (g.type === 'Point' ? [g.coordinates] : g.coordinates);
      return rows.filter((r) => pts(r.geometry).some((p) => distanceToShapeM(p, coords) <= bufferM));
    },
    async exclusionPolygons(ids, bufferM) {
      return rows.filter((r) => ids.includes(r.id)).map((r) => {
        const [lon, lat] = r.geometry.coordinates;
        const d = bufferM / 111320;
        const e = d / Math.cos((lat * Math.PI) / 180);
        return { id: r.id, ring: [[lon - e, lat - d], [lon + e, lat - d], [lon + e, lat + d], [lon - e, lat + d], [lon - e, lat - d]] };
      });
    },
  };
}

const rows6 = Array.from({ length: N_ROUTES - 1 }, (_, i) => heightRow(i));

test('defaults: MAX_REROUTES 8, pre-exclusion on, Valhalla perimeter budget 95 % of 10 km', () => {
  const c = routingConfig();
  assert.equal(c.maxReroutes, 8);
  assert.equal(c.preExclude, true);
  assert.equal(c.maxPreExclusions, 200);
  assert.equal(c.perimeterBudgetM, 9500);
});

test('progressive reveal: 6 conflicts found one per route resolve within the new limit', async () => {
  const v = mockValhalla();
  const { trucksil } = await planRoute({ callValhalla: v, repo: memRepo(rows6), baseRequest: {}, vehicle: truck, now, preExclude: false });
  assert.equal(trucksil.reroutes, 6);
  assert.deepEqual(trucksil.avoided.map((a) => a.id), ['c0', 'c1', 'c2', 'c3', 'c4', 'c5']);
  // exclusions accumulate: the last request still excludes the first conflict
  assert.ok(v.calls.at(-1).exclude_polygons.some((r) => inRing(conflictPoint(0), r)));
});

test('progressive reveal with the old limit of 3 -> 409 (safety unchanged: no route through a conflict)', async () => {
  await assert.rejects(
    planRoute({ callValhalla: mockValhalla(), repo: memRepo(rows6), baseRequest: {}, vehicle: truck, now, preExclude: false, maxReroutes: 3 }),
    (e) => e instanceof RouteError && e.status === 409 && e.body.conflicts[0].id === 'c3',
  );
});

test('pre-exclusion: corridor conflicts excluded up front -> one re-route', async () => {
  const repo = memRepo(rows6);
  const v = mockValhalla();
  const { trucksil } = await planRoute({ callValhalla: v, repo, baseRequest: {}, vehicle: truck, now });
  assert.equal(trucksil.reroutes, 1);
  assert.deepEqual(trucksil.avoided.map((a) => a.id), ['c0'], 'only conflicts actually met are reported as avoided');
  assert.ok(repo.calls.includes(3000), 'corridor query at 3 km');
  assert.equal(v.calls.length, 2);
});

test('pre-exclusion is soft: if it makes Valhalla fail, it is dropped and the reactive loop continues', async () => {
  // The first request carrying the pre-exclusion of c1 "has no path" -> pre-exclusions must be dropped.
  let failed = 0;
  const v = mockValhalla({ failWhen: (rings) => (!failed && rings.some((r) => inRing(conflictPoint(1), r)) ? (failed += 1, { ok: false, status: 400, json: { error_code: 442, error: 'No path could be found for input' } }) : null) });
  const { trucksil } = await planRoute({ callValhalla: v, repo: memRepo(rows6.slice(0, 2)), baseRequest: {}, vehicle: truck, now, debug: true });
  assert.deepEqual(trucksil.debug.preExclusionDropped.ids, ['c1']);
  assert.deepEqual(trucksil.avoided.map((a) => a.id), ['c0', 'c1']);
});

test('cap: number of pre-exclusions and perimeter budget, nearest first', async () => {
  const repo = memRepo(rows6);
  const v = mockValhalla();
  await planRoute({ callValhalla: v, repo, baseRequest: {}, vehicle: truck, now, maxPreExclusions: 2 }).catch(() => {});
  const second = v.calls[1].exclude_polygons;
  assert.ok(inRing(conflictPoint(1), second.find((r) => inRing(conflictPoint(1), r))), 'nearest (c1) pre-excluded');
  assert.ok(!second.some((r) => inRing(conflictPoint(3), r)), 'c3 beyond the count cap');
  // perimeter: every request stays within the budget
  const v2 = mockValhalla();
  const budget = 400;
  await planRoute({ callValhalla: v2, repo: memRepo(rows6), baseRequest: {}, vehicle: truck, now, perimeterBudgetM: budget }).catch(() => {});
  for (const b of v2.calls) {
    const p = (b.exclude_polygons || []).reduce((s, r) => s + ringPerimeterM(r), 0);
    assert.ok(p <= budget, `perimeter ${p} <= ${budget}`);
  }
});

test('mandatory exclusions over the perimeter budget -> 409, never an unchecked route', async () => {
  await assert.rejects(
    planRoute({ callValhalla: mockValhalla(), repo: memRepo(rows6), baseRequest: {}, vehicle: truck, now, perimeterBudgetM: 30, preExclude: false }),
    (e) => e.status === 409 && /perimeter/.test(e.body.error),
  );
});

test('Valhalla error 167 (perimeter exceeded) -> 409 with explicit message, not 422', async () => {
  const v = mockValhalla({ failWhen: (rings) => (rings.length ? { ok: false, status: 400, json: { error_code: 167, error: 'Exceeded maximum circumference for exclude_polygons' } } : null) });
  await assert.rejects(
    planRoute({ callValhalla: v, repo: memRepo(rows6), baseRequest: {}, vehicle: truck, now, preExclude: false }),
    (e) => e.status === 409 && /perimeter limit/.test(e.body.error),
  );
});

test('422 names the exclusions added in the last step as blocking candidates', async () => {
  const v = mockValhalla({ failWhen: (rings) => (rings.some((r) => inRing(conflictPoint(1), r)) ? { ok: false, status: 400, json: { error_code: 442 } } : null) });
  await assert.rejects(
    planRoute({ callValhalla: v, repo: memRepo(rows6), baseRequest: {}, vehicle: truck, now, preExclude: false }),
    (e) => {
      assert.equal(e.status, 422);
      assert.deepEqual(e.body.blockingCandidates, ['c1']);
      assert.deepEqual(e.body.exclusions.map((x) => x.id), ['c0', 'c1']);
      return true;
    },
  );
});

test('way match: crossing on another road (route on the bridge above) is not a conflict; trace failure -> conservative', async () => {
  const crossing = heightRow(0, { id: 'osm-maxheight-way77-crossing88', road_segment_id: 'osm:way:77' });
  assert.equal(gateWayId(crossing), 77);
  assert.equal(gateWayId(heightRow(0, { id: 'osm-maxheight-node5', road_segment_id: 'osm:way:77' })), null, 'height nodes stay geometric');
  assert.equal(gateWayId(heightRow(0, { road_segment_id: 'osm:way:77', geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] } })), 77);
  assert.deepEqual(splitByWay([crossing], null).rows, [crossing]);
  const traceOn = (ways) => async () => ({ ok: true, json: { edges: ways.map((w) => ({ way_id: w })) } });
  const repo = memRepo([crossing]);
  const onBridge = await planRoute({ callValhalla: mockValhalla(), callTraceAttributes: traceOn([88]), repo, baseRequest: {}, vehicle: truck, now, debug: true });
  assert.equal(onBridge.trucksil.reroutes, 0);
  assert.deepEqual(onBridge.trucksil.debug.iterations[0].otherRoad, ['osm-maxheight-way77-crossing88']);
  const underIt = await planRoute({ callValhalla: mockValhalla(), callTraceAttributes: traceOn([77, 88]), repo, baseRequest: {}, vehicle: truck, now });
  assert.equal(underIt.trucksil.reroutes, 1);
  const failed = await planRoute({ callValhalla: mockValhalla(), callTraceAttributes: async () => ({ ok: false, status: 500 }), repo, baseRequest: {}, vehicle: truck, now });
  assert.equal(failed.trucksil.reroutes, 1, 'unknown route ways -> restriction applies');
  const off = await planRoute({ callValhalla: mockValhalla(), callTraceAttributes: traceOn([88]), repo, baseRequest: {}, vehicle: truck, now, wayMatch: false });
  assert.equal(off.trucksil.reroutes, 1, 'ROUTE_WAY_MATCH=0 disables it');
});

test('pre-exclusion rings: small squares; crossings and directional rows skipped', () => {
  const pt = preExclusionRings(heightRow(0));
  assert.equal(pt.length, 1);
  assert.ok(ringPerimeterM(pt[0]) < 60);
  assert.equal(preExclusionRings(heightRow(0, { id: 'osm-maxheight-way1-crossing2' })), null);
  assert.equal(preExclusionRings(heightRow(0, { direction: 'forward' })), null);
  const line = preExclusionRings(heightRow(0, { geometry: { type: 'LineString', coordinates: [[34.8, 32], [34.801, 32]] } }));
  assert.equal(line.length, 2);
});

test('debug: per-iteration conflicts with type, value, status and source', async () => {
  const { trucksil } = await planRoute({ callValhalla: mockValhalla(), repo: memRepo(rows6.slice(0, 1)), baseRequest: {}, vehicle: truck, now, debug: true });
  const c = trucksil.debug.iterations[0].conflicts[0];
  assert.deepEqual(
    { id: c.id, type: c.type, value: c.value, status: c.status, sourceName: c.sourceName, sourceUrl: c.sourceUrl },
    { id: 'c0', type: 'max_height', value: 3.5, status: 'unverified', sourceName: 'e2e-fictional', sourceUrl: 'https://example.invalid/0' },
  );
  assert.equal(trucksil.debug.iterations.length, 2);
  const plain = await planRoute({ callValhalla: mockValhalla(), repo: memRepo(rows6.slice(0, 1)), baseRequest: {}, vehicle: truck, now });
  assert.equal(plain.trucksil.debug, undefined);
});

test('way match: nearby OSM tunnel/parking LineStrings within 50 m but not driven on are neither avoided nor onRoute', async () => {
  // Owner case: residential tunnel 2.8 m and parking-aisle tunnel 2 m parallel to the route.
  const c = conflictPoint(0);
  const near = (id, way, h) => heightRow(0, {
    id, road_segment_id: `osm:way:${way}`, value_numeric: h,
    geometry: { type: 'LineString', coordinates: [[c[0] - 0.0003, c[1] + 0.0002], [c[0] + 0.0003, c[1] + 0.0002]] },
  });
  const rows = [near('osm-maxheight-way288057451', 288057451, 2.8), near('osm-maxheight-way384018549', 384018549, 2), near('osm-maxheight-way9', 9, 5)];
  const trace = async () => ({ ok: true, json: { edges: [{ way_id: 1 }, { way_id: 9 }] } });
  const { trucksil } = await planRoute({ callValhalla: mockValhalla(), callTraceAttributes: trace, repo: memRepo(rows), baseRequest: {}, vehicle: truck, now });
  assert.equal(trucksil.reroutes, 0);
  assert.deepEqual(trucksil.avoided, []);
  assert.deepEqual(trucksil.onRoute.map((x) => x.id), ['osm-maxheight-way9'], 'only the way the route drives on is reported');
});
