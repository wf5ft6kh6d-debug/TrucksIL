// Maps POST /v1/route outcomes to a view model. Pure: no DOM, no fetch.
// Safety rule (ADR-0002): only a 200 response ever yields route geometry. 409/422 show conflicts
// and never a route; every other status shows an error and no route.
import { routeShape } from '../../api/src/polyline.mjs';

/** Representative [lon, lat] for a GeoJSON geometry (marker position), or null. */
export function markerPosition(geometry) {
  if (!geometry || typeof geometry !== 'object') return null;
  const c = geometry.coordinates;
  const ok = (p) => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]);
  switch (geometry.type) {
    case 'Point': return ok(c) ? [c[0], c[1]] : null;
    case 'LineString': case 'MultiPoint': return Array.isArray(c) && c.length && ok(c[Math.floor((c.length - 1) / 2)]) ? c[Math.floor((c.length - 1) / 2)].slice(0, 2) : null;
    case 'Polygon': case 'MultiLineString': {
      const ring = Array.isArray(c) ? c[0] : null;
      if (!Array.isArray(ring) || !ring.length || !ring.every(ok)) return null;
      const pts = ring.length > 1 && ring[0][0] === ring.at(-1)[0] && ring[0][1] === ring.at(-1)[1] ? ring.slice(0, -1) : ring;
      return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];
    }
    default: return null;
  }
}

/**
 * One restriction item for display. The value is shown exactly as the API returned it
 * (no rounding, no unit conversion), with the unit next to it.
 */
export function restrictionItem(r, kind) {
  const isBool = typeof r.value === 'boolean';
  return {
    id: String(r.id),
    kind, // 'avoided' | 'onRoute' | 'conflict'
    restrictionType: r.restrictionType,
    typeKey: `type.${r.restrictionType}`,
    valueText: isBool ? null : `${String(r.value)} ${r.unit}`,
    valueBoolKey: isBool ? `value.${r.value}` : null,
    valueSourceKey: `source.${r.valueSource || 'unknown'}`,
    status: r.status,
    statusKey: `status.${r.status}`,
    reason: r.reason || null,
    position: markerPosition(r.geometry),
  };
}

const list = (a, kind) => (Array.isArray(a) ? a.map((r) => restrictionItem(r, kind)) : []);

/**
 * @param {number|null} status  HTTP status, or null for a network failure
 * @param {object|null} body    parsed JSON body (may be null)
 */
export function routeViewModel(status, body) {
  const b = body && typeof body === 'object' ? body : {};
  const base = { route: null, summary: null, avoided: [], onRoute: [], conflicts: [], coverage: null, error: null };
  if (status === 200) {
    const ts = b.trucksil || {};
    let coords = [];
    try { coords = routeShape(b); } catch { coords = []; }
    if (!coords.length) {
      // A 200 without a decodable shape is treated as an error: nothing checked can be shown.
      return { ...base, kind: 'error', error: { key: 'err.502', status, message: 'route shape missing or invalid', details: [] } };
    }
    const s = b.trip && b.trip.summary;
    return {
      ...base,
      kind: 'route',
      route: coords,
      summary: s ? { km: Number(s.length).toFixed(1), min: Math.round(Number(s.time) / 60), reroutes: ts.reroutes ?? 0 } : null,
      avoided: list(ts.avoided, 'avoided'),
      onRoute: list(ts.onRoute, 'onRoute'),
      coverage: ts.coverage ? {
        verified: ts.coverage.verifiedOnRoute ?? 0,
        unverified: ts.coverage.unverifiedOnRoute ?? 0,
        note: ts.coverage.note || null,
      } : null,
    };
  }
  const message = typeof b.error === 'string' ? b.error : null;
  if (status === 409 || status === 422) {
    return {
      ...base,
      kind: 'conflict',
      conflicts: list(b.conflicts, 'conflict'),
      avoided: list(b.avoided, 'avoided'),
      error: { key: `err.${status}`, status, message, details: [] },
    };
  }
  let key = 'err.other';
  if (status === null || status === undefined) key = 'err.network';
  else if ([400, 502, 503].includes(status)) key = `err.${status}`;
  return {
    ...base,
    kind: 'error',
    error: { key, status: status ?? null, message, details: Array.isArray(b.details) ? b.details.map(String) : [] },
  };
}

/** GeoJSON FeatureCollection of marker points for a view model. */
export function markersGeoJSON(vm) {
  const features = [];
  for (const it of [...vm.avoided, ...vm.onRoute, ...vm.conflicts]) {
    if (!it.position) continue;
    features.push({ type: 'Feature', geometry: { type: 'Point', coordinates: it.position }, properties: { id: it.id, kind: it.kind, status: it.status } });
  }
  return { type: 'FeatureCollection', features };
}
