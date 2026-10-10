"""Offline replay of licensed snapshot; generates guarded rollback-only SQL."""
import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from osm_pilot import load_snapshot, normalize
from ingest_restrictions import timestamp


def copy_field(value):
    return str(value).replace('\\','\\\\').replace('\t','\\t').replace('\n','\\n').replace('\r','\\r')


def sql_plan(result, manifest):
    # Only validated numeric coordinates and generated IDs; COPY escaping for text.
    revision=manifest['sha256'];source='osm:'+revision
    checked=manifest['license']['checked_on']+'T00:00:00Z'
    due=(timestamp(checked)+timedelta(days=30)).isoformat()  # Internal licence re-review, not expiry of ODbL
    lines=[r'\set ON_ERROR_STOP on', 'BEGIN;', """DO $$ BEGIN
 IF current_database() !~ '^trucksil_stage2_test_[a-zA-Z0-9_]+$' OR inet_server_addr() IS NOT NULL THEN
  RAISE EXCEPTION 'Disposable local Unix-socket database required'; END IF;
 IF EXISTS (SELECT 1 FROM trucksil_stage2.sources) OR EXISTS (SELECT 1 FROM trucksil_stage2.road_nodes)
    OR EXISTS (SELECT 1 FROM trucksil_stage2.road_segments) THEN
  RAISE EXCEPTION 'Pilot replay requires empty staging tables'; END IF;
END $$;""",'SET LOCAL search_path=trucksil_stage2,public;',
      'COPY sources FROM STDIN;']
    lines.append('\t'.join(map(copy_field,[source,'© OpenStreetMap contributors — Haifa research pilot',
        manifest['source_url'],'open_mapping','false','ODbL-1.0',manifest['license']['reference'],
        'permitted',checked,due,manifest['license']['reviewer'],json.dumps(manifest['license']['obligations'])])))
    lines.extend([r'\.', 'COPY road_nodes FROM STDIN;'])
    for n in result['nodes']:
        x,y=n['geometry']['coordinates']
        lines.append('\t'.join(map(copy_field,[n['id'],source,f"node/{n['source_node']}/v{n['source_version']}",
            revision,f'SRID=4326;POINT({x} {y})','unverified'])))
    lines.extend([r'\.', 'COPY road_segments FROM STDIN;'])
    for s in result['segments']:
        coords=','.join(f'{x} {y}' for x,y in s['geometry']['coordinates'])
        lines.append('\t'.join(map(copy_field,[s['id'],source,
            f"way/{s['source_way']}/v{s['source_version']}/pair/{s['source_pair_index']}",revision,
            s['from_node'],s['to_node'],f'SRID=4326;LINESTRING({coords})',s['direction'],'unverified'])))
    lines.append(r'\.')
    w,s,e,n=manifest['bbox_wgs84'];ns=len(result['segments']);nn=len(result['nodes'])
    length=result['summary']['road_length_m_spherical']
    lines.append(f"""DO $$ BEGIN
 IF (SELECT count(*) FROM road_nodes)<>{nn} OR (SELECT count(*) FROM road_segments)<>{ns} OR {ns}=0 THEN
  RAISE EXCEPTION 'Pilot feature count mismatch/empty graph'; END IF;
 IF EXISTS (SELECT 1 FROM road_segments WHERE NOT ST_IsValid(geometry) OR ST_IsEmpty(geometry)
   OR ST_SRID(geometry)<>4326 OR ST_Length(geometry::geography)<=0
   OR NOT ST_CoveredBy(geometry,ST_MakeEnvelope({w},{s},{e},{n},4326))) THEN
  RAISE EXCEPTION 'Pilot geometry invalid/outside scope'; END IF;
 IF EXISTS (SELECT 1 FROM road_segments r JOIN road_nodes a ON a.node_id=r.from_node
    JOIN road_nodes b ON b.node_id=r.to_node
    WHERE NOT ST_Equals(ST_StartPoint(r.geometry),a.geometry) OR NOT ST_Equals(ST_EndPoint(r.geometry),b.geometry)
      OR r.source_revision<>a.source_revision OR r.source_revision<>b.source_revision) THEN
  RAISE EXCEPTION 'Pilot endpoint/source identity mismatch'; END IF;
 IF abs((SELECT sum(ST_Length(geometry::geography,false)) FROM road_segments)-{length})>1 THEN
  RAISE EXCEPTION 'Independent length check mismatch'; END IF;
 IF (SELECT count(*) FROM audit_events)<>{nn+ns+1} THEN RAISE EXCEPTION 'Pilot audit count mismatch'; END IF;
 IF EXISTS (SELECT 1 FROM audit_events WHERE old_row IS NOT NULL OR new_row IS NULL OR session_actor<>session_user) THEN
  RAISE EXCEPTION 'Pilot audit payload missing'; END IF;
 IF EXISTS (SELECT 1 FROM restriction_staging) OR EXISTS (SELECT 1 FROM coverage_reviews)
  OR EXISTS (SELECT 1 FROM segment_safety_state WHERE route_suitability<>'unknown' OR route_safety_certified) THEN
  RAISE EXCEPTION 'Pilot accidentally promoted into safety evidence'; END IF;
END $$;
SELECT count(*) AS segments, round(sum(ST_Length(geometry::geography))::numeric,3) AS metres_spheroid,
 round(sum(ST_Length(geometry::geography,false))::numeric,3) AS metres_sphere FROM road_segments;
ROLLBACK;
\\echo 'Real OSM pilot geometry/source/audit/unknown checks PASS; transaction rolled back.'
""")
    return '\n'.join(lines)+'\n'


def build(folder, output):
    p,m=load_snapshot(folder);r=normalize(p,m)
    expected=json.loads((Path(folder)/'expected-summary.json').read_text())
    if r['summary']!=expected: raise ValueError('Reproduction differs from reviewed summary')
    output=Path(output)
    if output.exists(): raise ValueError('Refusing to overwrite build output')
    sql=sql_plan(r,m)
    output.mkdir(parents=True)
    for name,obj in [('normalized.json',r),('summary.json',r['summary']),('restrictions.json',[])]:
        (output/name).write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
    (output/'pilot-replay.sql').write_text(sql)
    print(json.dumps(r['summary'],ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',default='data/stage3/osm-haifa-20261010')
    p.add_argument('--output',required=True)
    a=p.parse_args();build(a.snapshot,a.output)
