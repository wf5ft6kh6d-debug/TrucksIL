-- NOT EXECUTED in Work. Run after migrate_stage2.py in a disposable local DB.
\set ON_ERROR_STOP on
BEGIN;
DO $$ BEGIN
 IF current_database() !~ '^trucksil_stage2_test_' OR inet_server_addr() IS NOT NULL THEN
  RAISE EXCEPTION 'Disposable local Unix-socket database required';
 END IF;
END $$;
SET LOCAL search_path=trucksil_stage2,public;
CREATE FUNCTION pg_temp.reject(stmt text, state text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE got text;
BEGIN
 BEGIN EXECUTE stmt;
 EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS got=RETURNED_SQLSTATE;
  IF got<>state THEN RAISE EXCEPTION 'Expected %, got %',state,got; END IF;
  RETURN;
 END;
 RAISE EXCEPTION 'Unexpectedly accepted: %',stmt;
END $$;
SELECT pg_temp.reject('INSERT INTO restriction_staging DEFAULT VALUES','42501');
SELECT pg_temp.reject('UPDATE restriction_staging SET status=''verified''','42501');
SELECT pg_temp.reject('DELETE FROM restriction_staging','42501');
SELECT pg_temp.reject('TRUNCATE restriction_staging','42501');
SELECT pg_temp.reject('UPDATE audit_events SET note=''tamper''','42501');
SELECT pg_temp.reject('DELETE FROM audit_events','42501');
SELECT pg_temp.reject('TRUNCATE audit_events','42501');
INSERT INTO sources VALUES ('TEST_S','Synthetic','urn:test','field_survey',false,
 'test','urn:license','pending','2026-10-01T00:00:00Z','2026-11-01T00:00:00Z','fixture','[]');
UPDATE sources SET name='Synthetic updated' WHERE source_id='TEST_S';
INSERT INTO road_nodes VALUES
 ('TEST_A','TEST_S','a','v1',ST_GeomFromText('POINT(34 31)',4326),'unverified'),
 ('TEST_B','TEST_S','b','v1',ST_GeomFromText('POINT(35 32)',4326),'unverified');
INSERT INTO road_segments VALUES
 ('TEST_AB','TEST_S','ab','v1','TEST_A','TEST_B',ST_GeomFromText('LINESTRING(34 31,35 32)',4326),'both','unverified');
SELECT pg_temp.reject('UPDATE road_segments SET source_revision=''v2'' WHERE segment_id=''TEST_AB''','23514');
SELECT pg_temp.reject('UPDATE road_segments SET geometry=ST_GeomFromText(''LINESTRING(34 31,36 33)'',4326) WHERE segment_id=''TEST_AB''','23514');
SELECT pg_temp.reject('UPDATE road_nodes SET source_revision=''v2'' WHERE node_id=''TEST_A''','23514');
INSERT INTO coverage_reviews(segment_id,dimension,direction) VALUES ('TEST_AB','max_height','both');
UPDATE coverage_reviews SET status='partial' WHERE segment_id='TEST_AB';
DELETE FROM coverage_reviews WHERE segment_id='TEST_AB';
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM audit_events WHERE entity_table='sources' AND action='UPDATE'
  AND old_row->>'name'='Synthetic' AND new_row->>'name'='Synthetic updated'
  AND session_actor=session_user AND transaction_id=txid_current()) THEN
  RAISE EXCEPTION 'Before/after source audit missing'; END IF;
 IF NOT EXISTS (SELECT 1 FROM audit_events WHERE entity_table='coverage_reviews' AND action='DELETE'
  AND entity_key='{"segment_id":"TEST_AB","dimension":"max_height","direction":"both"}'::jsonb
  AND old_row->>'status'='partial' AND new_row IS NULL) THEN
  RAISE EXCEPTION 'Composite key/delete audit missing'; END IF;
 IF NOT EXISTS (SELECT 1 FROM segment_safety_state WHERE segment_id='TEST_AB'
  AND route_suitability='unknown' AND route_safety_certified=false) THEN
  RAISE EXCEPTION 'Unsafe route state'; END IF;
END $$;
ROLLBACK;
\echo 'Hardening candidate checks passed; all fixtures rolled back.'
