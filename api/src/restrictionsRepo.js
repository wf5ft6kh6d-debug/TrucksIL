'use strict';
// PostGIS access for route checks. Kept behind a tiny interface so tests can pass a fake:
//   findAlongRoute(coords [[lon,lat],...], bufferM) -> Promise<row[]>
//   exclusionPolygons(ids string[], bufferM)       -> Promise<[{id, ring:[[lon,lat],...]}]>

// Rows within bufferM metres of the route line. 'expired' is never applied. A 'verified' row whose review is
// overdue (review_due_at in the past) is returned as 'unverified' (ADR-0021): still avoided, never counted as verified. The bbox prefilter
// (geometry && expanded envelope, in degrees, generous for Israel's latitudes) lets the GiST index
// work; ST_DWithin on geography then does the exact metre-based test.
const ALONG_ROUTE_SQL = `
WITH route AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 4326) AS g)
SELECT r.id, r.road_segment_id, r.value_source, r.direction, r.restriction_type, r.value_numeric,
       r.value_boolean, r.value_text, r.unit, r.time_windows,
       CASE WHEN r.status = 'verified' AND r.review_due_at IS NOT NULL AND r.review_due_at < now() THEN 'unverified' ELSE r.status END AS status,
       r.verified_at, r.review_due_at, r.source,
       ST_AsGeoJSON(r.geometry, 7)::json AS geometry
FROM restrictions r, route
WHERE r.geometry IS NOT NULL
  AND r.status <> 'expired'
  AND r.geometry && ST_Expand(ST_Envelope(route.g), $2::float8 / 50000.0)
  AND ST_DWithin(r.geometry::geography, route.g::geography, $2::float8)
ORDER BY r.id`;

// Same query for status 'expired' only. Expired rows never exclude or reroute (ADR-0002): they are
// fetched only to produce warnings when the vehicle would violate them (ADR-0020).
const EXPIRED_ALONG_ROUTE_SQL = ALONG_ROUTE_SQL.replace("r.status <> 'expired'", "r.status = 'expired'");

// Polygon (metre buffer on geography) around each restriction geometry, for Valhalla exclude_polygons.
const EXCLUSION_SQL = `
SELECT id, ST_AsGeoJSON(ST_Buffer(geometry::geography, $2::float8, 'quad_segs=4')::geometry, 7)::json AS polygon
FROM restrictions
WHERE id = ANY($1::text[]) AND geometry IS NOT NULL
ORDER BY id`;

function createRestrictionsRepo(db) {
  return {
    async findAlongRoute(coords, bufferM) {
      if (!Array.isArray(coords) || coords.length === 0) return [];
      const line = coords.length === 1
        ? { type: 'Point', coordinates: coords[0] }
        : { type: 'LineString', coordinates: coords };
      const { rows } = await db.query(ALONG_ROUTE_SQL, [JSON.stringify(line), bufferM]);
      return rows;
    },
    async findExpiredAlongRoute(coords, bufferM) {
      if (!Array.isArray(coords) || coords.length === 0) return [];
      const line = coords.length === 1
        ? { type: 'Point', coordinates: coords[0] }
        : { type: 'LineString', coordinates: coords };
      const { rows } = await db.query(EXPIRED_ALONG_ROUTE_SQL, [JSON.stringify(line), bufferM]);
      return rows;
    },
    async exclusionPolygons(ids, bufferM) {
      if (!ids.length) return [];
      const { rows } = await db.query(EXCLUSION_SQL, [ids, bufferM]);
      return rows.map((r) => ({ id: r.id, ring: r.polygon.coordinates[0] }));
    },
  };
}

module.exports = { createRestrictionsRepo, ALONG_ROUTE_SQL, EXPIRED_ALONG_ROUTE_SQL, EXCLUSION_SQL };
