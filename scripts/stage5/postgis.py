"""Generate standalone transactional research acceptance; never an operational migration."""
import json
from pathlib import Path
from scripts.stage5.contract import canonical, validate_record

HEADER = r'''\set ON_ERROR_STOP on
DO $$ BEGIN
 IF current_database() !~ '^trucksil_stage5_test_[a-z0-9_]+$' OR inet_server_addr() IS NOT NULL THEN
  RAISE EXCEPTION 'Requires isolated local trucksil_stage5_test_ database';
 END IF;
END $$;
BEGIN;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA trucksil_stage5_test;
SET LOCAL search_path=trucksil_stage5_test,public;
CREATE TABLE sources(source_id text PRIMARY KEY, payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'));
CREATE TABLE records(
 record_id text PRIMARY KEY, source_id text NOT NULL REFERENCES sources,
 status text NOT NULL CHECK(status IN ('QUARANTINE','UNKNOWN')),
 navigation_eligible boolean NOT NULL CHECK(navigation_eligible=false),
 synthetic boolean NOT NULL, payload jsonb NOT NULL,
 geom geometry(Geometry,4326),
 CHECK((jsonb_typeof(payload)='object' AND payload ?& ARRAY['schema_version','record_id','kind','source','raw','interpretation','reasons','status','geometry','synthetic','navigation_eligible']) IS TRUE),
 CHECK((payload->>'schema_version'='stage5.research.v1') IS TRUE),
 CHECK((payload->>'kind' IN ('bridge','barrier','transport_rule','conditional','turn','scenario')) IS TRUE),
 CHECK((payload->>'record_id'=record_id) IS TRUE),
 CHECK((payload->>'status'=status) IS TRUE),
 CHECK((jsonb_typeof(payload->'navigation_eligible')='boolean' AND (payload->>'navigation_eligible')::boolean=false) IS TRUE),
 CHECK((jsonb_typeof(payload->'synthetic')='boolean' AND (payload->>'synthetic')::boolean=synthetic) IS TRUE),
 CHECK((jsonb_typeof(payload->'source')='object' AND payload->'source'->>'source_id'=source_id) IS TRUE),
 CHECK((jsonb_typeof(payload->'raw')='object') IS TRUE),
 CHECK((jsonb_typeof(payload->'interpretation')='object') IS TRUE),
 CHECK((CASE WHEN jsonb_typeof(payload->'reasons')='array' THEN jsonb_array_length(payload->'reasons')>0 ELSE false END) IS TRUE),
 CHECK((CASE WHEN payload->'geometry'='null'::jsonb THEN geom IS NULL
  WHEN jsonb_typeof(payload->'geometry')='object' AND geom IS NOT NULL THEN
   ST_OrderingEquals(geom,ST_SetSRID(ST_GeomFromGeoJSON((payload->'geometry')::text),4326))
  ELSE false END) IS TRUE),
 CHECK(geom IS NULL OR (ST_IsValid(geom) AND NOT ST_IsEmpty(geom) AND
 ST_GeometryType(geom) IN ('ST_Point','ST_LineString') AND
 ST_XMin(Box3D(geom))>=-180 AND ST_XMax(Box3D(geom))<=180 AND
 ST_YMin(Box3D(geom))>=-90 AND ST_YMax(Box3D(geom))<=90)));
CREATE FUNCTION guard_source_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE registered jsonb;
BEGIN
 SELECT payload INTO registered FROM sources WHERE source_id=NEW.source_id;
 IF registered IS NULL THEN RAISE EXCEPTION 'missing source' USING ERRCODE='23503'; END IF;
 IF NEW.payload->'source' IS DISTINCT FROM registered THEN RAISE EXCEPTION 'source provenance mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_identity BEFORE INSERT OR UPDATE ON records FOR EACH ROW EXECUTE FUNCTION guard_source_identity();
CREATE FUNCTION immutable_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'source registry immutable; use new source ID' USING ERRCODE='42501'; END $$;
CREATE TRIGGER source_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON sources FOR EACH STATEMENT EXECUTE FUNCTION immutable_source();
CREATE INDEX records_geom_gist ON records USING gist(geom);
CREATE TABLE audit(event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, record_id text NOT NULL, action text NOT NULL, old_row jsonb, new_row jsonb);
CREATE FUNCTION log_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO audit(record_id,action,old_row,new_row) VALUES(coalesce(NEW.record_id,OLD.record_id),TG_OP,to_jsonb(OLD),to_jsonb(NEW));
 RETURN NULL;
END $$;
CREATE TRIGGER record_audit AFTER INSERT OR UPDATE OR DELETE ON records FOR EACH ROW EXECUTE FUNCTION log_change();
CREATE FUNCTION forbid_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'append-only audit' USING ERRCODE='42501'; END $$;
CREATE TRIGGER protect_audit BEFORE UPDATE OR DELETE OR TRUNCATE ON audit FOR EACH STATEMENT EXECUTE FUNCTION forbid_audit_mutation();
CREATE TEMP TABLE incoming(payload jsonb NOT NULL);
COPY incoming(payload) FROM stdin;
'''

INSERT = '''DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM incoming i JOIN records r ON r.record_id=i.payload->>'record_id' WHERE r.payload IS DISTINCT FROM i.payload) THEN
  RAISE EXCEPTION 'conflicting identity replay';
 END IF;
END $$;
INSERT INTO records(record_id,source_id,status,navigation_eligible,synthetic,payload,geom)
SELECT payload->>'record_id',payload->'source'->>'source_id',payload->>'status',
(payload->>'navigation_eligible')::boolean,(payload->>'synthetic')::boolean,payload,
CASE WHEN payload->'geometry' <> 'null'::jsonb THEN ST_SetSRID(ST_GeomFromGeoJSON((payload->'geometry')::text),4326) END
FROM incoming ON CONFLICT(record_id) DO NOTHING;
'''

def generate(records_path, output):
    count = 0
    with open(output,'w',encoding='utf-8') as dest:
        dest.write(HEADER)
        with open(records_path,encoding='utf-8') as rows:
            for line in rows:
                row=validate_record(json.loads(line)); count+=1
                # PostgreSQL text COPY unescapes backslashes; preserve JSON exactly.
                dest.write(canonical(row).replace('\\','\\\\').replace('\t','\\t').replace('\n','\\n').replace('\r','\\r')+'\n')
        dest.write('\\.\n')
        dest.write('''DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM incoming GROUP BY payload->>'record_id' HAVING count(*)>1) THEN RAISE EXCEPTION 'duplicate identity'; END IF;
 IF EXISTS(SELECT 1 FROM incoming GROUP BY payload->'source'->>'source_id' HAVING count(DISTINCT payload->'source')>1) THEN RAISE EXCEPTION 'source identity conflict'; END IF;
END $$;
INSERT INTO sources SELECT DISTINCT payload->'source'->>'source_id',payload->'source' FROM incoming;
''')
        dest.write(INSERT)
        dest.write(INSERT)
        dest.write(f'''DO $$ BEGIN
 IF (SELECT count(*) FROM records)<>{count} OR (SELECT count(*) FROM audit)<>{count} THEN RAISE EXCEPTION 'count or idempotent audit mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM incoming i LEFT JOIN records r ON r.record_id=i.payload->>'record_id' WHERE r.payload IS DISTINCT FROM i.payload) THEN RAISE EXCEPTION 'full row mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM records WHERE geom IS NOT NULL AND NOT ST_Equals(geom,ST_SetSRID(ST_GeomFromGeoJSON((payload->'geometry')::text),4326))) THEN RAISE EXCEPTION 'geometry mismatch'; END IF;
END $$;
''')
        dest.write(r'''-- Constraint and audit failure probes execute inside subtransactions.
DO $$ DECLARE sample records; n bigint; required_key text; before_payload jsonb; after_payload jsonb; BEGIN
 SELECT * INTO sample FROM records ORDER BY record_id LIMIT 1;
 IF sample.record_id IS NULL THEN RAISE EXCEPTION 'nonempty acceptance corpus required'; END IF;
 BEGIN UPDATE records SET status='VERIFIED' WHERE record_id=sample.record_id; RAISE EXCEPTION 'VERIFIED accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET navigation_eligible=true WHERE record_id=sample.record_id; RAISE EXCEPTION 'navigation allowed'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET source_id='missing-source',payload=jsonb_set(payload,'{source,source_id}','"missing-source"') WHERE record_id=sample.record_id; RAISE EXCEPTION 'missing FK accepted'; EXCEPTION WHEN foreign_key_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{source,sha256}','"forged"') WHERE record_id=sample.record_id; RAISE EXCEPTION 'source hash tampering accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE sources SET payload='{}'; RAISE EXCEPTION 'source registry mutation accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE records SET geom=CASE WHEN geom IS NULL THEN ST_SetSRID(ST_MakePoint(0,0),4326) ELSE ST_Translate(geom,0.001,0.001) END WHERE record_id=sample.record_id; RAISE EXCEPTION 'geometry divergence accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE audit SET action='forged'; RAISE EXCEPTION 'audit mutation accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 FOREACH required_key IN ARRAY ARRAY['status','source','raw','interpretation','reasons','navigation_eligible','synthetic'] LOOP
  BEGIN UPDATE records SET payload=payload-required_key WHERE record_id=sample.record_id; RAISE EXCEPTION 'missing required key accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN UPDATE records SET payload=jsonb_set(payload,ARRAY[required_key],'null') WHERE record_id=sample.record_id; RAISE EXCEPTION 'null required key accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 END LOOP;
 SELECT count(*) INTO n FROM audit;
 SELECT payload INTO before_payload FROM records WHERE record_id=sample.record_id;
 UPDATE records SET payload=jsonb_set(payload,'{interpretation,audit_probe}','true') WHERE record_id=sample.record_id;
 SELECT payload INTO after_payload FROM records WHERE record_id=sample.record_id;
 IF (SELECT count(*) FROM audit)<>n+1 OR NOT EXISTS(SELECT 1 FROM audit WHERE action='UPDATE' AND old_row->'payload'=before_payload AND new_row->'payload'=after_payload) THEN RAISE EXCEPTION 'update audit missing'; END IF;
 UPDATE records SET payload=before_payload WHERE record_id=sample.record_id;
END $$;
ANALYZE records;
SET LOCAL enable_seqscan=off;
DO $$ DECLARE plan json; BEGIN
 EXECUTE 'EXPLAIN (FORMAT JSON) SELECT record_id FROM records WHERE geom && ST_MakeEnvelope(34,31,35,32,4326)' INTO plan;
 IF position('records_geom_gist' in plan::text)=0 THEN RAISE EXCEPTION 'GiST not usable'; END IF;
END $$;
SELECT count(*) AS full_row_count, count(geom) AS spatial_records FROM records;
ROLLBACK;
DO $$ BEGIN IF to_regnamespace('trucksil_stage5_test') IS NOT NULL THEN RAISE EXCEPTION 'rollback failed'; END IF; END $$;
SELECT 'STAGE5_POSTGIS_PASS' AS result;
''')
    return count
