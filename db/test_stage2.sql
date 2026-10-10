-- SYNTHETIC FIXTURES ONLY. No real road evidence or navigation certification.
-- Execute only after stage2.sql, in a disposable LOCAL database named
-- trucksil_stage2_test_*. ON_ERROR_STOP and ROLLBACK protect fixture isolation.
\set ON_ERROR_STOP on
BEGIN;
DO $$
BEGIN
    IF current_database() !~ '^trucksil_stage2_test_' THEN
        RAISE EXCEPTION 'Requires disposable database named trucksil_stage2_test_*';
    END IF;
    IF inet_server_addr() IS NOT NULL THEN
        RAISE EXCEPTION 'Requires local Unix socket connection; TCP disallowed';
    END IF;
END;
$$;
SET LOCAL search_path = trucksil_stage2, public;

CREATE FUNCTION pg_temp.expect_rejection(statement text, expected_state text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE actual_state text;
BEGIN
    BEGIN
        EXECUTE statement;
    EXCEPTION WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS actual_state = RETURNED_SQLSTATE;
        IF actual_state <> expected_state THEN
            RAISE EXCEPTION 'Expected SQLSTATE %, got % for %', expected_state, actual_state, statement;
        END IF;
        RETURN;
    END;
    RAISE EXCEPTION 'Statement unexpectedly accepted: %', statement;
END;
$$;

INSERT INTO sources VALUES (
    'SYNTHETIC_SOURCE_DO_NOT_USE','Synthetic fixture','urn:trucksil:test:source',
    'field_survey',false,'SYNTHETIC-NO-REAL-DATA','urn:trucksil:test:license',
    'pending','2026-10-01T00:00:00Z','2026-11-01T00:00:00Z','test-reviewer','[]'
);
INSERT INTO road_nodes VALUES
    ('TEST_A','SYNTHETIC_SOURCE_DO_NOT_USE','A','synthetic-v1',ST_SetSRID(ST_MakePoint(34,31),4326),'unverified'),
    ('TEST_B','SYNTHETIC_SOURCE_DO_NOT_USE','B','synthetic-v1',ST_SetSRID(ST_MakePoint(34.001,31.001),4326),'unverified');
INSERT INTO road_segments VALUES (
    'TEST_SEGMENT','SYNTHETIC_SOURCE_DO_NOT_USE','AB','synthetic-v1','TEST_A','TEST_B',
    ST_GeomFromText('LINESTRING(34 31,34.001 31.001)',4326),'unknown','unverified'
);
INSERT INTO restriction_staging (
    restriction_id,source_id,road_segment_id,restriction_type,value,unit,status,
    observed_at,checked_at,review_due_at,verifier,evidence,validated_record
) VALUES (
    'SYNTHETIC_RESTRICTION_DO_NOT_USE','SYNTHETIC_SOURCE_DO_NOT_USE','TEST_SEGMENT',
    'max_height',4,'m','unverified','2026-10-01T00:00:00Z','2026-10-02T00:00:00Z',
    '2026-11-01T00:00:00Z','synthetic-verifier',
    '[{"reference":"urn:trucksil:test:evidence"}]','{"synthetic":true}'
);

SELECT pg_temp.expect_rejection(
    $$UPDATE restriction_staging SET unit='t' WHERE restriction_id='SYNTHETIC_RESTRICTION_DO_NOT_USE'$$,'23514');
SELECT pg_temp.expect_rejection(
    $$UPDATE restriction_staging SET value=0 WHERE restriction_id='SYNTHETIC_RESTRICTION_DO_NOT_USE'$$,'23514');
SELECT pg_temp.expect_rejection(
    $$UPDATE restriction_staging SET value='NaN' WHERE restriction_id='SYNTHETIC_RESTRICTION_DO_NOT_USE'$$,'23514');
SELECT pg_temp.expect_rejection(
    $$UPDATE restriction_staging SET value='Infinity' WHERE restriction_id='SYNTHETIC_RESTRICTION_DO_NOT_USE'$$,'23514');
SELECT pg_temp.expect_rejection(
    $$UPDATE restriction_staging SET road_segment_id=NULL,geometry=NULL WHERE restriction_id='SYNTHETIC_RESTRICTION_DO_NOT_USE'$$,'23514');
SELECT pg_temp.expect_rejection(
    $$UPDATE restriction_staging SET road_segment_id='NONEXISTENT' WHERE restriction_id='SYNTHETIC_RESTRICTION_DO_NOT_USE'$$,'23503');
SELECT pg_temp.expect_rejection(
    $$UPDATE restriction_staging SET status='verified' WHERE restriction_id='SYNTHETIC_RESTRICTION_DO_NOT_USE'$$,'23514');
SELECT pg_temp.expect_rejection(
    $$UPDATE restriction_staging SET geometry=ST_SetSRID(ST_MakePoint(181,31),4326) WHERE restriction_id='SYNTHETIC_RESTRICTION_DO_NOT_USE'$$,'23514');
SELECT pg_temp.expect_rejection(
    $$UPDATE sources SET authenticated_official=true WHERE source_id='SYNTHETIC_SOURCE_DO_NOT_USE'$$,'23514');
SELECT pg_temp.expect_rejection(
    $$INSERT INTO coverage_reviews(segment_id,dimension,direction,status) VALUES ('TEST_SEGMENT','max_height','both','reviewed')$$,'23514');

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM segment_safety_state WHERE segment_id='TEST_SEGMENT'
                   AND route_suitability='unknown' AND route_safety_certified=false) THEN
        RAISE EXCEPTION 'Missing coverage must preserve unknown/false';
    END IF;
    IF (SELECT count(*) FROM audit_events WHERE entity_id IN
        ('SYNTHETIC_SOURCE_DO_NOT_USE','TEST_A','TEST_B','TEST_SEGMENT','SYNTHETIC_RESTRICTION_DO_NOT_USE')) <> 5 THEN
        RAISE EXCEPTION 'Expected exactly 5 successful-insert audit events';
    END IF;
END;
$$;
ROLLBACK;
\echo 'Local synthetic constraint and audit checks passed; fixtures rolled back. NO road safety certification.'
