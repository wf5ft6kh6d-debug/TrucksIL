"""Reuse stage6 transactional storage; add actual SQL guards for review dimensions."""
import hashlib
import tempfile
from pathlib import Path
from scripts.stage6 import postgis as storage
from scripts.stage6.contract import make_record
from scripts.stage7.postgis import CORE_GATE as PREVIOUS_GATE
from scripts.stage8.contract import canonical, validate_review, validate_source

def generate(reviews,sources,output,public=True):
    output=Path(output)
    if output.exists() or output.is_symlink():raise ValueError('Output already exists')
    if not reviews:raise ValueError('Nonempty review corpus required')
    for source in sources.values():validate_source(source)
    rows=[]
    for review in reviews:
        validate_review(review,sources,public)
        linked=[sources[k] for k in sorted(review['sources'])]
        digest=hashlib.sha256(canonical(linked).encode()).hexdigest()
        source=dict(source_id='stage8-sources:'+digest,source_type='user_report',locator='Attributed review source metadata; no road verification assertion',retrieved_at=None,sha256=digest)
        rows.append(make_record('claim',review['id'],source,{'review':review,'sources':linked}, {'evidence_status':review['evidence_status'],'interpretation_status':review['interpretation_status']},review['unknown_reasons'],status=review['evidence_status']))
    with tempfile.TemporaryDirectory() as td:
        inp=Path(td)/'input.jsonl';sql=Path(td)/'output.sql'
        inp.write_text(''.join(canonical(row)+'\n' for row in rows),encoding='utf-8');storage.generate(inp,sql)
        text=sql.read_text().replace('trucksil_stage6_test','trucksil_stage8_test').replace('STAGE6_POSTGIS_PASS','STAGE8_POSTGIS_PASS')
        gate=CORE_GATE
        if public:gate=gate.replace('/*PUBLIC_GATE*/',"IF r->>'rights_status' IS DISTINCT FROM 'PUBLIC_METADATA_ONLY' THEN RAISE EXCEPTION 'private review in public import' USING ERRCODE='23514'; END IF;")
        else:gate=gate.replace('/*PUBLIC_GATE*/','')
        text=text.replace(storage.INSERT,gate+'\n'+storage.INSERT,1).replace('ANALYZE records;',NEGATIVE_PROBES+'\nANALYZE records;')
        output.write_text(text,encoding='utf-8')
    return len(rows)

# The proven immutable source registry is reused, not reimplemented.
SOURCE_GATE=PREVIOUS_GATE.split('CREATE FUNCTION guard_stage7_evidence()',1)[0].replace('stage7','stage8')
CORE_GATE=SOURCE_GATE+r"""
CREATE FUNCTION guard_stage8_review() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r jsonb; item jsonb; linked jsonb; registered jsonb; BEGIN
 r=NEW.payload->'raw'->'review';
 IF (jsonb_typeof(r)='object' AND r->>'schema_version'='stage8.review.v1' AND r->>'id'=NEW.record_id AND
 r->>'review_kind' IN ('NORM','LOCAL_RESTRICTION','CLAIM','GAP') AND
 r->>'evidence_status' IN ('QUARANTINE','UNKNOWN') AND
 r->>'evidence_status'=NEW.status AND
 r->'evidence_status'=NEW.payload->'interpretation'->'evidence_status' AND
 r->'interpretation_status'=NEW.payload->'interpretation'->'interpretation_status' AND
 r->>'interpretation_status' IN ('SUPPORTED','UNKNOWN','UNSUPPORTED','CONFLICT') AND
 r->>'currentness_status' IN ('CURRENT','UNKNOWN','EXPIRED') AND
 r->>'geobinding_status' IN ('BOUND','UNKNOWN','NOT_APPLICABLE') AND
 r->>'rights_status' IN ('PUBLIC_METADATA_ONLY','PRIVATE','UNKNOWN') AND
 r->'navigation_eligible'='false'::jsonb AND r->'operational_change'='false'::jsonb AND
 valid_reasons(r->'unknown_reasons') AND valid_reasons(r->'sources') AND
 jsonb_typeof(r->'subject_id')='string' AND length(btrim(r->>'subject_id'))>0 AND
 jsonb_typeof(r->'finding')='string' AND length(btrim(r->>'finding'))>0 AND
 jsonb_typeof(r->'checked_at')='string' AND (r->>'checked_at') ~ '^\d{4}-\d{2}-\d{2}$' AND
 (r - ARRAY['schema_version','id','subject_id','review_kind','finding','evidence_status','interpretation_status','currentness_status','geobinding_status','rights_status','unknown_reasons','sources','checked_at','navigation_eligible','operational_change'])='{}'::jsonb)
 IS NOT TRUE THEN RAISE EXCEPTION 'invalid stage8 review' USING ERRCODE='23514'; END IF;
 PERFORM (r->>'checked_at')::date;
 /*PUBLIC_GATE*/
 FOR item IN SELECT jsonb_array_elements(NEW.payload->'raw'->'sources') LOOP
  SELECT registry.payload INTO registered FROM stage8_source_registry AS registry WHERE registry.source_id=item->>'source_id';
  IF item IS DISTINCT FROM registered THEN RAISE EXCEPTION 'stage8 source provenance mismatch' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR linked IN SELECT jsonb_array_elements(r->'sources') LOOP
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.payload->'raw'->'sources') AS evidence(value) WHERE evidence.value->>'source_id'=linked#>>'{}') THEN RAISE EXCEPTION 'stage8 source reference missing' USING ERRCODE='23503'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER stage8_review_guard BEFORE INSERT OR UPDATE ON records FOR EACH ROW EXECUTE FUNCTION guard_stage8_review();
"""
NEGATIVE_PROBES=r"""
DO $$ DECLARE sid text; field text; BEGIN
 SELECT record_id INTO sid FROM records ORDER BY record_id LIMIT 1;
 FOREACH field IN ARRAY ARRAY['evidence_status','interpretation_status','currentness_status','geobinding_status','rights_status'] LOOP
  BEGIN UPDATE records SET payload=jsonb_set(payload,ARRAY['raw','review',field],'"INVALID"') WHERE record_id=sid; RAISE EXCEPTION 'invalid dimension accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 END LOOP;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,review,evidence_status}',to_jsonb(CASE WHEN status='QUARANTINE' THEN 'UNKNOWN'::text ELSE 'QUARANTINE'::text END)) WHERE record_id=sid; RAISE EXCEPTION 'divergent evidence copy accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{interpretation,interpretation_status}',to_jsonb(CASE WHEN payload->'raw'->'review'->>'interpretation_status'='UNKNOWN' THEN 'SUPPORTED'::text ELSE 'UNKNOWN'::text END)) WHERE record_id=sid; RAISE EXCEPTION 'divergent interpretation copy accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,review,evidence_status}','"VERIFIED"') WHERE record_id=sid; RAISE EXCEPTION 'VERIFIED accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,review,operational_change}','true') WHERE record_id=sid; RAISE EXCEPTION 'operational change accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,review,navigation_eligible}','true') WHERE record_id=sid; RAISE EXCEPTION 'navigation accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,review,unknown_reasons}','[]') WHERE record_id=sid; RAISE EXCEPTION 'missing reason accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,review,sources}','["missing"]') WHERE record_id=sid; RAISE EXCEPTION 'missing source accepted'; EXCEPTION WHEN foreign_key_violation THEN NULL; END;
 BEGIN UPDATE records SET payload=jsonb_set(payload,'{raw,sources,0,rights}','"forged"') WHERE record_id=sid; RAISE EXCEPTION 'forged rights accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN UPDATE stage8_source_registry SET payload='{}'; RAISE EXCEPTION 'registry mutation accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
"""
