'use strict';
// Route coverage (ADR-0014): which bridges/tunnels on the final route have ANY TrucksIL data.
// Structures come from Valhalla /trace_attributes (edge.bridge / edge.tunnel), so no extra dataset
// is needed. A structure is "covered" when a TrucksIL restriction (any status except expired, as
// returned by repo.findAlongRoute) lies within COVERAGE_BUFFER_M of its geometry; otherwise it is a
// "no data" segment. Failure of any step -> status 'unknown' (never 'ok'): absence of data is not
// evidence of suitability (ADR-0002).
// Known limit: a road passing UNDER a bridge is not flagged by Valhalla edges, so underpasses are
// not counted here (see ADR-0014, later step: route_structures table from OSM).
const { encodePolyline, decodePolyline } = require('./polyline');

const COVERAGE_BUFFER_M = 30;
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

/**
 * Groups consecutive bridge/tunnel edges of the same way into structures.
 * @returns {Array<{type:'bridge'|'tunnel', wayId:number|null, coords:[[lon,lat],...]}>}
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
    if (prev && prev.type === type && prev.wayId === wayId && prev.endIndex === b) {
      prev.coords.push(...coords.slice(1));
      prev.endIndex = en;
    } else {
      out.push({ type, wayId, coords, endIndex: en });
    }
  }
  return out.map(({ endIndex, ...s }) => s);
}

/**
 * @param {object} p
 * @param {Function} p.callTraceAttributes  async (body) -> {ok, status, json}
 * @param {object} p.repo                   restrictions repo with findAlongRoute(coords, bufferM)
 * @param {Array} p.shape                   final route [[lon,lat],...]
 * @param {string} p.note                   coverage note to keep
 */
async function computeCoverage({ callTraceAttributes, repo, shape, note, bufferM = COVERAGE_BUFFER_M }) {
  const unknown = (reason) => ({
    status: 'unknown', reason, structuresOnRoute: null, structuresWithData: null, noDataSegments: null, note,
  });
  if (!Array.isArray(shape) || shape.length < 2) return unknown('route shape missing');
  let structures;
  try {
    const r = await callTraceAttributes(traceAttributesRequest(shape));
    if (!r || !r.ok) return unknown(`trace_attributes failed (HTTP ${r ? r.status : '?'})`);
    structures = structuresFromTrace(r.json, shape);
  } catch (e) {
    return unknown(`trace_attributes failed (${e.message})`);
  }
  const noDataSegments = [];
  let withData = 0;
  try {
    for (const s of structures) {
      const rows = await repo.findAlongRoute(s.coords, bufferM);
      if (rows.length) withData += 1;
      else noDataSegments.push({ type: s.type, from: s.coords[0], to: s.coords.at(-1), wayId: s.wayId, coordinates: s.coords });
    }
  } catch (e) {
    return unknown(`restrictions lookup failed (${e.message})`);
  }
  return {
    status: 'computed',
    structuresOnRoute: structures.length,
    structuresWithData: withData,
    noDataSegments,
    note,
    limits: 'bridges and tunnels on the route only (Valhalla edge flags); roads passing under bridges are not counted',
  };
}

module.exports = { COVERAGE_BUFFER_M, traceAttributesRequest, structuresFromTrace, computeCoverage };
