-- Roads passing under bridges, computed from an OSM extract (ADR-0014). Idempotent.
-- Data is ODbL-derived (OpenStreetMap contributors): it lives ONLY in the local database and is
-- loaded by scripts/load_osm_underpasses.py; it is never committed to the repository.
-- osm_maxheight_* is an "OSM candidate" for display only, never used for routing decisions.
BEGIN;

CREATE TABLE IF NOT EXISTS osm_underpasses (
  id                  bigserial PRIMARY KEY,
  osm_road_way_id     bigint NOT NULL,
  osm_bridge_way_id   bigint NOT NULL,
  bridge_kind         text NOT NULL CHECK (bridge_kind IN ('road', 'rail')),
  geom                geometry(Point, 4326) NOT NULL,
  road_ref            text,
  road_class          text,
  osm_maxheight_text  text,
  osm_maxheight_m     numeric,
  loaded_at           timestamptz NOT NULL DEFAULT now(),
  source_extract_date timestamptz
);

CREATE INDEX IF NOT EXISTS osm_underpasses_geom_idx ON osm_underpasses USING gist (geom);
CREATE INDEX IF NOT EXISTS osm_underpasses_road_way_idx ON osm_underpasses (osm_road_way_id);

COMMIT;
