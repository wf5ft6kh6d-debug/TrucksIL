-- TrucksIL initial schema. Mirrors data/restrictions.schema.json (draft).
-- Absence of a restriction is NOT evidence that a road is suitable (ADR-0002).
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE restrictions (
  id               text PRIMARY KEY,
  road_segment_id  text NOT NULL,
  geometry         geometry(Geometry, 4326)
                   CHECK (geometry IS NULL OR GeometryType(geometry) IN ('POINT', 'LINESTRING')),
  value_source     text CHECK (value_source IN ('posted_sign', 'measured', 'regulation', 'derived', 'unknown')),
  direction        text NOT NULL DEFAULT 'both' CHECK (direction IN ('both', 'forward', 'backward')),
  restriction_type text NOT NULL CHECK (restriction_type IN (
                     'max_height', 'max_width', 'max_length', 'max_gross_weight',
                     'max_axle_weight', 'truck_prohibited', 'hazmat_restriction')),
  value_numeric    double precision,
  value_boolean    boolean,
  unit             text NOT NULL CHECK (unit IN ('m', 't', 'boolean')),
  time_windows     jsonb CHECK (time_windows IS NULL OR jsonb_typeof(time_windows) = 'array'),
  status           text NOT NULL CHECK (status IN ('unverified', 'verified', 'disputed', 'expired')),
  source           jsonb NOT NULL CHECK (source ? 'name' AND source ? 'reference'),
  observed_at      timestamptz NOT NULL,
  verified_by      text,
  verified_at      timestamptz,
  review_due_at    timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  -- exactly one value column, matching the unit
  CHECK ((unit = 'boolean' AND value_boolean IS NOT NULL AND value_numeric IS NULL)
      OR (unit IN ('m', 't') AND value_numeric IS NOT NULL AND value_boolean IS NULL)),
  CHECK (value_numeric IS NULL OR (value_numeric > 0 AND value_numeric <= 200)),
  CHECK (restriction_type NOT IN ('max_height', 'max_width', 'max_length')
         OR (unit = 'm' AND value_source IS NOT NULL AND value_numeric <= 50)),
  CHECK (restriction_type NOT IN ('max_gross_weight', 'max_axle_weight') OR unit = 't'),
  CHECK (restriction_type NOT IN ('truck_prohibited', 'hazmat_restriction') OR unit = 'boolean'),
  -- status 'verified' requires verifier and date (docs/DATA_VERIFICATION.md)
  CHECK (status <> 'verified' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL))
);

CREATE INDEX restrictions_geometry_gix ON restrictions USING gist (geometry);
CREATE INDEX restrictions_segment_idx ON restrictions (road_segment_id);
CREATE INDEX restrictions_status_idx ON restrictions (status);

-- Append-only audit trail of every change to a restriction.
CREATE TABLE restriction_events (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  restriction_id text NOT NULL,
  event_type     text NOT NULL CHECK (event_type IN ('insert', 'update', 'delete')),
  old_row        jsonb,
  new_row        jsonb,
  actor          text,
  occurred_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX restriction_events_restriction_idx ON restriction_events (restriction_id, occurred_at);

CREATE FUNCTION restrictions_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    NEW.updated_at := now();
  END IF;
  INSERT INTO restriction_events (restriction_id, event_type, old_row, new_row, actor)
  VALUES (
    CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END,
    lower(TG_OP),
    CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END,
    CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) END,
    current_setting('trucksil.actor', true)
  );
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER restrictions_audit_trg
  BEFORE INSERT OR UPDATE OR DELETE ON restrictions
  FOR EACH ROW EXECUTE FUNCTION restrictions_audit();
