'use strict';
// Truck POIs (ADR-0017): rows of the local truck_poi table (migration 005, loaded by
// scripts/import_osm_truck_poi.py; ODbL-derived, never committed). Always status 'unverified'.
//   inBbox(bbox, kinds) -> {loaded:false} | {loaded:true, rows}
//   nearRoute(coords, withinM, limit) -> {loaded:false} | {loaded:true, rows} (nearest first)
const POI_KINDS = ['parking', 'rest_area', 'fuel_hgv'];
const POI_LABEL = 'OSM, unverified';

const PRESENT_SQL = `SELECT to_regclass('public.truck_poi') IS NOT NULL AS present`;

const COLS = `id, osm_type, osm_id, kind, name, ST_X(geom) AS lon, ST_Y(geom) AS lat, status`;

const BBOX_SQL = `
SELECT ${COLS}
FROM truck_poi
WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326) AND kind = ANY($5::text[])
ORDER BY id
LIMIT 2000`;

const NEAR_ROUTE_SQL = `
WITH route AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 4326) AS g)
SELECT ${COLS}, ST_Distance(p.geom::geography, route.g::geography) AS distance_m
FROM truck_poi p, route
WHERE p.geom && ST_Expand(ST_Envelope(route.g), $2::float8 / 50000.0)
  AND ST_DWithin(p.geom::geography, route.g::geography, $2::float8)
ORDER BY distance_m, id
LIMIT $3`;

function rowToPoi(r) {
  const osmType = r.osm_type;
  const osmId = Number(r.osm_id);
  const p = {
    id: r.id, kind: r.kind, name: r.name ?? null, position: [r.lon, r.lat], status: 'unverified', label: POI_LABEL,
    source: { name: 'OpenStreetMap contributors', license: 'ODbL-1.0', url: `https://www.openstreetmap.org/${osmType}/${osmId}` },
  };
  if (r.distance_m != null) p.distanceM = Math.round(Number(r.distance_m));
  return p;
}

function poiToFeature(p) {
  const { position, ...props } = p;
  return { type: 'Feature', id: p.id, geometry: { type: 'Point', coordinates: position }, properties: props };
}

function createPoiRepo(db) {
  async function present() {
    const { rows: [p] } = await db.query(PRESENT_SQL);
    return Boolean(p && p.present);
  }
  return {
    async inBbox({ minLon, minLat, maxLon, maxLat }, kinds = POI_KINDS) {
      if (!(await present())) return { loaded: false };
      const { rows } = await db.query(BBOX_SQL, [minLon, minLat, maxLon, maxLat, kinds]);
      return { loaded: true, rows: rows.map(rowToPoi) };
    },
    async nearRoute(coords, withinM, limit) {
      if (!(await present())) return { loaded: false };
      const line = JSON.stringify({ type: 'LineString', coordinates: coords });
      const { rows } = await db.query(NEAR_ROUTE_SQL, [line, withinM, limit]);
      return { loaded: true, rows: rows.map(rowToPoi) };
    },
  };
}

/** ?kind=parking,rest_area -> {ok, value:[kinds]} (absent = all kinds). */
function parseKinds(s) {
  if (s == null || s === '') return { ok: true, value: POI_KINDS };
  const kinds = [...new Set(String(s).split(',').map((k) => k.trim()).filter(Boolean))];
  const bad = kinds.filter((k) => !POI_KINDS.includes(k));
  if (!kinds.length || bad.length) return { ok: false, error: `kind must be a comma-separated subset of ${POI_KINDS.join(', ')}` };
  return { ok: true, value: kinds };
}

module.exports = {
  POI_KINDS, POI_LABEL, PRESENT_SQL, BBOX_SQL, NEAR_ROUTE_SQL, createPoiRepo, rowToPoi, poiToFeature, parseKinds,
};
