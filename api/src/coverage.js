'use strict';
// Route coverage (ADR-0014): which bridges/tunnels on the final route have ANY TrucksIL data.
// Structures come from Valhalla /trace_attributes (edge.bridge / edge.tunnel), so no extra dataset
// is needed. A structure is "covered" when a TrucksIL restriction (any status except expired, as
// returned by repo.findAlongRoute) lies within COVERAGE_BUFFER_M of its geometry; otherwise it is a
// "no data" segment. Failure of any step -> status 'unknown' (never 'ok'): absence of data is not
// evidence of suitability (ADR-0002).
// Underpasses (road passing UNDER a bridge) are not flagged by Valhalla edges; they come from the
// local osm_underpasses table (migration 004, scripts/load_osm_underpasses.py), matched by the
// route's own OSM way ids (never by distance alone, which would also catch bridges passing over
// roads the route uses). OSM maxheight is reported only as an "OSM candidate", never used to route.
// OSM height limits imported into `restrictions` (scripts/import_osm_maxheight.py, status 'unverified')
// DO count as "with data" (and are avoided by routing, ADR-0002); *WithVerifiedData counts only
// structures/underpasses that have at least one status 'verified' restriction, so clients can tell
// verified data from OSM candidates.
const { encodePolyline, decodePolyline } = require('./polyline');

const COVERAGE_BUFFER_M = 30;
const MERGE_GAP_M = 20;        // adjacent structure edges closer than this are one structure
const UNDERPASS_NEAR_M = 15;   // crossing point must be this close to the route line
const ATTRIBUTES = ['edge.bridge', 'edge.tunnel', 'edge.way_id', 'edge.begin_shape_index', 'edge.end_shape_index', 'shape'];

/** Valhalla /trace_attributes request for an exact route shape ([[lon,lat],...]). */
function traceAttributesRequest(coords) {
  return {
    encoded_polyline: encodePolyline(coords),
    shape_match: 'edge_walk',
    costing: 'truck',
    filters: { attributes: ATTRIBUTES, action: 'include' },
  };
}

function haversineM(a, b) {
  const R = 6371008.8, rad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * rad, dLon = (b[0] - a[0]) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/**
 * Groups bridge/tunnel edges into structures: consecutive edges of the same type that are
 * contiguous along the route (end shape index == next begin, or gap < MERGE_GAP_M) are merged
 * regardless of OSM way. wayId is the first way (backward compatible); wayIds lists all.
 * @returns {Array<{type:'bridge'|'tunnel', wayId:number|null, wayIds:number[], coords:[[lon,lat],...]}>}
 */
function structuresFromTrace(json, fallbackShape) {
  if (!json || !Array.isArray(json.edges)) throw new Error('trace_attributes: no edges');
  let shape = fallbackShape;
  if (typeof json.shape === 'string' && json.shape) shape = decodePolyline(json.shape);
  const out = [];
  for (const e of json.edges) {
    const type = e.tunnel ? 'tunnel' : e.bridge ? 'bridge' : null;
    if (!type) continue;
    const b = Number(e.begin_shape_index);
    const en = Number(e.end_shape_index);
    if (!Number.isInteger(b) || !Number.isInteger(en) || b < 0 || en < b || en >= shape.length) {
      throw new Error('trace_attributes: bad shape index');
    }
    const coords = shape.slice(b, en + 1);
    const wayId = e.way_id ?? null;
    const prev = out.at(-1);
    if (prev && prev.type === type && (prev.endIndex === b || (b > prev.endIndex
        && haversineM(prev.coords.at(-1), coords[0]) < MERGE_GAP_M))) {
      prev.coords.push(...(prev.endIndex === b ? coords.slice(1) : coords));
      prev.endIndex = en;
      if (wayId !== null && !prev.wayIds.includes(wayId)) prev.wayIds.push(wayId);
    } else {
      out.push({ type, wayId, wayIds: wayId === null ? [] : [wayId], coords, endIndex: en });
    }
  }
  return out.map(({ endIndex, ...s }) => s);
}

/** All OSM way ids the route travels on (any edge), as numbers. */
function routeWayIds(json) {
  const ids = new Set();
  for (const e of (json && json.edges) || []) {
    const w = Number(e.way_id);
    if (e.way_id != null && Number.isSafeInteger(w) && w > 0) ids.add(w);
  }
  return [...ids];
}

/**
 * Underpasses on the route. underpassRepo.findOnRoute(wayIds, shape, nearM, bufferM) ->
 *   {loaded:false} | {loaded:true, rows:[{point:[lon,lat], roadRef, osmMaxheightText, osmMaxheightM, hasData}]}
 */
async function computeUnderpasses(underpassRepo, wayIds, shape) {
  const empty = { underpassesOnRoute: null, underpassesWithData: null, underpassesWithVerifiedData: null, noDataUnderpasses: null };
  if (!underpassRepo) return { underpassStatus: 'not_loaded', ...empty };
  let r;
  try {
    r = await underpassRepo.findOnRoute(wayIds, shape, UNDERPASS_NEAR_M, COVERAGE_BUFFER_M);
  } catch (e) {
    return { underpassStatus: 'unknown', underpassReason: `underpass lookup failed (${e.message})`, ...empty };
  }
  if (!r || !r.loaded) return { underpassStatus: 'not_loaded', ...empty };
  const noData = r.rows.filter((u) => !u.hasData).map((u) => ({
    point: u.point,
    roadRef: u.roadRef ?? null,
    osmMaxheightCandidate: u.osmMaxheightText == null ? null
      : { text: u.osmMaxheightText, metres: u.osmMaxheightM ?? null, note: 'OSM candidate, not used for routing' },
  }));
  return {
    underpassStatus: 'computed',
    underpassesOnRoute: r.rows.length,
    underpassesWithData: r.rows.length - noData.length,
    underpassesWithVerifiedData: r.rows.filter((u) => u.hasData && u.hasVerifiedData === true).length,
    noDataUnderpasses: noData,
  };
}

/**
 * @param {object} p
 * @param {Function} p.callTraceAttributes  async (body) -> {ok, status, json}
 * @param {object} p.repo                   restrictions repo with findAlongRoute(coords, bufferM)
 * @param {Array} p.shape                   final route [[lon,lat],...]
 * @param {string} p.note                   coverage note to keep
 */
async function computeCoverage({ callTraceAttributes, repo, underpassRepo, shape, note, bufferM = COVERAGE_BUFFER_M }) {
  const unknown = (reason) => ({
    status: 'unknown', reason, structuresOnRoute: null, structuresWithData: null, structuresWithVerifiedData: null,
    noDataSegments: null, note, underpassStatus: 'unknown', underpassesOnRoute: null, underpassesWithData: null,
    underpassesWithVerifiedData: null, noDataUnderpasses: null,
  });
  if (!Array.isArray(shape) || shape.length < 2) return unknown('route shape missing');
  let structures;
  let wayIds;
  try {
    const r = await callTraceAttributes(traceAttributesRequest(shape));
    if (!r || !r.ok) return unknown(`trace_attributes failed (HTTP ${r ? r.status : '?'})`);
    structures = structuresFromTrace(r.json, shape);
    wayIds = routeWayIds(r.json);
  } catch (e) {
    return unknown(`trace_attributes failed (${e.message})`);
  }
  const noDataSegments = [];
  let withData = 0;
  let withVerified = 0;
  try {
    for (const s of structures) {
      const rows = await repo.findAlongRoute(s.coords, bufferM);
      if (rows.some((x) => x.status === 'verified')) withVerified += 1;
      if (rows.length) withData += 1;
      else noDataSegments.push({ type: s.type, from: s.coords[0], to: s.coords.at(-1), wayId: s.wayId, wayIds: s.wayIds, coordinates: s.coords });
    }
  } catch (e) {
    return unknown(`restrictions lookup failed (${e.message})`);
  }
  const under = await computeUnderpasses(underpassRepo, wayIds, shape);
  return {
    status: 'computed',
    structuresOnRoute: structures.length,
    structuresWithData: withData,
    structuresWithVerifiedData: withVerified,
    noDataSegments,
    ...under,
    note,
    limits: under.underpassStatus === 'computed'
      ? 'bridges/tunnels from Valhalla edge flags; underpasses from local OSM extract (osm_underpasses), matched by route way id'
      : 'bridges and tunnels on the route only (Valhalla edge flags); underpasses not loaded (osm_underpasses empty or missing)',
  };
}

module.exports = {
  COVERAGE_BUFFER_M, MERGE_GAP_M, UNDERPASS_NEAR_M, traceAttributesRequest, structuresFromTrace,
  routeWayIds, computeUnderpasses, computeCoverage,
};
