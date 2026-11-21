'use strict';
// Applies TrucksIL's own restrictions to a Valhalla route (stage 2, item 3).
// Policy (ADR-0002): any known conflict is AVOIDED whatever its status (avoiding is always the
// safe direction), but nothing here ever claims a route is safe: absent data is not evidence.
const { routeShape } = require('./polyline');
const { directionApplies, thinExclusionRings } = require('./routeGeometry');

const ROUTE_BUFFER_M = 50; // restriction counts as "on the route" within this distance of the shape
const EXCLUDE_BUFFER_M = 20; // radius of the fallback ("wide") polygon around the restriction (ADR-0011)
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
function classify(rows, vehicle, now = new Date(), shape = null) {
  const conflicts = [];
  const onRoute = [];
  for (const row of rows) {
    if (row.status === 'expired') continue;
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
  // id -> {level: 'thin' | 'wide', rings}. Escalation per conflict (ADR-0011): thin rectangles around the
  // route edge that passed it -> 20 m polygon around the restriction itself -> no progress -> 409.
  const exclusions = new Map();
  let attempt = 0;
  for (;;) {
    const rings = [...exclusions.values()].flatMap((e) => e.rings);
    const body = rings.length ? { ...baseRequest, exclude_polygons: rings } : baseRequest;
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
    const { conflicts, onRoute } = classify(rows, vehicle, now, shape);
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
    let progressed = 0;
    const needWide = [];
    for (const c of conflicts) {
      const prev = exclusions.get(c.id);
      if (!prev) {
        const thin = thinExclusionRings(shape, c.geometry);
        if (thin) { exclusions.set(c.id, { level: 'thin', rings: thin }); progressed += 1; } else needWide.push(c.id);
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
      }
    }
    for (const c of conflicts) avoided.set(c.id, c);
    if (progressed === 0) {
      // Conflicts already excluded at the widest level (Valhalla still routes through them) -> no progress.
      throw new RouteError(409, { error: 'route still conflicts with TrucksIL restrictions; exclusion had no effect', conflicts });
    }
    attempt += 1;
  }
}

module.exports = {
  ROUTE_BUFFER_M, EXCLUDE_BUFFER_M, MAX_REROUTES, DISCLAIMER, COVERAGE_NOTE,
  TUNNEL_CATEGORIES, vehicleTunnelCode, tunnelConflict, isActiveNow, violation, classify, planRoute, RouteError,
};
