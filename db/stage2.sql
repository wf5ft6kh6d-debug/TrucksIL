-- PROPOSED LOCAL STAGING ONLY. Not executed or migration-tested against PostgreSQL.
-- Requires a disposable PostgreSQL database with PostGIS installed by its owner.
-- No application routing, credentials, remote connections, or deployment here.
BEGIN;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS trucksil_stage2;
SET LOCAL search_path = trucksil_stage2, public;

CREATE TABLE IF NOT EXISTS sources (
    source_id text PRIMARY KEY CHECK (length(trim(source_id)) > 0),
    name text NOT NULL,
    reference text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('official','open_mapping','field_survey','user_report','other')),
    authenticated_official boolean NOT NULL DEFAULT false,
    license_identifier text NOT NULL,
    license_reference text NOT NULL,
    license_decision text NOT NULL DEFAULT 'pending' CHECK (license_decision IN ('permitted','pending','denied')),
    license_checked_at timestamptz NOT NULL,
    license_review_due_at timestamptz NOT NULL,
    license_reviewer text NOT NULL,
    license_obligations jsonb NOT NULL DEFAULT '[]'::jsonb,
    CHECK (authenticated_official = (kind = 'official')),
    CHECK (license_review_due_at > license_checked_at),
    CHECK (jsonb_typeof(license_obligations) = 'array')
);

CREATE TABLE IF NOT EXISTS road_nodes (
    node_id text PRIMARY KEY,
    source_id text NOT NULL REFERENCES sources(source_id),
    source_feature_id text NOT NULL,
    source_revision text NOT NULL,
    geometry geometry(Point,4326) NOT NULL,
    topology_status text NOT NULL DEFAULT 'unverified' CHECK (topology_status IN ('unverified','reviewed','disputed')),
    CHECK (ST_IsValid(geometry) AND NOT ST_IsEmpty(geometry)),
    CHECK (ST_X(geometry) BETWEEN -180 AND 180 AND ST_Y(geometry) BETWEEN -90 AND 90)
);
CREATE TABLE IF NOT EXISTS road_segments (
    segment_id text PRIMARY KEY,
    source_id text NOT NULL REFERENCES sources(source_id),
    source_feature_id text NOT NULL,
    source_revision text NOT NULL,
    from_node text NOT NULL REFERENCES road_nodes(node_id),
    to_node text NOT NULL REFERENCES road_nodes(node_id),
    geometry geometry(LineString,4326) NOT NULL,
    direction text NOT NULL DEFAULT 'unknown' CHECK (direction IN ('both','forward','reverse','unknown')),
    topology_status text NOT NULL DEFAULT 'unverified' CHECK (topology_status IN ('unverified','reviewed','disputed')),
    CHECK (ST_IsValid(geometry) AND NOT ST_IsEmpty(geometry) AND ST_NPoints(geometry) >= 2),
    CHECK (ST_XMin(Box3D(geometry)) >= -180 AND ST_XMax(Box3D(geometry)) <= 180),
    CHECK (ST_YMin(Box3D(geometry)) >= -90 AND ST_YMax(Box3D(geometry)) <= 90)
);
CREATE INDEX IF NOT EXISTS road_segments_geometry_idx ON road_segments USING gist (geometry);
-- Endpoint snapping, grade separation, turn restrictions, revision reconciliation
-- and nationwide completeness are NOT inferred from these tables.

CREATE TABLE IF NOT EXISTS restriction_staging (
    restriction_id text PRIMARY KEY,
    source_id text NOT NULL REFERENCES sources(source_id),
    road_segment_id text REFERENCES road_segments(segment_id),
    geometry geometry(Geometry,4326),
    restriction_type text NOT NULL CHECK (restriction_type IN ('max_height','max_width','max_length','max_gross_weight','max_axle_weight','truck_prohibited','hazmat_restriction')),
    value numeric NOT NULL,
    unit text NOT NULL CHECK (unit IN ('m','t','boolean')),
    status text NOT NULL CHECK (status IN ('unverified','verified','disputed','expired')),
    direction text NOT NULL DEFAULT 'unknown' CHECK (direction IN ('both','forward','reverse','unknown')),
    observed_at timestamptz NOT NULL,
    checked_at timestamptz NOT NULL,
    verified_at timestamptz,
    review_due_at timestamptz NOT NULL,
    verifier text NOT NULL,
    independent_reviewer text,
    independently_reviewed_at timestamptz,
    independent_review_decision text CHECK (independent_review_decision IN ('approved','pending','rejected')),
    independent_review_reference text,
    evidence jsonb NOT NULL CHECK (jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0),
    -- Exact validated importer record; protected raw evidence must NOT be copied here.
    validated_record jsonb NOT NULL CHECK (jsonb_typeof(validated_record) = 'object'),
    CHECK (road_segment_id IS NOT NULL OR geometry IS NOT NULL),
    CHECK (geometry IS NULL OR (ST_GeometryType(geometry) IN ('ST_Point','ST_LineString') AND ST_IsValid(geometry) AND NOT ST_IsEmpty(geometry))),
    CHECK (geometry IS NULL OR (ST_XMin(Box3D(geometry)) >= -180 AND ST_XMax(Box3D(geometry)) <= 180 AND ST_YMin(Box3D(geometry)) >= -90 AND ST_YMax(Box3D(geometry)) <= 90)),
    CHECK ((restriction_type IN ('max_height','max_width','max_length') AND unit = 'm' AND value > 0 AND value < 'Infinity'::numeric)
        OR (restriction_type IN ('max_gross_weight','max_axle_weight') AND unit = 't' AND value > 0 AND value < 'Infinity'::numeric)
        OR (restriction_type IN ('truck_prohibited','hazmat_restriction') AND unit = 'boolean' AND value = 1)),
    CHECK (observed_at <= checked_at),
    CHECK (verified_at IS NULL OR (verified_at >= observed_at AND verified_at <= checked_at)),
    CHECK (status <> 'verified' OR (verified_at IS NOT NULL AND direction <> 'unknown'
        AND independent_reviewer IS NOT NULL AND length(trim(independent_reviewer)) > 0
        AND lower(trim(independent_reviewer)) <> lower(trim(verifier))
        AND independently_reviewed_at IS NOT NULL AND independently_reviewed_at BETWEEN verified_at AND checked_at
        AND independent_review_decision IS NOT NULL AND independent_review_decision = 'approved'
        AND independent_review_reference IS NOT NULL AND length(trim(independent_review_reference)) > 0
        AND review_due_at > checked_at))
);
CREATE INDEX IF NOT EXISTS restriction_geometry_idx ON restriction_staging USING gist (geometry);

-- A row is required for EACH restriction dimension and direction under review.
-- Missing row, unknown status or overdue row always means coverage unknown.
CREATE TABLE IF NOT EXISTS coverage_reviews (
    segment_id text NOT NULL REFERENCES road_segments(segment_id),
    dimension text NOT NULL CHECK (dimension IN ('max_height','max_width','max_length','max_gross_weight','max_axle_weight','truck_prohibited','hazmat_restriction','turns','topology','temporary_closures')),
    direction text NOT NULL CHECK (direction IN ('both','forward','reverse','unknown')),
    status text NOT NULL DEFAULT 'unknown' CHECK (status IN ('unknown','partial','reviewed','disputed','expired')),
    source_id text REFERENCES sources(source_id),
    review_reference text,
    reviewer text,
    reviewed_at timestamptz,
    review_due_at timestamptz,
    PRIMARY KEY (segment_id,dimension,direction),
    CHECK (status <> 'reviewed' OR (source_id IS NOT NULL AND review_reference IS NOT NULL
        AND reviewer IS NOT NULL AND reviewed_at IS NOT NULL AND review_due_at IS NOT NULL AND review_due_at > reviewed_at))
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT current_timestamp,
    database_actor text NOT NULL DEFAULT current_user,
    entity_table text NOT NULL,
    entity_id text NOT NULL,
    action text NOT NULL CHECK (action IN ('INSERT','UPDATE','DELETE')),
    note text NOT NULL DEFAULT 'Local staging mutation; no safety certification'
);
CREATE OR REPLACE FUNCTION audit_staging_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE row_data jsonb;
BEGIN
    row_data := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    INSERT INTO trucksil_stage2.audit_events(entity_table,entity_id,action)
    VALUES (TG_TABLE_NAME,coalesce(row_data->>'restriction_id',row_data->>'segment_id',row_data->>'node_id',row_data->>'source_id','unknown'),TG_OP);
    RETURN NULL;
END;
$$;
DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['sources','road_nodes','road_segments','restriction_staging','coverage_reviews'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS staging_audit ON trucksil_stage2.%I',target);
        EXECUTE format('CREATE TRIGGER staging_audit AFTER INSERT OR UPDATE OR DELETE ON trucksil_stage2.%I FOR EACH ROW EXECUTE FUNCTION trucksil_stage2.audit_staging_change()',target);
    END LOOP;
END;
$$;

-- Deliberately NEVER exposes a safe/eligible route predicate.
CREATE OR REPLACE VIEW segment_safety_state AS
SELECT segment_id, 'unknown'::text AS route_suitability, false AS route_safety_certified
FROM road_segments;
COMMIT;
