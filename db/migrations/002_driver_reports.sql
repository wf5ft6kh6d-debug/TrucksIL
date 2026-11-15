-- TrucksIL stage 5: driver reports (ADR-0012).
-- Driver reports are UNVERIFIED crowd hints. They are deliberately kept apart from `restrictions`:
-- no foreign key, no shared view, and they never feed the routing safety check (ADR-0002,
-- docs/DATA_VERIFICATION.md: a user report can never become an official notice by itself).
-- Privacy (US-08): no account, no IP, no raw location history. Only a salted hash of an anonymous
-- client id is stored, to rate-limit and to allow one vote per report.

DO $$ BEGIN
  CREATE TYPE driver_report_type AS ENUM ('traffic', 'accident', 'hazard', 'camera', 'low_clearance', 'other');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE driver_report_status AS ENUM ('pending', 'visible', 'hidden', 'expired');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS driver_reports (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  type           driver_report_type NOT NULL,
  geometry       geometry(Point, 4326) NOT NULL,
  note           text CHECK (note IS NULL OR char_length(note) <= 280),
  created_at     timestamptz NOT NULL DEFAULT now(),
  -- Type-based TTL is computed by the API (api/src/reports.js REPORT_TTL_MS):
  -- traffic 1h, accident 3h, hazard 12h, camera 30d, low_clearance 30d, other 6h.
  expires_at     timestamptz NOT NULL,
  status         driver_report_status NOT NULL DEFAULT 'visible',
  reporter_hash  text NOT NULL CHECK (char_length(reporter_hash) BETWEEN 32 AND 128),
  confirmations  integer NOT NULL DEFAULT 0 CHECK (confirmations >= 0),
  rejections     integer NOT NULL DEFAULT 0 CHECK (rejections >= 0),
  CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS driver_reports_geom_idx ON driver_reports USING gist (geometry);
CREATE INDEX IF NOT EXISTS driver_reports_live_idx ON driver_reports (status, expires_at);

-- One vote per reporter per report. Holds only the salted hash, never a location.
CREATE TABLE IF NOT EXISTS driver_report_votes (
  report_id      uuid NOT NULL REFERENCES driver_reports(id) ON DELETE CASCADE,
  reporter_hash  text NOT NULL,
  vote           text NOT NULL CHECK (vote IN ('confirm', 'reject')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (report_id, reporter_hash)
);

-- Append-only moderation audit (manual hide/show and automatic hides).
CREATE TABLE IF NOT EXISTS report_moderation (
  id          bigserial PRIMARY KEY,
  -- No ON DELETE CASCADE: the audit must outlive any cleanup (reports expire by status, not deletion).
  report_id   uuid NOT NULL REFERENCES driver_reports(id),
  action      text NOT NULL CHECK (action IN ('hide', 'show', 'auto_hide')),
  actor       text NOT NULL,          -- 'moderator' or 'system'; no personal identifiers
  reason      text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION report_moderation_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'report_moderation is append-only';
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS report_moderation_no_update ON report_moderation;
CREATE TRIGGER report_moderation_no_update BEFORE UPDATE OR DELETE ON report_moderation
  FOR EACH ROW EXECUTE FUNCTION report_moderation_append_only();
