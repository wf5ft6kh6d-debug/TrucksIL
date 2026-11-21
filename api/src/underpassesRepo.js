'use strict';
// Underpasses on the route (ADR-0014): rows of the local osm_underpasses table (migration 004,
// loaded by scripts/load_osm_underpasses.py; ODbL-derived data, never committed).
//   findOnRoute(wayIds, coords, nearM, bufferM) -> {loaded:false} | {loaded:true, rows:[...]}
// A row matches only when its osm_road_way_id is one of the route's own way ids (the route passes
// UNDER the bridge) AND its crossing point is within nearM of the route line. hasData: any
// non-expired TrucksIL max_height restriction within bufferM of the crossing point (OSM candidates
// imported by scripts/import_osm_maxheight.py included); hasVerifiedData: the same, status 'verified' only.

const PRESENT_SQL = `SELECT to_regclass('public.osm_underpasses') IS NOT NULL AS present`;
const LOADED_SQL = `SELECT EXISTS (SELECT 1 FROM osm_underpasses) AS loaded`;

const ON_ROUTE_SQL = `
WITH route AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON($2), 4326) AS g)
SELECT u.id, u.osm_road_way_id, u.osm_bridge_way_id, u.bridge_kind, u.road_ref, u.road_class,
       u.osm_maxheight_text, u.osm_maxheight_m::float8 AS osm_maxheight_m,
       ST_X(u.geom) AS lon, ST_Y(u.geom) AS lat,
       EXISTS (
         SELECT 1 FROM restrictions r
         WHERE r.restriction_type = 'max_height' AND r.status <> 'expired' AND r.geometry IS NOT NULL
           AND r.geometry && ST_Expand(u.geom, $4::float8 / 50000.0)
           AND ST_DWithin(r.geometry::geography, u.geom::geography, $4::float8)
       ) AS has_data,
       EXISTS (
         SELECT 1 FROM restrictions r
         WHERE r.restriction_type = 'max_height' AND r.status = 'verified' AND r.geometry IS NOT NULL
           AND r.geometry && ST_Expand(u.geom, $4::float8 / 50000.0)
           AND ST_DWithin(r.geometry::geography, u.geom::geography, $4::float8)
       ) AS has_verified_data
FROM osm_underpasses u, route
WHERE u.osm_road_way_id = ANY($1::bigint[])
  AND u.geom && ST_Expand(ST_Envelope(route.g), $3::float8 / 50000.0)
  AND ST_DWithin(u.geom::geography, route.g::geography, $3::float8)
ORDER BY u.id`;

function createUnderpassesRepo(db) {
  return {
    async findOnRoute(wayIds, coords, nearM, bufferM) {
      const { rows: [p] } = await db.query(PRESENT_SQL);
      if (!p || !p.present) return { loaded: false };
      const { rows: [st] } = await db.query(LOADED_SQL);
      if (!st || !st.loaded) return { loaded: false };
      if (!wayIds.length || !Array.isArray(coords) || coords.length < 2) return { loaded: true, rows: [] };
      const line = JSON.stringify({ type: 'LineString', coordinates: coords });
      const { rows } = await db.query(ON_ROUTE_SQL, [wayIds.map(String), line, nearM, bufferM]);
      return {
        loaded: true,
        rows: rows.map((r) => ({
          id: r.id, roadWayId: Number(r.osm_road_way_id), bridgeWayId: Number(r.osm_bridge_way_id),
          bridgeKind: r.bridge_kind, roadRef: r.road_ref, roadClass: r.road_class,
          osmMaxheightText: r.osm_maxheight_text, osmMaxheightM: r.osm_maxheight_m,
          point: [r.lon, r.lat], hasData: r.has_data, hasVerifiedData: r.has_verified_data === true,
        })),
      };
    },
  };
}

module.exports = { createUnderpassesRepo, PRESENT_SQL, LOADED_SQL, ON_ROUTE_SQL };
