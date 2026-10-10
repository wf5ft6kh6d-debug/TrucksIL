"""Read-only research audit. No physical connectivity or truck permissions inferred."""
import argparse, csv, hashlib, json, sqlite3, time
from collections import Counter
from pathlib import Path
from shapely import STRtree, from_wkt
from shapely.geometry import LineString, mapping


def file_sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def active(tags, key):
    return key in tags and str(tags[key]).lower() not in ('no','false','0')


def direction(tags):
    return {'yes':'forward','1':'forward','true':'forward','-1':'reverse','no':'both','0':'both','false':'both'}.get(tags.get('oneway'),'unknown')


def turn_check(tags, members, ways):
    roles={k:[m for m in members if m['role']==k] for k in ('from','via','to')}
    issues=[]
    for k in roles:
        if not roles[k]: issues.append('missing_'+k)
        if len(roles[k])>1: issues.append('multiple_'+k)
    if any('conditional' in k for k in tags):issues.append('conditional_requires_interpretation')
    if tags.get('except'):issues.append('except_requires_vehicle_interpretation')
    if any(k.startswith('restriction:') and k!='restriction:conditional' for k in tags):issues.append('vehicle_specific_restriction')
    if any(m['type']=='w' for m in roles['via']):issues.append('via_way_requires_path_analysis')
    directional={}
    if all(len(roles[k])==1 for k in roles) and roles['via'][0]['type']=='n':
        via=roles['via'][0]['id']
        for role in ('from','to'):
            mem=roles[role][0]
            if mem['type']!='w' or mem['id'] not in ways:
                issues.append(role+'_not_in_highway_graph');continue
            w=ways[mem['id']];nodes=w['nodes'];d=direction(w['tags'])
            positions=[i for i,n in enumerate(nodes) if n==via]
            if not positions:issues.append(role+'_via_node_not_on_way');directional[role]='disconnected';continue
            if d=='unknown': directional[role]='unknown';continue
            allowed=any((i>0 if role=='from' else i<len(nodes)-1) if d=='forward' else
                        (i<len(nodes)-1 if role=='from' else i>0) if d=='reverse' else len(nodes)>1 for i in positions)
            directional[role]='explicit_direction_allows_incidence' if allowed else 'explicit_direction_conflict'
            if not allowed:issues.append(role+'_explicit_direction_conflict')
    return {'issues':issues,'direction_incidence':directional,'status':'QUARANTINE'}


def crossing_class(a, b, common_nodes):
    different=(a.get('layer') is not None and b.get('layer') is not None and a['layer']!=b['layer'])
    return {'status':'UNKNOWN','classification':'shared_osm_node_candidate' if common_nodes else 'different_explicit_layer_candidate' if different else 'no_shared_osm_node_unknown',
            'explicit_layer_values_differ':different,'physical_connection_verified':False}


def run(source, output, sql_export=False, all_road_pairs=False):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(f'file:{Path(source).resolve()}?mode=ro',uri=True);start=time.monotonic()
    ways={i:{'id':i,'version':v,'timestamp':ts,'tags':json.loads(t),'nodes':json.loads(n)} for i,v,ts,t,n in db.execute('select * from ways')}
    ids=[];geoms=[];current=None;coords=[];counts=Counter()
    def flush():
        if current is not None and len(coords)>1:
            ids.append(current);geoms.append(LineString(coords))
    for wid,seq,wkt in db.execute('select way_id,seq,geom from segments order by way_id,seq'):
        pts=list(from_wkt(wkt).coords)
        if wid!=current:flush();current=wid;coords=[pts[0]]
        if coords[-1]!=pts[0]:raise ValueError('discontinuous source way: cannot invent connection')
        coords.append(pts[1])
    flush();tree=STRtree(geoms);infra_indices=[i for i,wid in enumerate(ids) if active(ways[wid]['tags'],'bridge') or active(ways[wid]['tags'],'tunnel')]
    infra_ids={ids[i] for i in infra_indices};node_incidence=Counter()
    for w in ways.values():
        for n in set(w['nodes']):node_incidence[n]+=1
    with (out/'infrastructure-ways.jsonl').open('w') as f:
        for i in infra_indices:
            w=ways[ids[i]];tags=w['tags'];types=[k for k in ('bridge','tunnel') if active(tags,k)]
            for typ in types:
                counts[typ+'_ways']+=1
                counts[typ+'_missing_layer']+=int('layer' not in tags)
            counts['infra_direction_'+direction(tags)]+=1
            if len(types)==2:counts['bridge_and_tunnel_same_way']+=1
            r={**w,'types':types,'geometry':mapping(geoms[i]),'status':'UNKNOWN','official_evidence':None,
               'endpoints':[{'node_id':n,'coordinate':list(p),'highway_ways_sharing_node':node_incidence[n], 'physical_portal_status':'UNKNOWN'} for n,p in [(w['nodes'][0],geoms[i].coords[0]),(w['nodes'][-1],geoms[i].coords[-1])]],'truck_permission':'UNKNOWN'}
            f.write(json.dumps(r)+'\n')
    predicates=Counter();classified=Counter();pairs=0
    with (out/'infrastructure-intersections.jsonl').open('w') as f:
        for i in (range(len(ids)) if all_road_pairs else infra_indices):
            a=geoms[i];wa=ways[ids[i]]
            for j0 in sorted(tree.query(a,predicate='intersects')):
                j=int(j0)
                if (j<=i if all_road_pairs else j==i or (ids[j] in infra_ids and j<i)):continue
                b=geoms[j];wb=ways[ids[j]];pairs+=1
                flags={p:bool(getattr(a,p)(b)) for p in ('intersects','touches','crosses','overlaps','equals')}
                predicates.update(k for k,v in flags.items() if v)
                shared=sorted(set(wa['nodes']).intersection(wb['nodes']));cl=crossing_class(wa['tags'],wb['tags'],shared);classified[cl['classification']]+=1
                r={'way_ids':[ids[i],ids[j]],'source_versions':[wa['version'],wb['version']],'predicates':flags,'relate':a.relate(b),'common_node_ids':shared,**cl}
                if not shared or ids[i] in infra_ids or ids[j] in infra_ids or any(flags[p] for p in ('crosses','overlaps','equals')):
                    r.update(geometry=mapping(a.intersection(b)),tags=[wa['tags'],wb['tags']])
                f.write(json.dumps(r)+'\n')
    turns=Counter();turn_directions=Counter()
    with (out/'turn-relations.jsonl').open('w') as f:
        for rid,v,ts,tags,members,missing,status in db.execute('select * from relations'):
            t=json.loads(tags);m=json.loads(members);r=turn_check(t,m,ways);turns.update(r['issues']);turn_directions.update(r['direction_incidence'].values())
            f.write(json.dumps({'id':rid,'version':v,'timestamp':ts,'tags':t,'members':m,'missing_source_refs':json.loads(missing),**r})+'\n')
    result={'schema_version':1,'scope':'all highway ways; all indexed intersecting way pairs; 2D only' if all_road_pairs else 'all highway ways; every pair involving an active bridge or tunnel way; 2D geometry only',
        'license':'ODbL-1.0','attribution':'© OpenStreetMap contributors','source_graph_name':Path(source).name,'source_osm_sha256':'dff1ce395df33b8df901b85f7fd822bacd7a10985ceb2d893144251455646670',
        'highway_ways':len(ways),'geometry_ways':len(ids),'infrastructure_ways':len(infra_indices),'infrastructure_counts':dict(counts),
        'intersecting_pairs':pairs,'predicates':dict(predicates),'classifications':dict(classified),'turn_relations':db.execute('select count(*) from relations').fetchone()[0],
        'turn_issues_overlapping':dict(turns),'turn_direction_incidence':dict(turn_directions),'verified_physical_connections':0,'verified_portals':0,'verified_truck_restrictions':0,
        'limitations':['Shared node anywhere on same ways is only an incidence candidate; not proof every intersection has that node.','No traffic permission from missing tags.','Layer comparison is raw tagged evidence only, not surveyed height.','Complex via-way, conditional and vehicle exceptions retained in quarantine.'], 'elapsed_seconds':time.monotonic()-start}
    if sql_export:
        with (out/'infrastructure-check.sql').open('w') as f:
            f.write("\\set ON_ERROR_STOP on\nDO $$ BEGIN IF current_database() !~ '^trucksil_stage4_test_' OR inet_server_addr() IS NOT NULL THEN RAISE EXCEPTION 'isolated Unix socket test DB required'; END IF; END $$;\nBEGIN;\nCREATE EXTENSION IF NOT EXISTS postgis;\nCREATE TEMP TABLE infrastructure_geometry(id bigint PRIMARY KEY,infra boolean,geom geometry(LineString,4326));\nCOPY infrastructure_geometry FROM STDIN WITH(FORMAT csv);\n")
            writer=csv.writer(f,lineterminator='\n')
            for i,wid in enumerate(ids):writer.writerow((wid,wid in infra_ids,'SRID=4326;'+geoms[i].wkt))
            pair_filter='a.id<b.id' if all_road_pairs else 'a.id<>b.id AND (NOT b.infra OR a.id<b.id) AND a.infra'
            f.write('\\.\nCREATE INDEX ON infrastructure_geometry USING gist(geom); ANALYZE infrastructure_geometry;\nCREATE TEMP TABLE infra_pairs AS SELECT a.id a,b.id b,ST_Relate(a.geom,b.geom) relate FROM infrastructure_geometry a JOIN infrastructure_geometry b ON '+pair_filter+' AND ST_Intersects(a.geom,b.geom);\n')
            for p in ('intersects','touches','crosses','overlaps','equals'):
                f.write(f"DO $$ BEGIN IF (SELECT count(*) FROM infra_pairs p JOIN infrastructure_geometry a ON a.id=p.a JOIN infrastructure_geometry b ON b.id=p.b WHERE ST_{p}(a.geom,b.geom))<>{predicates[p]} THEN RAISE EXCEPTION '{p} mismatch'; END IF; END $$;\n")
            f.write('CREATE TEMP TABLE expected_pairs(a bigint,b bigint,relate text);\nCOPY expected_pairs FROM STDIN WITH(FORMAT csv);\n')
            writer=csv.writer(f,lineterminator='\n')
            with (out/'infrastructure-intersections.jsonl').open() as evidence:
                for line in evidence:
                    pair=json.loads(line);writer.writerow((*pair['way_ids'],pair['relate']))
            f.write("\\.\nDO $$ BEGIN IF EXISTS(SELECT 1 FROM expected_pairs e FULL JOIN infra_pairs p USING(a,b) WHERE e.a IS NULL OR p.a IS NULL OR e.relate<>p.relate) THEN RAISE EXCEPTION 'pair IDs or DE9IM mismatch'; END IF; END $$;\nSELECT 'INFRASTRUCTURE FULL INDEXED PAIR COMPARISON PASS';\nROLLBACK;\n")
    result['artifact_sha256']={p.name:file_sha256(p) for p in out.iterdir() if p.name.endswith('.jsonl')}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('output');p.add_argument('--sql-export',action='store_true');p.add_argument('--all-road-pairs',action='store_true');a=p.parse_args();run(a.source,a.output,a.sql_export,a.all_road_pairs)
