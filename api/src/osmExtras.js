'use strict';
// OSM-derived extras on the final route (ADR-0017). All of it is informational, status 'unverified',
// ODbL (OpenStreetMap contributors) and never part of the safety check (ADR-0002, ADR-0006).
//  - speedLimits: from Valhalla /trace_attributes edge.speed_limit (OSM maxspeed) and edge.truck_speed
//    (OSM maxspeed:hgv), the SAME memoised call as coverage (ADR-0014). Consecutive edges with equal
//    values are merged; edges without any value are left out (gap = unknown, not "no limit").
//  - lanes: Valhalla returns maneuvers[].lanes itself when the request has turn_lanes: true (lib.js);
//    laneGuidanceInfo only describes it.
//  - poiNearRoute: truck parking / rest areas / HGV fuel from the local truck_poi table (migration 005).

const POI_NEAR_ROUTE_M = 500;
const POI_NEAR_ROUTE_MAX = 50;
const SPEED_NOTE = 'OSM maxspeed / maxspeed:hgv via Valhalla, unverified; gaps = unknown';

function speedValue(v) {
  if (v === 'unlimited') return null;
  const n = Number(v);
  return v != null && Number.isFinite(n) && n > 0 ? Math.round(n) : null;
}

/**
 * @param {object} json trace_attributes response ({edges:[{begin_shape_index,end_shape_index,speed_limit,truck_speed}]})
 * @returns {Array<{fromIndex:number,toIndex:number,kmh:number|null,truckKmh?:number,source:'osm',status:'unverified'}>}
 *   indices are into the traced shape (edge_walk of the route shape, i.e. the route's own polyline).
 */
function speedLimitsFromTrace(json) {
  if (!json || !Array.isArray(json.edges)) throw new Error('trace_attributes: no edges');
  const out = [];
  for (const e of json.edges) {
    const b = Number(e.begin_shape_index);
    const en = Number(e.end_shape_index);
    if (!Number.isInteger(b) || !Number.isInteger(en) || b < 0 || en < b) continue;
    const kmh = speedValue(e.speed_limit);
    const truckKmh = speedValue(e.truck_speed);
    const prev = out.at(-1);
    if (kmh === null && truckKmh === null) continue;
    if (prev && prev.toIndex === b && prev.kmh === kmh && (prev.truckKmh ?? null) === truckKmh) {
      prev.toIndex = en;
      continue;
    }
    const item = { fromIndex: b, toIndex: en, kmh };
    if (truckKmh !== null) item.truckKmh = truckKmh;
    out.push(Object.assign(item, { source: 'osm', status: 'unverified' }));
  }
  return out;
}

/** speedLimits for the route via the (memoised) trace call; null when it failed. */
async function computeSpeedLimits(callTraceAttributes, traceRequest) {
  try {
    const r = await callTraceAttributes(traceRequest);
    if (!r || !r.ok) return null;
    return speedLimitsFromTrace(r.json);
  } catch {
    return null;
  }
}

/** Number of maneuvers with a Valhalla `lanes` array (the arrays themselves stay in trip.legs[].maneuvers). */
function laneGuidanceInfo(result) {
  let n = 0;
  for (const leg of (result && result.trip && result.trip.legs) || []) {
    for (const m of leg.maneuvers || []) if (Array.isArray(m.lanes) && m.lanes.length) n += 1;
  }
  return { maneuversWithLanes: n, where: 'trip.legs[].maneuvers[].lanes', source: 'osm', status: 'unverified' };
}

/** POIs within POI_NEAR_ROUTE_M of the route; null when the table is missing/empty or lookup failed. */
async function poiNearRoute(poiRepo, coords) {
  if (!poiRepo || !Array.isArray(coords) || coords.length < 2) return null;
  try {
    const r = await poiRepo.nearRoute(coords, POI_NEAR_ROUTE_M, POI_NEAR_ROUTE_MAX);
    return r && r.loaded ? r.rows : null;
  } catch {
    return null;
  }
}

module.exports = {
  POI_NEAR_ROUTE_M, POI_NEAR_ROUTE_MAX, SPEED_NOTE,
  speedLimitsFromTrace, computeSpeedLimits, laneGuidanceInfo, poiNearRoute,
};
