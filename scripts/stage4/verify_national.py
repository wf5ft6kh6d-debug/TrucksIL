"""Independent full-row geometry/NetworkX checks; bounded pairwise sample clearly labelled."""
import csv,io,json,sqlite3,sys,time
from pathlib import Path
import networkx as nx
from shapely import wkt
from jsonschema import Draft202012Validator

def verify(folder):
 p=Path(folder);s=json.loads((p/'summary.json').read_text());db=sqlite3.connect(p/'graph.sqlite');t=time.monotonic();g=nx.Graph();unknown=0;n=0
 from shapely.geometry import Polygon
 from shapely.prepared import prep
 coords=[]
 for line in Path('data/stage4/source-boundary.poly').read_text().splitlines():
  parts=line.split()
  if len(parts)==2:
   try:coords.append(tuple(map(float,parts)))
   except ValueError:pass
 poly=prep(Polygon(coords));outside=0
 for a,b,d,geom in db.execute('SELECT a,b,direction,geom FROM segments'):
  line=wkt.loads(geom);assert line.is_valid and line.length>0 and len(line.coords)==2
  assert all(-180<=x<=180 and -90<=y<=90 for x,y in line.coords)
  g.add_edge(a,b);unknown+=d=='unknown';n+=1;outside+=not poly.covers(line.interpolate(.5,normalized=True))
 sizes=sorted(map(len,nx.connected_components(g)),reverse=True);assert sizes==s['component_sizes']
 assert n==s['counts']['segments'] and unknown==s['direction_segments'].get('unknown',0)
 assert not db.execute('PRAGMA foreign_key_check').fetchall()
 schema={'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','required':['type','id','version','tags','categories','status'],'properties':{'type':{'enum':['node','way','relation']},'id':{'type':'integer','minimum':1},'version':{'type':'integer','minimum':1},'tags':{'type':'object'},'categories':{'type':'array','minItems':1},'status':{'const':'QUARANTINE'}}}
 v=Draft202012Validator(schema);c=0
 for typ,id,version,tags,cats,status in db.execute('SELECT type,id,version,tags,categories,status FROM candidates'):
  v.validate({'type':typ,'id':id,'version':version,'tags':json.loads(tags),'categories':json.loads(cats),'status':status});c+=1
 result={'source_polygon_midpoints_outside':outside,'segments_checked':n,'nodes_with_edges':g.number_of_nodes(),'components':len(sizes),'candidate_records_schema_checked':c,'unknown_direction_segments':unknown,'all_geometry_rows_valid':True,'networkx_components_agree':True,'foreign_keys_ok':True,'elapsed_seconds':time.monotonic()-t,'pairwise_national_intersections':'NOT EXHAUSTIVELY TESTED','verified_restrictions':0}
 (p/'independent-checks.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

def export_sql(folder):
 p=Path(folder);db=sqlite3.connect(p/'graph.sqlite');s=json.loads((p/'summary.json').read_text());sha=s['source_sha256'];out=(p/'national-test.sql').open('w')
 out.write("\\set ON_ERROR_STOP on\n\\timing on\nDO $$ BEGIN IF current_database() !~ '^trucksil_stage4_test_' OR inet_server_addr() IS NOT NULL THEN RAISE EXCEPTION 'isolated test database via Unix socket required'; END IF; END $$;\nBEGIN;\nCREATE EXTENSION IF NOT EXISTS postgis;\nCREATE SCHEMA trucksil_stage4;\nSET search_path=trucksil_stage4,public;\n")
 out.write("CREATE TABLE sources(sha text PRIMARY KEY CHECK(sha ~ '^[0-9a-f]{64}$'),snapshot timestamptz NOT NULL,license text CHECK(license='ODbL-1.0'));\n")
 out.write(f"INSERT INTO sources VALUES('{sha}','{s['snapshot_at']}','ODbL-1.0');\n")
 out.write("CREATE TABLE audit(id bigserial,operation text,table_name text,at timestamptz DEFAULT clock_timestamp());\nCREATE FUNCTION audit_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN INSERT INTO audit(operation,table_name) VALUES(TG_OP,TG_TABLE_NAME); RETURN NULL; END $$;\n")
 out.write(f"CREATE TABLE ways(id bigint PRIMARY KEY,version integer CHECK(version>0),timestamp timestamptz,tags jsonb,nodes jsonb,source_sha text NOT NULL DEFAULT '{sha}' REFERENCES sources);\n")
 out.write("CREATE TABLE nodes(id bigint PRIMARY KEY,lon double precision CHECK(lon BETWEEN -180 AND 180),lat double precision CHECK(lat BETWEEN -90 AND 90));\nCREATE TABLE segments(id bigint PRIMARY KEY,way_id bigint REFERENCES ways,seq integer,a bigint REFERENCES nodes,b bigint REFERENCES nodes,direction text CHECK(direction IN ('forward','reverse','both','unknown')),geom geometry(LineString,4326) NOT NULL CHECK(ST_IsValid(geom) AND ST_NPoints(geom)=2 AND ST_Length(geom)>0),length_m double precision CHECK(length_m>0),tile text,CHECK(a<>b));\nCREATE TABLE candidates(type text,id bigint,version integer CHECK(version>0),timestamp timestamptz,tags jsonb,categories jsonb,geometry jsonb,status text CHECK(status='QUARANTINE'),PRIMARY KEY(type,id));\n")
 out.write("CREATE TRIGGER segment_audit AFTER INSERT OR UPDATE OR DELETE ON segments FOR EACH STATEMENT EXECUTE FUNCTION audit_change();\n")
 for tab,cols in [('ways','id,version,timestamp,tags,nodes'),('nodes','id,lon,lat'),('segments','id,way_id,seq,a,b,direction,geom,length_m,tile'),('candidates','type,id,version,timestamp,tags,categories,geometry,status')]:
  out.write(f'COPY {tab}({cols}) FROM STDIN WITH (FORMAT csv);\n');writer=csv.writer(out,lineterminator='\n')
  for row in db.execute('SELECT '+cols+' FROM '+tab):
   row=list(row)
   if tab=='segments':row[6]='SRID=4326;'+row[6]
   writer.writerow(row)
  out.write('\\.\n')
 out.write("CREATE INDEX segments_geom_gist ON segments USING gist(geom); ANALYZE segments;\nSELECT version(),postgis_full_version();\n")
 n=s['counts']['segments'];u=s['direction_segments'].get('unknown',0)
 out.write(f"DO $$ BEGIN IF (SELECT count(*) FROM segments)<>{n} OR (SELECT count(*) FROM segments WHERE direction='unknown')<>{u} THEN RAISE EXCEPTION 'count mismatch'; END IF; IF EXISTS(SELECT 1 FROM segments s JOIN nodes n ON n.id=s.a WHERE ST_X(ST_StartPoint(s.geom))<>n.lon OR ST_Y(ST_StartPoint(s.geom))<>n.lat) THEN RAISE EXCEPTION 'node geometry mismatch'; END IF; END $$;\n")
 out.write("DO $$ BEGIN IF EXISTS(SELECT 1 FROM segments s JOIN nodes n ON n.id=s.b WHERE ST_X(ST_EndPoint(s.geom))<>n.lon OR ST_Y(ST_EndPoint(s.geom))<>n.lat) THEN RAISE EXCEPTION 'end geometry mismatch'; END IF; END $$;\n")
 out.write("CREATE TEMP TABLE repeat_batch AS SELECT * FROM segments; INSERT INTO segments SELECT * FROM repeat_batch ON CONFLICT DO NOTHING;\n")
 out.write(f"DO $$ BEGIN IF (SELECT count(*) FROM segments)<>{n} THEN RAISE EXCEPTION 'repeat import changed count'; END IF; BEGIN UPDATE segments SET a=-1 WHERE id=1; RAISE EXCEPTION 'FK accepted'; EXCEPTION WHEN foreign_key_violation THEN NULL; END; BEGIN UPDATE candidates SET status='VERIFIED'; RAISE EXCEPTION 'verification bypass'; EXCEPTION WHEN check_violation THEN NULL; END; IF (SELECT count(*) FROM audit)<2 THEN RAISE EXCEPTION 'missing audit'; END IF; END $$;\n")
 # Engine comparison: deterministic 1000-segment sample, ALL pairs within it; not national exhaustive.
 rows=db.execute('SELECT id,geom FROM segments ORDER BY id LIMIT 1000').fetchall();preds=['intersects','touches','overlaps','equals','crosses'];expected={k:0 for k in preds}
 shapes=[wkt.loads(g) for _,g in rows]
 for i,a in enumerate(shapes):
  for b in shapes[i+1:]:
   if not a.intersects(b):continue
   for k in preds:expected[k]+=int(getattr(a,k)(b))
 out.write('CREATE TEMP TABLE sample AS SELECT * FROM segments ORDER BY id LIMIT 1000;\n')
 for k,num in expected.items():out.write(f"DO $$ BEGIN IF (SELECT count(*) FROM sample a JOIN sample b ON a.id<b.id AND ST_{k}(a.geom,b.geom))<>{num} THEN RAISE EXCEPTION '{k} mismatch'; END IF; END $$;\n")
 out.write("SELECT count(*) AS nearby_pairs_0_5m FROM sample a JOIN sample b ON a.id<b.id AND ST_DWithin(a.geom::geography,b.geom::geography,0.5);\nSELECT ST_Relate(a.geom,b.geom) FROM sample a JOIN sample b ON a.id<b.id AND ST_Intersects(a.geom,b.geom) LIMIT 10;\nEXPLAIN (ANALYZE,BUFFERS) SELECT count(*) FROM segments WHERE geom && ST_MakeEnvelope(34.99,32.811,35.004,32.821,4326);\nSELECT 'NATIONAL FULL ROW / SAMPLE PREDICATE CHECKS PASS';\nROLLBACK;\nDO $$ BEGIN IF EXISTS(SELECT FROM pg_namespace WHERE nspname='trucksil_stage4') THEN RAISE EXCEPTION 'rollback leaked schema'; END IF; END $$;\nSELECT 'NATIONAL ROLLBACK PASS';\n")
 out.close();(p/'sample-predicates.json').write_text(json.dumps({'sample':'first 1000 segment IDs; not representative of national intersections','pair_counts':expected},indent=2))
if __name__=='__main__':
 verify(sys.argv[1]);export_sql(sys.argv[1])
