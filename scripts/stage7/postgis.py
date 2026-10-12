"""Reuse the audited transactional SQL gate with lossless stage7 payloads.

Stage7 semantic validation occurs before wrapping; SQL validates the stage6
storage envelope/provenance. SQL/Python semantic equivalence is not claimed.
"""
import hashlib
import json
import tempfile
from pathlib import Path
from scripts.stage6 import postgis as storage
from scripts.stage6.contract import make_record
from scripts.stage7.contract import canonical, validate_record, validate_source

def generate(records, sources, output):
    output=Path(output)
    if output.exists() or output.is_symlink():raise ValueError('Output already exists')
    if not records:raise ValueError('Nonempty evidence corpus required')
    for source in sources.values():validate_source(source)
    rows=[]
    for row in records:
        validate_record(row,sources)
        if row['evidence_status']=='VERIFIED':raise ValueError('Stage7 SQL promotion requires a separately approved individual review path; none enabled')
        # VERIFIED semantics are checked by runner's external independent review gate.
        # Storage QUARANTINE is intentional: no operational promotion in stage7.
        linked=[sources[k] for k in sorted(row['sources'])]
        digest=hashlib.sha256(canonical(linked).encode()).hexdigest()
        source=dict(source_id='stage7-sources:'+digest,source_type='user_report',
                    locator='Full attributed source metadata in raw.sources; not a verification assertion',
                    retrieved_at=None,sha256=digest)
        rows.append(make_record('claim',row['id'],source,
            {'restriction':row,'sources':linked},
            {'evidence_status':row['evidence_status'],'interpretation_status':row['interpretation_status']},
            row['unknown_reasons'] or ['Research evidence; navigation eligibility remains false'],
            geometry=row['geometry']))
    with tempfile.TemporaryDirectory() as td:
        inp=Path(td)/'input.jsonl';sql=Path(td)/'output.sql'
        inp.write_text(''.join(canonical(r)+'\n' for r in rows),encoding='utf-8')
        storage.generate(inp,sql)
        text=sql.read_text().replace('trucksil_stage6_test','trucksil_stage7_test').replace('STAGE6_POSTGIS_PASS','STAGE7_POSTGIS_PASS')
        text=text.replace(storage.INSERT, CORE_GATE+'\n'+storage.INSERT,1)
        text=text.replace('ANALYZE records;',NEGATIVE_PROBES+'\nANALYZE records;')
        output.write_text(text,encoding='utf-8')
    return len(rows)

CORE_GATE = r"""
CREATE TABLE stage7_source_registry(source_id text PRIMARY KEY,payload jsonb NOT NULL);
DO $$ BEGIN
 IF EXISTS(SELECT item->>'source_id' FROM incoming, jsonb_array_elements(payload->'raw'->'sources') item GROUP BY item->>'source_id' HAVING count(DISTINCT item)>1) THEN RAISE EXCEPTION 'stage7 source identity conflict'; END IF;
END $$;
INSERT INTO stage7_source_registry SELECT DISTINCT item->>'source_id',item FROM incoming,jsonb_array_elements(payload->'raw'->'sources') item;
CREATE TRIGGER stage7_source_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON stage7_source_registry FOR EACH STATEMENT EXECUTE FUNCTION immutable_source();
CREATE FUNCTION guard_stage7_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r jsonb; item jsonb; linked jsonb; registered jsonb; BEGIN
 r=NEW.payload->'raw'->'restriction';
 IF (jsonb_typeof(r)='object' AND r->>'schema_version'='stage7.restriction.v1' AND r->>'id'=NEW.record_id AND
 r->>'scope' IN ('LOCAL','GENERAL_VEHICLE_NORM') AND r->>'evidence_status' IN ('QUARANTINE','UNKNOWN') AND
 r->>'interpretation_status' IN ('SUPPORTED','UNKNOWN','UNSUPPORTED','CONFLICT') AND
 r->'navigation_eligible'='false'::jsonb AND r->'synthetic'='false'::jsonb AND r->'geometry'=NEW.payload->'geometry' AND
 jsonb_typeof(r->'location')='object' AND jsonb_typeof(r->'vehicle_conditions')='object' AND
 jsonb_typeof(r->'value')='object' AND jsonb_typeof(r->'validity')='object' AND
 jsonb_typeof(r->'sources')='array' AND jsonb_array_length(r->'sources')>0 AND
 jsonb_typeof(r->'unknown_reasons')='array') IS NOT TRUE THEN RAISE EXCEPTION 'invalid stage7 core' USING ERRCODE='23514'; END IF;
 IF (r->>'interpretation_status' IN ('UNKNOWN','UNSUPPORTED','CONFLICT') OR r->>'evidence_status'='UNKNOWN') AND valid_reasons(r->'unknown_reasons') IS NOT TRUE THEN RAISE EXCEPTION 'stage7 unknown reason missing' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT jsonb_array_elements(NEW.payload->'raw'->'sources') LOOP
  SELECT payload INTO registered FROM stage7_source_registry WHERE source_id=item->>'source_id';
  IF item IS DISTINCT FROM registered THEN RAISE EXCEPTION 'stage7 source provenance mismatch' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR linked IN SELECT jsonb_array_elements(r->'sources') LOOP
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.payload->'raw'->'sources') item WHERE item->>'source_id'=linked#>>'{}') THEN RAISE EXCEPTION 'stage7 source reference missing' USING ERRCODE='23503'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER stage7_evidence_guard BEFORE INSERT OR UPDATE ON records FOR EACH ROW EXECUTE FUNCTION guard_stage7_evidence();
"""

NEGATIVE_PROBES = r"""
DO $$ DECLARE sid text; BEGIN
 SELECT record_id INTO sid FROM records ORDER BY record_id LIMIT 1;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,restriction,evidence_status}','"VERIFIED"') WHERE record_id=sid; RAISE EXCEPTION 'raw VERIFIED accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,restriction,navigation_eligible}','true') WHERE record_id=sid; RAISE EXCEPTION 'raw navigation accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,restriction,sources}','["missing"]') WHERE record_id=sid; RAISE EXCEPTION 'raw source FK accepted'; EXCEPTION WHEN foreign_key_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,sources,0,rights}','"forged rights"') WHERE record_id=sid; RAISE EXCEPTION 'raw source forgery accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE stage7_source_registry SET payload='{}'; RAISE EXCEPTION 'stage7 registry mutation accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
"""
