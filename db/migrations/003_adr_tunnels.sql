-- ADR tunnel categories as TrucksIL restrictions (ADR-0013). Idempotent: safe to run again.
-- restriction_type 'adr_tunnel', unit 'adr_tunnel_category', value in the new value_text column (B..E).
-- Mirrors data/restrictions.schema.json. Constraint names below replace the auto-generated ones from 001.
BEGIN;

ALTER TABLE restrictions ADD COLUMN IF NOT EXISTS value_text text;

ALTER TABLE restrictions DROP CONSTRAINT IF EXISTS restrictions_restriction_type_check;
ALTER TABLE restrictions ADD CONSTRAINT restrictions_restriction_type_check CHECK (restriction_type IN (
  'max_height', 'max_width', 'max_length', 'max_gross_weight',
  'max_axle_weight', 'truck_prohibited', 'hazmat_restriction', 'adr_tunnel'));

ALTER TABLE restrictions DROP CONSTRAINT IF EXISTS restrictions_unit_check;
ALTER TABLE restrictions ADD CONSTRAINT restrictions_unit_check
  CHECK (unit IN ('m', 't', 'boolean', 'adr_tunnel_category'));

-- 001's "exactly one value column, matching the unit" (auto-named restrictions_check), now with value_text.
ALTER TABLE restrictions DROP CONSTRAINT IF EXISTS restrictions_check;
ALTER TABLE restrictions DROP CONSTRAINT IF EXISTS restrictions_value_column_check;
ALTER TABLE restrictions ADD CONSTRAINT restrictions_value_column_check CHECK (
     (unit = 'boolean' AND value_boolean IS NOT NULL AND value_numeric IS NULL AND value_text IS NULL)
  OR (unit IN ('m', 't') AND value_numeric IS NOT NULL AND value_boolean IS NULL AND value_text IS NULL)
  OR (unit = 'adr_tunnel_category' AND value_text IS NOT NULL AND value_numeric IS NULL AND value_boolean IS NULL));

ALTER TABLE restrictions DROP CONSTRAINT IF EXISTS restrictions_adr_tunnel_check;
ALTER TABLE restrictions ADD CONSTRAINT restrictions_adr_tunnel_check CHECK (
  (restriction_type = 'adr_tunnel') = (unit = 'adr_tunnel_category')
  AND (value_text IS NULL OR value_text IN ('B', 'C', 'D', 'E')));

COMMIT;
