"""Read-only exact/Shapely audit; emits pair-by-pair independent PostGIS assertions."""
import json,sys
from collections import Counter,defaultdict,deque
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
import shapely
from shapely.geometry import LineString,box,mapping
from shapely.strtree import STRtree
from shapely.ops import transform
from pyproj import Transformer
from osm_pilot import load_snapshot,normalize
from topology_audit import relation,classify,endpoint_evidence

def audit():
 p,m=load_snapshot('data/stage3/osm-haifa-20261010');g=normalize(p,m)
 segs=g['segments'];lines=[LineString(s['geometry']['coordinates']) for s in segs]
 tree=STRtree(lines);pairs=[];expected=[];counts=Counter();exact_count=0
 for i,a in enumerate(lines):
  for j in sorted(map(int,tree.query(a))):
   if j<=i:continue
   b=lines[j];kind=relation(list(a.coords),list(b.coords))
   intersects=a.intersects(b)
   assert (kind!='disjoint')==intersects,('exact intersection mismatch',i,j)
   if not intersects:continue
   exact_count+=1
   skind='equals' if a.equals(b) else 'overlaps' if a.overlaps(b) else 'contained_overlap' if a.intersection(b).length>0 else 'crosses' if a.crosses(b) else 'endpoint_touch' if set(a.coords)&set(b.coords) else 'interior_touch'
   assert kind==skind,('exact classification mismatch',i,j,kind,skind)
   s,t=segs[i],segs[j];shared=sorted({s['from_node'],s['to_node']}&{t['from_node'],t['to_node']})
   shared=[int(n.rsplit(':',1)[1]) for n in shared]
   status,reason=classify(kind,shared,s['tags'],t['tags'])
   row={'id':f'PAIR-{i}-{j}','segments':[i,j],'coordinates_wgs84':mapping(a.intersection(b)), 'kind':kind,'shared_osm_nodes':shared,'status':status,'reason':reason,'priority':'P2' if status=='VERIFIED' else 'P1','next_action':'No connection change; official/field evidence for transport applicability' if status!='VERIFIED' else 'Retain OSM identity; not a truck permission'}
   pairs.append(row);counts[kind]+=1
   expected.append([i,j,a.touches(b),a.overlaps(b),a.equals(b),a.crosses(b),a.relate(b)])
 project=Transformer.from_crs(4326,32636,always_xy=True).transform
 projected=[transform(project,a) for a in lines];ptree=STRtree(projected);near=[]
 for i,a in enumerate(projected):
  for j in sorted(map(int,ptree.query(a.buffer(.5)))):
   if j>i and a.distance(projected[j])<=.5:
    near.append([i,j])
 # Full ways may include context outside the pilot; intersect scope, but never import it.
 nodes={e['id']:e for e in p['elements'] if e['type']=='node'}
 ways=[e for e in p['elements'] if e['type']=='way'];scope=box(*m['bbox_wgs84']);infra=[];raw_checks=[]
 for w in ways:
  missing=[n for n in w['nodes'] if n not in nodes]
  coords=[[nodes[n]['lon'],nodes[n]['lat']] for n in w['nodes'] if n in nodes]
  geom=LineString(coords) if len(coords)>1 and not missing else None
  if geom is None or not geom.intersects(scope):continue
  repeated=sum(a==b for a,b in zip(coords,coords[1:]))
  if repeated or not geom.is_simple or not geom.is_valid:
   raw_checks.append({'way':w['id'],'version':w['version'],'repeated_consecutive_vertices':repeated,'is_simple':geom.is_simple,'is_valid':geom.is_valid,'scope':'full source way intersects pilot; may include outside context','status':'SUSPECTED','next_action':'Inspect repeated vertices/non-simple geometry before classifying a defect'})
  if any(k in w.get('tags',{}) for k in ('bridge','tunnel','layer','maxheight','maxweight','maxwidth','maxaxleload')):
   infra.append({'id':f"INFRA-{w['id']}",'way':w['id'],'version':w['version'],'tags':w['tags'],'coordinates_wgs84':coords,'endpoints':endpoint_evidence(w,nodes,ways),'retained_segments':sum(s['source_way']==w['id'] for s in segs),'is_simple':geom.is_simple,'is_valid':geom.is_valid,'status':'UNKNOWN','priority':'P1','official_evidence':None,'truck_applicability':'unknown','next_action':'Verify physical portals, levels and limits with competent source; no graph edits'})
 # Context geometry is clipped only for diagnostics, never inserted as graph roads.
 infra_ids={x['way'] for x in infra};context=[];contacts=[]
 for w in ways:
  if 'highway' not in w.get('tags',{}) or any(n not in nodes for n in w['nodes']):continue
  geom=LineString([(nodes[n]['lon'],nodes[n]['lat']) for n in w['nodes']]).intersection(scope)
  if not geom.is_empty:context.append((w,geom))
 for i,(a,ga) in enumerate(context):
  for b,gb in context[i+1:]:
   if not ({a['id'],b['id']}&infra_ids) or not ga.intersects(gb):continue
   shared=sorted(set(a['nodes'])&set(b['nodes']))
   shared=[n for n in shared if scope.covers(shapely.geometry.Point(nodes[n]['lon'],nodes[n]['lat']))]
   different=all('layer' in w.get('tags',{}) for w in (a,b)) and a['tags']['layer']!=b['tags']['layer']
   contacts.append({'id':f"CONTEXT-{a['id']}-{b['id']}",'priority':'P1','next_action':'Independent physical/official level verification; never connect based on crossing','versions':[a['version'],b['version']],'ways':[a['id'],b['id']],'tags':[a['tags'],b['tags']],'coordinates_wgs84':mapping(ga.intersection(gb)),'shared_nodes':shared,'matrix':ga.relate(gb),'different_explicit_layers':different,'status':'UNKNOWN','reason':'Diagnostic contact of raw ways inside bbox; physical level/portal and truck use unverified'})
 for x in infra:
  for e in x['endpoints']:e['inside_pilot']=scope.covers(shapely.geometry.Point(e['coordinates'])) if e['coordinates'] else False
 adj=defaultdict(set)
 for s in segs:
  a,b=s['from_node'],s['to_node'];adj[a].add(b);adj[b].add(a)
 def existing_path(pair):
  a,b=[segs[i] for i in pair];ends={b['from_node'],b['to_node']};queue=deque((n,[n]) for n in (a['from_node'],a['to_node']));seen={n for n,_ in queue}
  while queue:
   n,path=queue.popleft()
   if n in ends:return [int(v.rsplit(':',1)[1]) for v in path]
   for nb in sorted(adj[n]-seen):seen.add(nb);queue.append((nb,path+[nb]))
  return None
 endpointcoords=defaultdict(set)
 for n in g['nodes']:endpointcoords[tuple(n['geometry']['coordinates'])].add(n['source_node'])
 nearonly=[x for x in near if not lines[x[0]].intersects(lines[x[1]])]
 summary={'segments':len(segs),'all_pairs':len(segs)*(len(segs)-1)//2,'intersecting_pairs':len(pairs),'relations':dict(sorted(counts.items())), 'exact_shapely_compared_pairs':exact_count,'coincident_distinct_node_groups':sum(len(x)>1 for x in endpointcoords.values()),'invalid_segments':sum(not a.is_valid for a in lines),'non_simple_segments':sum(not a.is_simple for a in lines),'zero_length_segments':sum(a.length==0 for a in lines),'raw_way_findings':len(raw_checks),'near_pairs_0_5m_utm36n':len(near),'near_disjoint_pairs_0_5m':len(nearonly),'different_explicit_layer_contacts':sum('different_explicit_layers' in x['reason'] or 'explicit_different_layers;' in x['reason'] for x in pairs),'nonverified_contact_pairs':sum(x['status']!='VERIFIED' for x in pairs),'infrastructure_objects':len(infra),'bridges':sum(x['tags'].get('bridge') not in (None,'no') for x in infra),'tunnels':sum(x['tags'].get('tunnel') not in (None,'no') for x in infra),'infrastructure_contact_pairs':len(contacts),'infrastructure_different_layer_pairs':sum(x['different_explicit_layers'] for x in contacts),'graph_changed':False,'verified_truck_restrictions':0}
 report={'source_sha256':m['sha256'],'license':'ODbL-1.0','bbox':m['bbox_wgs84'],'confirmation_scope':'VERIFIED means geometry and OSM node identity only, never legal or truck verification','summary':summary,'segment_catalog':[{'index':i,'way':s['source_way'],'version':s['source_version'],'pair_index':s['source_pair_index'],'nodes':[int(s['from_node'].rsplit(':',1)[1]),int(s['to_node'].rsplit(':',1)[1])],'coordinates_wgs84':s['geometry']['coordinates']} for i,s in enumerate(segs)],'way_tags':{str(s['source_way']):s['tags'] for s in segs},'pairs':pairs,'infrastructure_contacts':contacts,'context_geometries':[{'way':w['id'],'infrastructure':w['id'] in infra_ids,'geometry':mapping(geom)} for w,geom in context],'near_disjoint_pairs':[{'id':f'NEAR-{x[0]}-{x[1]}','segments':x,'existing_undirected_node_path':existing_path(x),'distance_m':projected[x[0]].distance(projected[x[1]]),'status':'UNKNOWN','reason':'Within explicit 0.5 m search tolerance in EPSG:32636; no snapping'} for x in nearonly],'infrastructure':infra,'raw_way_findings':raw_checks,'limits':'2D geometry does not establish transport connectivity; missing layer is unknown. Pair counts are not unique junction counts. Near tolerance 0.5 m, EPSG:32636, no snapping. No official structural evidence.'}
 return report,expected,near,g

def sql_checks(base,report,expected,near,g):
 assert base.count('ROLLBACK;')==1
 rows=['CREATE TEMP TABLE topology_index(i integer PRIMARY KEY, id text);','COPY topology_index FROM STDIN;']
 rows += [f"{i}\t{s['id']}" for i,s in enumerate(g['segments'])];rows += [r'\.']
 rows+=['CREATE TEMP TABLE expected_topology(i integer,j integer,touch boolean,overlap boolean,eq boolean,crossing boolean,matrix text);','COPY expected_topology FROM STDIN;']
 rows += ['\t'.join(str(v).lower() if isinstance(v,bool) else str(v) for v in r) for r in expected];rows += [r'\.']
 rows+=['CREATE TEMP TABLE expected_near(i integer,j integer);','COPY expected_near FROM STDIN;'];rows+=['\t'.join(map(str,r)) for r in near];rows += [r'\.']
 rows += [r"""CREATE TEMP TABLE audit_geoms AS SELECT t.i,r.geometry,ST_Transform(r.geometry,32636) AS metric FROM topology_index t JOIN road_segments r ON t.id=r.segment_id;
CREATE INDEX ON audit_geoms USING gist(geometry);
CREATE INDEX ON audit_geoms USING gist(metric);
CREATE TEMP TABLE actual_topology AS SELECT a.i,b.i AS j,ST_Touches(a.geometry,b.geometry) AS touch,ST_Overlaps(a.geometry,b.geometry) AS overlap,ST_Equals(a.geometry,b.geometry) AS eq,ST_Crosses(a.geometry,b.geometry) AS crossing,ST_Relate(a.geometry,b.geometry) AS matrix FROM audit_geoms a JOIN audit_geoms b ON a.i<b.i AND ST_Intersects(a.geometry,b.geometry);
CREATE TEMP TABLE actual_near AS SELECT a.i,b.i AS j FROM audit_geoms a JOIN audit_geoms b ON a.i<b.i AND ST_DWithin(a.metric,b.metric,0.5);
DO $$ BEGIN
 IF EXISTS ((TABLE actual_topology EXCEPT TABLE expected_topology) UNION ALL (TABLE expected_topology EXCEPT TABLE actual_topology)) THEN RAISE EXCEPTION 'Shapely/PostGIS pair predicates or DE-9IM mismatch'; END IF;
 IF EXISTS ((TABLE actual_near EXCEPT TABLE expected_near) UNION ALL (TABLE expected_near EXCEPT TABLE actual_near)) THEN RAISE EXCEPTION 'Shapely/PostGIS 0.5m EPSG:32636 mismatch'; END IF;
 IF EXISTS (SELECT 1 FROM audit_geoms WHERE NOT ST_IsValid(geometry) OR NOT ST_IsSimple(geometry) OR ST_Length(metric)=0) THEN RAISE EXCEPTION 'Invalid/zero/non-simple segment'; END IF;
END $$;
SELECT count(*) AS independently_matched_intersecting_pairs FROM actual_topology;
SELECT count(*) AS independently_matched_near_pairs FROM actual_near;
\echo 'Topology Shapely/PostGIS all pair predicates, DE-9IM and 0.5m UTM comparison PASS'
"""]
 rows += ['CREATE TEMP TABLE context_geoms(way bigint, infrastructure boolean, geometry geometry);']
 # GeoJSON contains numeric geometry only; no untrusted string interpolation.
 for x in report['context_geometries']:
  geo=json.dumps(x['geometry'],separators=(',',':'))
  rows.append(f"INSERT INTO context_geoms VALUES ({x['way']},{str(x['infrastructure']).lower()},ST_SetSRID(ST_GeomFromGeoJSON('{geo}'),4326));")
 rows += ['CREATE TEMP TABLE expected_context(a bigint,b bigint,matrix text);']
 for x in report['infrastructure_contacts']:
  a,b=x['ways'];rows.append(f"INSERT INTO expected_context VALUES ({min(a,b)},{max(a,b)},'{x['matrix'] if a<b else ''.join(x['matrix'][k] for k in (0,3,6,1,4,7,2,5,8))}');")
 rows += [r"""CREATE TEMP TABLE actual_context AS SELECT a.way AS a,b.way AS b,ST_Relate(a.geometry,b.geometry) AS matrix FROM context_geoms a JOIN context_geoms b ON a.way<b.way AND (a.infrastructure OR b.infrastructure) AND ST_Intersects(a.geometry,b.geometry);
DO $$ BEGIN
 IF EXISTS ((TABLE actual_context EXCEPT TABLE expected_context) UNION ALL (TABLE expected_context EXCEPT TABLE actual_context)) THEN RAISE EXCEPTION 'Infrastructure context matrix mismatch'; END IF;
END $$;
\echo 'Infrastructure context Shapely/PostGIS comparison PASS'
"""]
 return base.replace('ROLLBACK;','\n'.join(rows)+'\nROLLBACK;')

if __name__=='__main__':
 out=Path(sys.argv[1]);r,e,n,g=audit()
 if len(sys.argv)>2:out.with_suffix('.sql').write_text(sql_checks(Path(sys.argv[2]).read_text(),r,e,n,g))
 r.pop('context_geometries')
 r['pair_defaults']={'priority':'P2','next_action':'Retain OSM identity; not a truck permission','reason':'shared OSM endpoint; geometry/identity only, truck access unverified'}
 for x in r['pairs']:
  if x['status']=='VERIFIED':
   for key in r['pair_defaults']:x.pop(key)
 out.write_text(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
 print(json.dumps(r['summary'],sort_keys=True))
