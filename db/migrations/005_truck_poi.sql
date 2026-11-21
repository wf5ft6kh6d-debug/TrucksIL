-- Truck parking, rest areas and HGV fuel stations from an OSM extract (ADR-0017). Idempotent.
-- Data is ODbL-derived (OpenStreetMap contributors): it lives ONLY in the local database, is loaded
-- by scripts/import_osm_truck_poi.py and is never committed. Display only, always 'unverified'.
BEGIN;

CREATE TABLE IF NOT EXISTS truck_poi (
  id                  text PRIMARY KEY,               -- osm-poi-<node|way><id>-<kind>
  osm_type            text NOT NULL CHECK (osm_type IN ('node', 'way')),
  osm_id              bigint NOT NULL,
  kind                text NOT NULL CHECK (kind IN ('parking', 'rest_area', 'fuel_hgv')),
  name                text,
  geom                geometry(Point, 4326) NOT NULL,  -- node position or way centroid
  tags                jsonb NOT NULL DEFAULT '{}'::jsonb,
  status              text NOT NULL DEFAULT 'unverified' CHECK (status = 'unverified'),
  source_extract_date timestamptz,
  loaded_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (osm_type, osm_id, kind)
);

CREATE INDEX IF NOT EXISTS truck_poi_geom_idx ON truck_poi USING gist (geom);
CREATE INDEX IF NOT EXISTS truck_poi_kind_idx ON truck_poi (kind);

COMMIT;
