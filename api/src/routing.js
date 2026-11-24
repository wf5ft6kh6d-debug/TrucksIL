'use strict';
// Applies TrucksIL's own restrictions to a Valhalla route (stage 2, item 3).
// Policy (ADR-0002): any known conflict is AVOIDED whatever its status (avoiding is always the
// safe direction), but nothing here ever claims a route is safe: absent data is not evidence.
const { routeShape } = require('./polyline');
const { directionApplies, thinExclusionRings, locate } = require('./routeGeometry');
const { traceAttributesRequest, routeWayIds } = require('./coverage');

const ROUTE_BUFFER_M = 50; // restriction counts as "on the route" within this distance of the shape
const EXCLUDE_BUFFER_M = 20; // radius of the fallback ("wide") polygon around the restriction (ADR-0011)

const DISCLAIMER = 'prototype, not for navigation';
const COVERAGE_NOTE = 'Absence of restrictions in TrucksIL data does not mean the route is safe';
const TZ = 'Asia/Jerusalem';
const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];

function localParts(now) {
  const f = new Intl.DateTimeFormat('en-GB', {
    timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', weekday: 'short', hourCycle: 'h23',
  });
  const p = Object.fromEntries(f.formatToParts(now).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}`, day: p.weekday.slice(0, 3).toLowerCase() };
}

function windowActive(w, lp) {
  if (!w || typeof w !== 'object') return true; // malformed -> treat as applying (conservative)
  if (w.validFrom && lp.date < w.validFrom) return false;
  if (w.validUntil && lp.date > w.validUntil) return false;
  if (Array.isArray(w.days) && w.days.length && w.days.every((d) => DAYS.includes(d)) && !w.days.includes(lp.day)) return false;
  if (w.startTime && w.endTime) {
    const { startTime: s, endTime: e } = w;
    const inside = s <= e ? lp.time >= s && lp.time < e : lp.time >= s || lp.time < e; // overnight windows
    if (!inside) return false;
  }
  return true;
}

/**
 * True if the restriction applies at `now` (Israel local time). No windows = always applies.
 * Simplification: overnight windows are matched on the start day's weekday only for the evening part.
 */
function isActiveNow(timeWindows, now = new Date()) {
  if (!Array.isArray(timeWindows) || timeWindows.length === 0) return true;
  const lp = localParts(now);
  return timeWindows.some((w) => windowActive(w, lp));
}

const NUMERIC_LIMITS = {
  max_height: 'heightM',
  max_width: 'widthM',
  max_length: 'lengthM',
  max_gross_weight: 'grossWeightT',
  max_axle_weight: 'axleLoadT',
};

// ADR tunnel categories, least to most restrictive (A = no restriction, not stored). ADR 1.9.5.2.2.
const TUNNEL_CATEGORIES = ['B', 'C', 'D', 'E'];

/**
 * Most restrictive tunnel category the vehicle may NOT enter, as a letter B..E, or null if unrestricted.
 * Simplification (ADR-0013): a code's first letter is the first forbidden category (B -> B..E forbidden,
 * D -> D and E). Combination codes (B1000C, B/D, C5000D, D/E, ...) are reduced to their first letter, i.e.
 * the strictest reading, because the exemption depends on load/tank details we do not model. A vehicle
 * with hazmat but no code is treated as code B (conservative). No hazmat -> null. '-' -> null.
 */
function vehicleTunnelCode(vehicle) {
  if (!vehicle || !vehicle.hazmat) return null;
  const code = vehicle.hazmat.adrTunnelCode;
  if (code === '-') return null;
  const letter = typeof code === 'string' ? code.charAt(0) : '';
  return TUNNEL_CATEGORIES.includes(letter) ? letter : 'B';
}

/**
 * Reason string if a vehicle with tunnel code `vehicleCode` (B..E or null) may not pass a tunnel of
 * `category`, else null. Forbidden when category >= code. An unknown/garbled category on a hazmat vehicle
 * is treated as E (most restrictive) -> conflict.
 */
function tunnelConflict(category, vehicleCode) {
  if (!vehicleCode) return null;
  let cat = TUNNEL_CATEGORIES.indexOf(category);
  if (cat < 0) cat = TUNNEL_CATEGORIES.length - 1;
  return cat >= TUNNEL_CATEGORIES.indexOf(vehicleCode)
    ? `ADR tunnel category ${TUNNEL_CATEGORIES[cat]} forbidden for tunnel code ${vehicleCode}`
    : null;
}

/** Returns null if the vehicle does not violate the restriction, otherwise a short reason. */
function violation(row, vehicle) {
  const field = NUMERIC_LIMITS[row.restriction_type];
  if (field) {
    const limit = Number(row.value_numeric);
    if (!Number.isFinite(limit)) return null;
    const actual = vehicle[field];
    // Axle load is optional in the profile: unknown axle load vs. a posted axle limit is treated as a
    // conflict (we cannot show compliance, so the conservative choice is to avoid).
    if (actual === undefined || actual === null) return `${field} not given; limit ${limit} ${row.unit}`;
    return limit < actual ? `${field} ${actual} > limit ${limit} ${row.unit}` : null;
  }
  if (row.restriction_type === 'truck_prohibited') return row.value_boolean === true ? 'trucks prohibited' : null;
  if (row.restriction_type === 'hazmat_restriction') {
    return row.value_boolean === true && vehicle.hazmat ? 'hazmat prohibited and vehicle carries hazmat' : null;
  }
  if (row.restriction_type === 'adr_tunnel') return tunnelConflict(row.value_text, vehicleTunnelCode(vehicle));
  return null;
}

function toPublic(row, reason) {
  const out = {
    id: row.id,
    restrictionType: row.restriction_type,
    value: row.unit === 'boolean' ? row.value_boolean
      : row.unit === 'adr_tunnel_category' ? row.value_text ?? null : Number(row.value_numeric),
    unit: row.unit,
    status: row.status,
    valueSource: row.value_source ?? null,
  };
  if (reason) out.reason = reason;
  // GeoJSON geometry (WGS84) so clients can place markers; omitted when the row has none.
  if (row.geometry && typeof row.geometry === 'object') out.geometry = row.geometry;
  return out;
}

/**
 * Splits rows near the route into conflicts (vehicle violates, active now) and the rest.
 * With `shape`, LineString restrictions with direction forward/backward that the route traverses the
 * other way are dropped (ADR-0011); anything undeterminable still applies.
 */
function classify(rows, vehicle, now = new Date(), shape = null, { includeExpired = false } = {}) {
  const conflicts = [];
  const onRoute = [];
  for (const row of rows) {
    if (row.status === 'expired' && !includeExpired) continue;
    if (shape && !directionApplies(row, shape)) continue;
    const reason = isActiveNow(row.time_windows, now) ? violation(row, vehicle) : null;
    if (reason) conflicts.push(toPublic(row, reason));
    else onRoute.push(toPublic(row));
  }
  return { conflicts, onRoute };
}

class RouteError extends Error {
  constructor(status, body) { super(body.error); this.status = status; this.body = body; }
}

// --- re-route loop configuration (ADR-0016) -----------------------------------------------------
const DEFAULT_MAX_REROUTES = 8;
// Valhalla service_limits.max_exclude_polygons_length: "Maximum total perimeter of all exclude_polygons
// in meters", default 10000 (scripts/valhalla_build_config). Exceeding it is error 167 (HTTP 400,
// "Exceeded maximum circumference for exclude_polygons"). We stay under it with a 5 % margin.
const DEFAULT_PERIMETER_BUDGET_M = 10000;
const PERIMETER_MARGIN = 0.95;
/**
 * Expired restrictions (ADR-0002, ADR-0020): never avoided or rerouted, but when the vehicle would
 * violate one that applies now, the route response carries a warning so an out-of-date limit is not
 * silently dropped. Same direction rules as classify (ADR-0011).
 */
function staleWarnings(rows, vehicle, now = new Date(), shape = null) {
  const out = [];
  for (const row of rows) {
    if (row.status !== 'expired') continue;
    if (shape && !directionApplies(row, shape)) continue;
    if (!isActiveNow(row.time_windows, now)) continue;
    const reason = violation(row, vehicle);
    if (reason) out.push(toPublic(row, reason));
  }
  return out;
}

const PRE_CORRIDOR_M = 3000; // pre-exclusion: conflicts within this distance of the first route
const DEFAULT_MAX_PRE_EXCLUSIONS = 200;
const PRE_HALF_M = 6; // half-size of a pre-exclusion square
const COMPACT_ALONG_M = 8; // thin ring length (+-m) used when the perimeter budget is tight
const VALHALLA_PERIMETER_ERROR = 167;

const envNum = (name, dflt) => {
  const v = Number(process.env[name]);
  return Number.isFinite(v) && v >= 0 && process.env[name] !== '' ? v : dflt;
};
const envFlag = (name, dflt) => {
  const v = process.env[name];
  if (v === undefined || v === '') return dflt;
  return !['0', 'false', 'no', 'off'].includes(String(v).toLowerCase());
};
/** Effective loop settings; env: MAX_REROUTES, PRE_EXCLUDE, MAX_PRE_EXCLUSIONS, VALHALLA_MAX_EXCLUDE_PERIMETER_M, ROUTE_WAY_MATCH. */
function routingConfig() {
  return {
    maxReroutes: Math.floor(envNum('MAX_REROUTES', DEFAULT_MAX_REROUTES)),
    preExclude: envFlag('PRE_EXCLUDE', true),
    maxPreExclusions: Math.floor(envNum('MAX_PRE_EXCLUSIONS', DEFAULT_MAX_PRE_EXCLUSIONS)),
    perimeterBudgetM: envNum('VALHALLA_MAX_EXCLUDE_PERIMETER_M', DEFAULT_PERIMETER_BUDGET_M) * PERIMETER_MARGIN,
    wayMatch: envFlag('ROUTE_WAY_MATCH', true),
  };
}

const MAX_REROUTES = DEFAULT_MAX_REROUTES;

/** Geodesic-ish perimeter (m) of a [lon,lat] ring (equirectangular, fine at ring scale). */
function ringPerimeterM(ring) {
  let p = 0;
  for (let i = 1; i < ring.length; i += 1) {
    const [a, b] = [ring[i - 1], ring[i]];
    const k = Math.cos(((a[1] + b[1]) / 2) * Math.PI / 180);
    p += Math.hypot((b[0] - a[0]) * k, b[1] - a[1]) * (Math.PI / 180) * 6371008.8;
  }
  return p;
}
const ringsPerimeterM = (rings) => rings.reduce((s, r) => s + ringPerimeterM(r), 0);

// OSM-derived rows carry road_segment_id 'osm:way:<id>' (scripts/import_osm_maxheight.py). For a
// LineString (the way itself) and for a "crossing" Point (road <id> passing under a bridge; the point
// lies on the bridge too) the restriction belongs to that road only. Height nodes stay geometric:
// a node can be shared by several ways.
const CROSSING_ID_RE = /-crossing\d+$/;
function gateWayId(row) {
  const m = /^osm:way:(\d+)$/.exec(row && row.road_segment_id ? String(row.road_segment_id) : '');
  if (!m || !row.geometry) return null;
  if (row.geometry.type === 'LineString' || (row.geometry.type === 'Point' && CROSSING_ID_RE.test(String(row.id)))) return Number(m[1]);
  return null;
}

/**
 * Way match (ADR-0016): drops rows whose OSM road (gateWayId) is not among the route's way ids.
 * routeWays null (trace unavailable) -> nothing dropped (conservative).
 */
function splitByWay(rows, routeWays) {
  if (!routeWays) return { rows, otherRoad: [] };
  const keep = [];
  const otherRoad = [];
  for (const r of rows) {
    const w = gateWayId(r);
    if (w !== null && !routeWays.has(w)) otherRoad.push(r); else keep.push(r);
  }
  return { rows: keep, otherRoad };
}

/** Square ring of half-size h metres around [lon,lat]. */
function squareRing([lon, lat], h) {
  const dLat = h / 111320;
  const dLon = dLat / Math.cos(lat * Math.PI / 180);
  return [[lon - dLon, lat - dLat], [lon + dLon, lat - dLat], [lon + dLon, lat + dLat], [lon - dLon, lat + dLat], [lon - dLon, lat - dLat]];
}

/** Point at fraction f of a LineString's length. */
function lineFraction(coords, f) {
  const seg = [];
  let total = 0;
  for (let i = 1; i < coords.length; i += 1) {
    const k = Math.cos(coords[i][1] * Math.PI / 180);
    const d = Math.hypot((coords[i][0] - coords[i - 1][0]) * k, coords[i][1] - coords[i - 1][1]);
    seg.push(d); total += d;
  }
  let t = total * f;
  for (let i = 0; i < seg.length; i += 1) {
    if (t <= seg[i] || i === seg.length - 1) {
      const u = seg[i] ? Math.min(t / seg[i], 1) : 0;
      return [coords[i][0] + (coords[i + 1][0] - coords[i][0]) * u, coords[i][1] + (coords[i + 1][1] - coords[i][1]) * u];
    }
    t -= seg[i];
  }
  return coords[coords.length - 1];
}

/**
 * Compact pre-exclusion rings for a restriction that is NOT on the current route (ADR-0016).
 * Point -> one small square. LineString -> squares at 15 % and 85 % of its length, which block the
 * way's edges near both ends without covering its middle, where a bridge usually crosses it.
 * Crossing Points are skipped (the square would also cut the bridge road above), as are directional
 * rows (a square excludes both directions). Returns null when not applicable.
 */
function preExclusionRings(row) {
  const g = row.geometry;
  if (!g || !Array.isArray(g.coordinates)) return null;
  if (row.direction === 'forward' || row.direction === 'backward') return null;
  if (g.type === 'Point') return CROSSING_ID_RE.test(String(row.id)) ? null : [squareRing(g.coordinates, PRE_HALF_M)];
  if (g.type === 'LineString' && g.coordinates.length >= 2) return [0.15, 0.85].map((f) => squareRing(lineFraction(g.coordinates, f), PRE_HALF_M));
  return null;
}

function debugConflict(c, row) {
  const src = row && row.source && typeof row.source === 'object' ? row.source : {};
  return {
    id: c.id, type: c.restrictionType, value: c.value, unit: c.unit, status: c.status, reason: c.reason,
    sourceName: src.name ?? null, sourceUrl: src.url ?? null, roadSegmentId: row ? row.road_segment_id ?? null : null,
  };
}

/**
 * Runs the route -> check -> exclude -> re-route loop (ADR-0011, ADR-0016).
 * @param {object} p
 * @param {Function} p.callValhalla  async (requestBody) -> {status, ok, json}; throws RouteError for transport errors
 * @param {Function} [p.callTraceAttributes] async (requestBody) -> {ok, json}; enables the way match
 * @param {object} p.repo            restrictions repository (see restrictionsRepo.js)
 * @param {object} p.baseRequest     Valhalla /route body without exclude_polygons
 * @param {object} p.vehicle
 * @param {boolean} [p.debug]        adds trucksil.debug (per-iteration conflicts and exclusions)
 * @returns {Promise<{result, trucksil}>}  throws RouteError for non-200 outcomes
 */
async function planRoute({
  callValhalla, callTraceAttributes = null, repo, baseRequest, vehicle, now = new Date(), debug = false, ...opts
}) {
  const cfg = { ...routingConfig(), ...Object.fromEntries(Object.entries(opts).filter(([, v]) => v !== undefined)) };
  const { maxReroutes, perimeterBudgetM, maxPreExclusions } = cfg;
  const avoided = new Map(); // id -> public conflict
  // id -> {level: 'thin' | 'wide', rings}. Escalation per conflict (ADR-0011): thin rectangles around the
  // route edge that passed it -> 20 m polygon around the restriction itself -> no progress -> 409.
  // Accumulated across iterations: nothing is ever removed, so a revealed conflict stays excluded.
  const exclusions = new Map();
  let pre = new Map(); // id -> {rings, distM}: soft pre-exclusions (ADR-0016), may be dropped
  let preDropped = null;
  let lastAdded = [];
  const iterations = [];
  let attempt = 0;
  const mandatoryRings = () => [...exclusions.values()].flatMap((e) => e.rings);
  const dbg = (extra) => (debug ? { debug: { config: cfg, iterations, preExclusionDropped: preDropped, ...extra } } : {});

  for (;;) {
    const rings = [...mandatoryRings(), ...[...pre.values()].flatMap((e) => e.rings)];
    const body = rings.length ? { ...baseRequest, exclude_polygons: rings } : baseRequest;
    const it = debug ? { attempt, exclusions: exclusions.size, preExclusions: pre.size, rings: rings.length, perimeterM: Math.round(ringsPerimeterM(rings)) } : null;
    if (it) iterations.push(it);
    const r = await callValhalla(body);
    if (!r.ok) {
      if (attempt === 0 && !rings.length) {
        throw new RouteError(r.status >= 500 ? 502 : r.status, { error: 'Valhalla error', valhalla: r.json });
      }
      if (r.status >= 500) throw new RouteError(502, { error: 'Valhalla error', valhalla: r.json, ...dbg() });
      if (pre.size) {
        // Pre-exclusions are an optimisation only: if they cut every path (or the budget), retry without.
        preDropped = { ids: [...pre.keys()], valhalla: r.json };
        if (it) it.result = `valhalla ${r.status}; pre-exclusions dropped`;
        pre = new Map();
        attempt += 1;
        if (attempt > maxReroutes) break;
        continue;
      }
      if (r.json && r.json.error_code === VALHALLA_PERIMETER_ERROR) {
        throw new RouteError(409, {
          error: 'too many TrucksIL conflicts to exclude: Valhalla exclude_polygons perimeter limit reached (set VALHALLA_MAX_EXCLUDE_PERIMETER_M to the server limit)',
          conflicts: [...avoided.values()], valhalla: r.json, ...dbg(),
        });
      }
      throw new RouteError(422, {
        error: 'no route found that avoids the known TrucksIL restrictions for this vehicle',
        conflicts: [...avoided.values()],
        // A route existed before the last step, so the exclusions added in it are the ones that cut off
        // every remaining path (together with the earlier ones).
        blockingCandidates: lastAdded,
        exclusions: [...exclusions.entries()].map(([id, e]) => ({ id, level: e.level, rings: e.rings.length })),
        valhalla: r.json,
        ...dbg(),
      });
    }
    const shape = routeShape(r.json);
    if (shape.length === 0) throw new RouteError(502, { error: 'Valhalla response has no route shape; restrictions cannot be checked' });

    let nearRows = await repo.findAlongRoute(shape, ROUTE_BUFFER_M);
    // Alternative-route mode (ADR-0020): out-of-date restrictions are treated like any other for
    // THIS search only, so the alternative avoids them. The default route never does this.
    if (cfg.includeExpired) nearRows = nearRows.concat(await repo.findExpiredAlongRoute(shape, ROUTE_BUFFER_M));
    let routeWays = null;
    // Trace only when some nearby row can be matched by way (saves a Valhalla call otherwise).
    if (cfg.wayMatch && callTraceAttributes && nearRows.some((x) => gateWayId(x) !== null)) {
      try {
        const t = await callTraceAttributes(traceAttributesRequest(shape));
        if (t && t.ok && t.json && Array.isArray(t.json.edges)) routeWays = new Set(routeWayIds(t.json));
      } catch { routeWays = null; }
    }
    const { rows: gated, otherRoad } = splitByWay(nearRows, routeWays);
    const { conflicts, onRoute } = classify(gated, vehicle, now, shape, { includeExpired: cfg.includeExpired === true });
    const rowById = new Map(nearRows.map((x) => [x.id, x]));
    if (it) {
      it.conflicts = conflicts.map((c) => debugConflict(c, rowById.get(c.id)));
      it.otherRoad = otherRoad.map((x) => x.id);
      it.wayMatch = routeWays ? 'on' : 'off';
    }
    if (conflicts.length === 0) {
      // Expired rows: warn only. A failed lookup is reported as 'unavailable', never as 'none'.
      let expiredWarnings = [];
      let expiredCheck = 'ok';
      if (typeof repo.findExpiredAlongRoute === 'function') {
        try {
          const expRows = await repo.findExpiredAlongRoute(shape, ROUTE_BUFFER_M);
          expiredWarnings = staleWarnings(splitByWay(expRows, routeWays).rows, vehicle, now, shape);
        } catch { expiredCheck = 'unavailable'; }
      } else expiredCheck = 'unavailable';
      // Offer (never impose) a route that also avoids the out-of-date restrictions; the driver chooses.
      let alternative = null;
      let alternativeStatus = 'not_needed';
      if (expiredWarnings.length && !cfg.includeExpired) {
        try {
          const alt = await planRoute({ callValhalla, callTraceAttributes, repo, baseRequest, vehicle, now, debug: false, ...opts, includeExpired: true });
          alternative = { result: alt.result, trucksil: alt.trucksil };
          alternativeStatus = 'found';
        } catch (e) {
          alternativeStatus = e instanceof RouteError && e.status < 500 ? 'none' : 'unavailable';
        }
      }
      const verifiedOnRoute = onRoute.filter((x) => x.status === 'verified').length;
      return {
        result: r.json,
        trucksil: {
          disclaimer: DISCLAIMER,
          avoided: [...avoided.values()],
          onRoute,
          expiredWarnings,
          expiredCheck,
          alternativeStatus,
          alternative,
          coverage: { verifiedOnRoute, unverifiedOnRoute: onRoute.length - verifiedOnRoute, note: COVERAGE_NOTE },
          unverifiedCoverage: 'unknown',
          reroutes: attempt,
          ...dbg({ preExcluded: [...pre.keys()] }),
        },
      };
    }
    if (attempt >= maxReroutes) {
      throw new RouteError(409, {
        error: `route still conflicts with TrucksIL restrictions after ${attempt} re-route attempts`,
        conflicts,
        avoided: [...avoided.values()].filter((a) => !conflicts.some((c) => c.id === a.id)),
        ...dbg(),
      });
    }
    let progressed = 0;
    const added = [];
    const needWide = [];
    for (const c of conflicts) {
      const prev = exclusions.get(c.id);
      pre.delete(c.id); // now a hard (mandatory) exclusion
      if (!prev) {
        const thin = thinExclusionRings(shape, c.geometry);
        if (thin) { exclusions.set(c.id, { level: 'thin', rings: thin, shape }); progressed += 1; added.push(c.id); } else needWide.push(c.id);
      } else if (prev.level === 'thin') {
        needWide.push(c.id); // thin exclusion did not keep the route off it -> escalate
      } // 'wide' already: nothing stronger to try
    }
    if (needWide.length) {
      const polys = await repo.exclusionPolygons(needWide, EXCLUDE_BUFFER_M);
      for (const p of polys) {
        const prev = exclusions.get(p.id);
        // Keep the thin rings too: they cover the route edge even if the restriction point is off it.
        exclusions.set(p.id, { level: 'wide', rings: [...(prev ? prev.rings : []), p.ring] });
        progressed += 1;
        added.push(p.id);
      }
    }
    for (const c of conflicts) avoided.set(c.id, c);
    if (progressed === 0) {
      // Conflicts already excluded at the widest level (Valhalla still routes through them) -> no progress.
      throw new RouteError(409, { error: 'route still conflicts with TrucksIL restrictions; exclusion had no effect', conflicts, ...dbg() });
    }
    // Perimeter budget: shrink newly added thin rings first; mandatory exclusions must fit.
    if (ringsPerimeterM(mandatoryRings()) > perimeterBudgetM) {
      for (const id of added) {
        const e = exclusions.get(id);
        if (e && e.level === 'thin' && e.shape) {
          const c = conflicts.find((x) => x.id === id);
          const compact = thinExclusionRings(e.shape, c.geometry, { alongM: COMPACT_ALONG_M });
          if (compact) e.rings = compact;
        }
      }
    }
    const mandatoryM = ringsPerimeterM(mandatoryRings());
    if (mandatoryM > perimeterBudgetM) {
      throw new RouteError(409, {
        error: `too many TrucksIL conflicts to exclude: exclusion perimeter ${Math.round(mandatoryM)} m exceeds the Valhalla limit ${Math.round(perimeterBudgetM)} m`,
        conflicts: [...avoided.values()],
        ...dbg(),
      });
    }
    lastAdded = added;
    // Pre-exclusion (once, after the first conflicting route): exclude up front every other conflict
    // within PRE_CORRIDOR_M of this route, nearest first, within the remaining budget.
    if (cfg.preExclude && attempt === 0 && maxPreExclusions > 0) {
      pre = await buildPreExclusions({
        repo, shape, vehicle, now, routeWays: null, skip: new Set([...exclusions.keys()]),
        budgetM: perimeterBudgetM - mandatoryM, maxCount: maxPreExclusions,
      });
    }
    // Keep pre-exclusions within what the grown mandatory set leaves of the budget (drop farthest first).
    if (pre.size) {
      let room = perimeterBudgetM - ringsPerimeterM(mandatoryRings());
      const kept = new Map();
      for (const [id, e] of [...pre.entries()].sort((a, b) => a[1].distM - b[1].distM)) {
        const p = ringsPerimeterM(e.rings);
        if (p <= room) { kept.set(id, e); room -= p; }
      }
      pre = kept;
    }
    if (it) { it.added = added; it.preAdded = attempt === 0 ? [...pre.keys()] : []; }
    attempt += 1;
  }
  throw new RouteError(409, {
    error: `route still conflicts with TrucksIL restrictions after ${attempt} re-route attempts`,
    conflicts: [...avoided.values()], ...dbg(),
  });
}

async function buildPreExclusions({ repo, shape, vehicle, now, skip, budgetM, maxCount }) {
  const rows = await repo.findAlongRoute(shape, PRE_CORRIDOR_M);
  // No shape -> no direction filter; preExclusionRings skips directional rows anyway.
  const { conflicts } = classify(rows.filter((x) => !skip.has(x.id)), vehicle, now, null);
  const byId = new Map(rows.map((x) => [x.id, x]));
  const cands = [];
  for (const c of conflicts) {
    const row = byId.get(c.id);
    const rings = preExclusionRings(row);
    if (!rings) continue;
    const loc = locate(shape, row.geometry);
    cands.push({ id: c.id, rings, distM: loc ? loc.distM : Infinity, perimeterM: ringsPerimeterM(rings) });
  }
  cands.sort((a, b) => a.distM - b.distM || (a.id < b.id ? -1 : 1));
  const out = new Map();
  let used = 0;
  for (const c of cands) {
    if (out.size >= maxCount) break;
    if (used + c.perimeterM > budgetM) continue;
    used += c.perimeterM;
    out.set(c.id, { rings: c.rings, distM: c.distM });
  }
  return out;
}

module.exports = {
  ROUTE_BUFFER_M, EXCLUDE_BUFFER_M, MAX_REROUTES, DEFAULT_PERIMETER_BUDGET_M, PRE_CORRIDOR_M, routingConfig,
  ringPerimeterM, gateWayId, splitByWay, preExclusionRings, DISCLAIMER, COVERAGE_NOTE,
  TUNNEL_CATEGORIES, vehicleTunnelCode, tunnelConflict, isActiveNow, violation, classify, staleWarnings, planRoute, RouteError,
};
