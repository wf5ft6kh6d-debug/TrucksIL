'use strict';
// Applies TrucksIL's own restrictions to a Valhalla route (stage 2, item 3).
// Policy (ADR-0002): any known conflict is AVOIDED whatever its status (avoiding is always the
// safe direction), but nothing here ever claims a route is safe: absent data is not evidence.
const { routeShape } = require('./polyline');

const ROUTE_BUFFER_M = 50; // restriction counts as "on the route" within this distance of the shape
const EXCLUDE_BUFFER_M = 20; // radius of the polygon sent to Valhalla exclude_polygons
const MAX_REROUTES = 3;

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
  return null;
}

function toPublic(row, reason) {
  const out = {
    id: row.id,
    restrictionType: row.restriction_type,
    value: row.unit === 'boolean' ? row.value_boolean : Number(row.value_numeric),
    unit: row.unit,
    status: row.status,
    valueSource: row.value_source ?? null,
  };
  if (reason) out.reason = reason;
  return out;
}

/** Splits rows near the route into conflicts (vehicle violates, active now) and the rest. */
function classify(rows, vehicle, now = new Date()) {
  const conflicts = [];
  const onRoute = [];
  for (const row of rows) {
    if (row.status === 'expired') continue;
    const reason = isActiveNow(row.time_windows, now) ? violation(row, vehicle) : null;
    if (reason) conflicts.push(toPublic(row, reason));
    else onRoute.push(toPublic(row));
  }
  return { conflicts, onRoute };
}

class RouteError extends Error {
  constructor(status, body) { super(body.error); this.status = status; this.body = body; }
}

/**
 * Runs the route -> check -> exclude -> re-route loop.
 * @param {object} p
 * @param {Function} p.callValhalla  async (requestBody) -> {status, ok, json}; throws RouteError for transport errors
 * @param {object} p.repo            restrictions repository (see restrictionsRepo.js)
 * @param {object} p.baseRequest     Valhalla /route body without exclude_polygons
 * @param {object} p.vehicle
 * @returns {Promise<{result, trucksil}>}  throws RouteError for non-200 outcomes
 */
async function planRoute({ callValhalla, repo, baseRequest, vehicle, now = new Date(), maxReroutes = MAX_REROUTES }) {
  const avoided = new Map(); // id -> public conflict
  const rings = new Map(); // id -> polygon ring
  let attempt = 0;
  for (;;) {
    const body = rings.size ? { ...baseRequest, exclude_polygons: [...rings.values()] } : baseRequest;
    const r = await callValhalla(body);
    if (!r.ok) {
      if (attempt === 0) {
        throw new RouteError(r.status >= 500 ? 502 : r.status, { error: 'Valhalla error', valhalla: r.json });
      }
      if (r.status >= 500) throw new RouteError(502, { error: 'Valhalla error', valhalla: r.json });
      throw new RouteError(422, {
        error: 'no route found that avoids the known TrucksIL restrictions for this vehicle',
        conflicts: [...avoided.values()],
        valhalla: r.json,
      });
    }
    const shape = routeShape(r.json);
    if (shape.length === 0) throw new RouteError(502, { error: 'Valhalla response has no route shape; restrictions cannot be checked' });

    const rows = await repo.findAlongRoute(shape, ROUTE_BUFFER_M);
    const { conflicts, onRoute } = classify(rows, vehicle, now);
    if (conflicts.length === 0) {
      const verifiedOnRoute = onRoute.filter((x) => x.status === 'verified').length;
      return {
        result: r.json,
        trucksil: {
          disclaimer: DISCLAIMER,
          avoided: [...avoided.values()],
          onRoute,
          coverage: { verifiedOnRoute, unverifiedOnRoute: onRoute.length - verifiedOnRoute, note: COVERAGE_NOTE },
          unverifiedCoverage: 'unknown',
          reroutes: attempt,
        },
      };
    }
    if (attempt >= maxReroutes) {
      throw new RouteError(409, {
        error: `route still conflicts with TrucksIL restrictions after ${attempt} re-route attempts`,
        conflicts,
        avoided: [...avoided.values()].filter((a) => !conflicts.some((c) => c.id === a.id)),
      });
    }
    const fresh = conflicts.filter((c) => !rings.has(c.id));
    const polys = await repo.exclusionPolygons(fresh.map((c) => c.id), EXCLUDE_BUFFER_M);
    for (const p of polys) rings.set(p.id, p.ring);
    for (const c of conflicts) avoided.set(c.id, c);
    if (polys.length === 0) {
      // Conflicts already excluded (Valhalla still routes through them) -> cannot make progress.
      throw new RouteError(409, { error: 'route still conflicts with TrucksIL restrictions; exclusion had no effect', conflicts });
    }
    attempt += 1;
  }
}

module.exports = {
  ROUTE_BUFFER_M, EXCLUDE_BUFFER_M, MAX_REROUTES, DISCLAIMER, COVERAGE_NOTE,
  isActiveNow, violation, classify, planRoute, RouteError,
};
