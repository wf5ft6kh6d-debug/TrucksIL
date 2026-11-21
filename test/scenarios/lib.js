'use strict';
// Shared helpers for the reference route scenarios (test/scenarios/routes.json).
// Used by test/api/scenarios.test.js (mock Valhalla + in-memory repo) and scripts/e2e_routes.js (real stack).
// All restrictions produced here are FICTIONAL test data.
const fs = require('node:fs');
const path = require('node:path');
const { encodePolyline, routeShape } = require('../../api/src/polyline');

const SEED_PREFIX = 'e2e-';
const SCENARIO_FILE = path.join(__dirname, 'routes.json');

/** Loads routes.json and resolves place / vehicle names. */
function loadScenarios(file = SCENARIO_FILE) {
  const data = JSON.parse(fs.readFileSync(file, 'utf8'));
  const resolve = (map, key, what, id) => {
    if (Array.isArray(key)) return key;
    if (!(key in map)) throw new Error(`${id}: unknown ${what} "${key}"`);
    return map[key];
  };
  const seen = new Set();
  return data.scenarios.map((s) => {
    if (seen.has(s.id)) throw new Error(`duplicate scenario id ${s.id}`);
    seen.add(s.id);
    return {
      ...s,
      from: resolve(data.places, s.from, 'place', s.id),
      to: resolve(data.places, s.to, 'place', s.id),
      vehicle: typeof s.vehicle === 'string' ? resolve(data.vehicles, s.vehicle, 'vehicle', s.id) : s.vehicle,
      restrictions: (s.restrictions || []).map((r) => ({ ...r, id: SEED_PREFIX + r.id })),
    };
  });
}

const R = 6371008.8;
const rad = (d) => (d * Math.PI) / 180;

function haversineM([lon1, lat1], [lon2, lat2]) {
  const a = Math.sin(rad(lat2 - lat1) / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lon2 - lon1) / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

/** Point at fraction f (0..1) of the shape's length. */
function pointAtFraction(shape, f) {
  if (!shape.length) throw new Error('empty shape');
  if (shape.length === 1) return shape[0];
  const seg = [];
  let total = 0;
  for (let i = 1; i < shape.length; i += 1) { const d = haversineM(shape[i - 1], shape[i]); seg.push(d); total += d; }
  let target = Math.min(Math.max(f, 0), 1) * total;
  for (let i = 0; i < seg.length; i += 1) {
    if (target <= seg[i] || i === seg.length - 1) {
      const t = seg[i] ? Math.min(target / seg[i], 1) : 0;
      const [a, b] = [shape[i], shape[i + 1]];
      return [+(a[0] + (b[0] - a[0]) * t).toFixed(7), +(a[1] + (b[1] - a[1]) * t).toFixed(7)];
    }
    target -= seg[i];
  }
  return shape[shape.length - 1];
}

/** Distance (m) from a point to a polyline; local equirectangular projection (fine at <100 km scale). */
function distanceToShapeM(p, shape) {
  const k = Math.cos(rad(p[1]));
  const xy = ([lon, lat]) => [rad(lon) * k * R, rad(lat) * R];
  const P = xy(p);
  let best = Infinity;
  for (let i = 0; i < shape.length; i += 1) {
    const A = xy(shape[i]);
    const B = xy(shape[Math.min(i + 1, shape.length - 1)]);
    const dx = B[0] - A[0];
    const dy = B[1] - A[1];
    const L = dx * dx + dy * dy;
    const t = L ? Math.max(0, Math.min(1, ((P[0] - A[0]) * dx + (P[1] - A[1]) * dy) / L)) : 0;
    best = Math.min(best, Math.hypot(P[0] - (A[0] + t * dx), P[1] - (A[1] + t * dy)));
  }
  return best;
}

/** Resolves a restriction's `where` to [lon, lat] using the baseline route shape. */
function resolveWhere(where, baselineShape) {
  if (Array.isArray(where)) return where;
  if (where && Number.isFinite(where.onRouteFraction)) return pointAtFraction(baselineShape, where.onRouteFraction);
  throw new Error(`bad "where": ${JSON.stringify(where)}`);
}

function shapeLengthM(shape) {
  let total = 0;
  for (let i = 1; i < shape.length; i += 1) total += haversineM(shape[i - 1], shape[i]);
  return total;
}

/**
 * Resolves `where` to a GeoJSON geometry. `{onRouteFraction, lineM}` -> a LineString of ~lineM metres
 * centred on that fraction and digitized along the route's travel direction (`reversed: true` -> against it).
 * Anything else -> Point (resolveWhere).
 */
function resolveGeometry(where, baselineShape) {
  if (where && Number.isFinite(where.lineM) && Number.isFinite(where.onRouteFraction)) {
    const half = where.lineM / 2 / (shapeLengthM(baselineShape) || 1);
    const coords = [-1, 0, 1].map((k) => pointAtFraction(baselineShape, where.onRouteFraction + k * half));
    return { type: 'LineString', coordinates: where.reversed ? coords.reverse() : coords };
  }
  return { type: 'Point', coordinates: resolveWhere(where, baselineShape) };
}

/** Representative point of a Point/LineString geometry (middle vertex). */
const geometryPoint = (g) => (g.type === 'Point' ? g.coordinates : g.coordinates[Math.floor(g.coordinates.length / 2)]);

/**
 * Restriction as a DB row (same column names as restrictionsRepo's SELECT) plus a `point`.
 * The second argument is a [lon,lat] point or a GeoJSON geometry (see resolveGeometry).
 */
function toRow(r, where) {
  const geometry = Array.isArray(where) ? { type: 'Point', coordinates: where } : where;
  const point = geometryPoint(geometry);
  const bool = r.unit === 'boolean';
  const text = r.unit === 'adr_tunnel_category';
  return {
    geometry,
    id: r.id, road_segment_id: 'e2e-fictional', value_source: r.valueSource ?? null, direction: r.direction ?? 'both',
    restriction_type: r.type, value_numeric: bool || text ? null : r.value, value_boolean: bool ? r.value : null, value_text: text ? r.value : null,
    unit: r.unit, time_windows: r.timeWindows ?? null, status: r.status,
    verified_at: r.status === 'verified' ? new Date('2026-01-01T00:00:00Z') : null, review_due_at: null, point,
  };
}

/**
 * In-memory stand-in for restrictionsRepo: same filters as ALONG_ROUTE_SQL (geometry within bufferM of the
 * line, status <> 'expired', ORDER BY id; LineStrings tested by their vertices) and a square ring of ~bufferM around the point for exclusions.
 */
function createMemoryRepo(rows) {
  return {
    async findAlongRoute(coords, bufferM) {
      if (!coords.length) return [];
      const near = (r) => (r.geometry.type === 'Point' ? [r.point] : r.geometry.coordinates).some((p) => distanceToShapeM(p, coords) <= bufferM);
      return rows.filter((r) => r.status !== 'expired' && near(r))
        .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
        .map(({ point, ...row }) => row);
    },
    async exclusionPolygons(ids, bufferM) {
      return rows.filter((r) => ids.includes(r.id)).sort((a, b) => (a.id < b.id ? -1 : 1)).map((r) => {
        const [lon, lat] = r.point;
        const dLat = bufferM / 111320;
        const dLon = dLat / Math.cos(rad(lat));
        return { id: r.id, ring: [[lon - dLon, lat - dLat], [lon + dLon, lat - dLat], [lon + dLon, lat + dLat], [lon - dLon, lat + dLat], [lon - dLon, lat - dLat]] };
      });
    },
  };
}

// --- mock Valhalla ----------------------------------------------------------------------------
// Baseline: 41 points on the straight line from -> to. Detour (whenever exclude_polygons is present):
// the same line bent sideways by up to ~0.05 deg (~5 km) in the middle, so it misses every point that
// lies on the middle part of the baseline. noDetour: any request with exclusions fails like Valhalla 442.
const N = 40;
function mockShape(from, to, bulgeDeg) {
  const [dx, dy] = [to[0] - from[0], to[1] - from[1]];
  const len = Math.hypot(dx, dy) || 1;
  const [nx, ny] = [-dy / len, dx / len];
  const pts = [];
  for (let i = 0; i <= N; i += 1) {
    const t = i / N;
    const off = bulgeDeg * Math.sin(Math.PI * t);
    pts.push([+(from[0] + dx * t + nx * off).toFixed(6), +(from[1] + dy * t + ny * off).toFixed(6)]);
  }
  return pts;
}

function mockValhallaRoute(body, { noDetour = false } = {}) {
  const locs = body && body.locations;
  if (!Array.isArray(locs) || locs.length < 2) return { status: 400, json: { error_code: 100, error: 'bad request (mock)' } };
  const from = [locs[0].lon, locs[0].lat];
  const to = [locs[locs.length - 1].lon, locs[locs.length - 1].lat];
  const excl = Array.isArray(body.exclude_polygons) && body.exclude_polygons.length > 0;
  if (excl && noDetour) return { status: 400, json: { error_code: 442, error: 'No path could be found for input (mock)' } };
  const shape = mockShape(from, to, excl ? 0.05 : 0);
  return {
    status: 200,
    json: { trip: { status: 0, mock: true, legs: [{ shape: encodePolyline(shape) }], summary: { length: 0, time: 0 } } },
  };
}

/** fetch() implementation answering Valhalla /status and /route with the mock. */
function mockValhallaFetch(opts = {}) {
  return async (url, init = {}) => {
    const u = String(url);
    const reply = (status, obj) => ({ ok: status >= 200 && status < 300, status, json: async () => obj });
    if (u.endsWith('/status')) return reply(200, { version: 'mock' });
    if (u.endsWith('/route')) { const r = mockValhallaRoute(JSON.parse(init.body), opts); return reply(r.status, r.json); }
    return reply(404, { error: 'not found (mock)' });
  };
}

/** Compares a /v1/route response with scenario.expected. Returns a list of failure messages ([] = pass). */
function checkExpectations(scenario, status, body) {
  const e = scenario.expected;
  const fails = [];
  const seeded = new Set(scenario.restrictions.map((r) => r.id));
  const ids = (arr) => (Array.isArray(arr) ? arr.map((x) => x.id).filter((id) => seeded.has(id)).sort() : []);
  const want = (arr) => (arr || []).map((id) => SEED_PREFIX + id).sort();
  const same = (label, got, exp) => { if (JSON.stringify(got) !== JSON.stringify(exp)) fails.push(`${label}: got [${got}] want [${exp}]`); };
  if (status !== e.status) fails.push(`HTTP ${status}, want ${e.status}${body && body.error ? ` (${body.error})` : ''}`);
  if (status === 200 && e.status === 200) {
    const t = body.trucksil || {};
    if ('avoidedIds' in e) same('avoided', ids(t.avoided), want(e.avoidedIds));
    if ('onRouteIds' in e) same('onRoute', ids(t.onRoute), want(e.onRouteIds));
    for (const id of want(e.absentIds)) {
      if ([...(t.avoided || []), ...(t.onRoute || [])].some((x) => x.id === id)) fails.push(`${id} must be ignored but is reported`);
    }
    if (Number.isFinite(e.minReroutes) && !(t.reroutes >= e.minReroutes)) fails.push(`reroutes ${t.reroutes} < ${e.minReroutes}`);
    if (Number.isFinite(e.maxReroutes) && !(t.reroutes <= e.maxReroutes)) fails.push(`reroutes ${t.reroutes} > ${e.maxReroutes}`);
    if (Number.isFinite(e.minVerifiedOnRoute)) {
      const v = t.coverage && t.coverage.verifiedOnRoute;
      if (!(v >= e.minVerifiedOnRoute)) fails.push(`coverage.verifiedOnRoute ${v} < ${e.minVerifiedOnRoute}`);
    }
    if (t.disclaimer !== 'prototype, not for navigation') fails.push('missing disclaimer');
  }
  if ('conflictIds' in e && status === e.status) same('conflicts', ids(body.conflicts), want(e.conflictIds));
  return fails;
}


/**
 * Evaluates an e2e run relative to the baseline (same request without the seeded rows), so real
 * (non-test) data in the database does not break the scenarios (ADR-0016).
 * base / res: {status, body}. strict: old absolute behaviour (E2E_STRICT=1).
 * Returns {result: 'PASS'|'FAIL'|'SKIP', fails: string[], notes: string[]}.
 *  - baseline not 200 -> SKIP "baseline blocked by non-test data" (FAIL when strict);
 *  - seeded ids (avoided/onRoute/absent/conflicts), status, verified coverage, disclaimer: as checkExpectations;
 *  - reroutes (relative): scenarios expecting avoidance (minReroutes >= 1) need reroutes >= max(minReroutes,
 *    baseline reroutes); no-avoid scenarios (maxReroutes 0) only need the seeded ids out of avoided;
 *    a different reroute count from the baseline is a note, not a failure.
 */
function evaluateRelative(scenario, base, res, { strict = false } = {}) {
  const notes = [];
  if (!base || base.status !== 200) {
    const why = `baseline HTTP ${base ? base.status : '?'}${base && base.body && base.body.error ? ` (${base.body.error})` : ''}`;
    if (strict) return { result: 'FAIL', fails: [`baseline route: ${why}`], notes };
    return { result: 'SKIP', fails: [], notes: [`baseline blocked by non-test data: ${why}`] };
  }
  const bt = base.body.trucksil || {};
  const baseReroutes = Number.isFinite(bt.reroutes) ? bt.reroutes : 0;
  const nonTest = [...(bt.avoided || []), ...(bt.onRoute || [])].filter((x) => !String(x.id).startsWith(SEED_PREFIX)).length;
  if (nonTest || baseReroutes) notes.push(`baseline: reroutes ${baseReroutes}, ${nonTest} non-test restriction(s)`);
  if (strict) {
    const fails = checkExpectations(scenario, res.status, res.body);
    return { result: fails.length ? 'FAIL' : 'PASS', fails, notes };
  }
  const e = scenario.expected;
  const relaxed = { ...scenario, expected: { ...e } };
  delete relaxed.expected.minReroutes;
  delete relaxed.expected.maxReroutes;
  const fails = checkExpectations(relaxed, res.status, res.body);
  if (res.status === 200 && e.status === 200) {
    const t = res.body.trucksil || {};
    if (Number.isFinite(e.minReroutes) && e.minReroutes >= 1) {
      const need = Math.max(e.minReroutes, baseReroutes);
      if (!(t.reroutes >= need)) fails.push(`reroutes ${t.reroutes} < ${need} (baseline ${baseReroutes})`);
    } else if (t.reroutes !== baseReroutes) {
      notes.push(`reroutes ${t.reroutes} vs baseline ${baseReroutes}`);
    }
  }
  return { result: fails.length ? 'FAIL' : 'PASS', fails, notes };
}

module.exports = {
  evaluateRelative,
  SEED_PREFIX, SCENARIO_FILE, loadScenarios, haversineM, pointAtFraction, distanceToShapeM, resolveWhere, resolveGeometry, toRow,
  createMemoryRepo, mockShape, mockValhallaRoute, mockValhallaFetch, checkExpectations, routeShape,
};
