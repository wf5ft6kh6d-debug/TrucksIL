"""Read-only full geometry audit. Findings are research evidence, never repairs.
Exact predicates operate on OSM's 1e-7 degree integer grid; Shapely is checked
against a separate segment-intersection implementation for every flagged way.
"""
import argparse, collections, csv, hashlib, itertools, json, sqlite3, time
from pathlib import Path
from shapely.geometry import LineString


def orient(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def relation(a,b,c,d):
    """Exact classification; no snapping or proximity tolerance."""
    o1,o2,o3,o4=orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
    if o1==o2==o3==o4==0:
        axis=0 if a[0]!=b[0] or c[0]!=d[0] else 1
        lo=max(min(a[axis],b[axis]),min(c[axis],d[axis]))
        hi=min(max(a[axis],b[axis]),max(c[axis],d[axis]))
        return 'overlap' if lo<hi else 'touch' if lo==hi else None
    if o1*o2<0 and o3*o4<0:return 'cross'
    def on(p,q,r):return orient(p,q,r)==0 and min(p[0],q[0])<=r[0]<=max(p[0],q[0]) and min(p[1],q[1])<=r[1]<=max(p[1],q[1])
    return 'touch' if on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b) else None


def classify(nodes,coords):
    grid=[tuple(round(v*10**7) for v in p) for p in coords]
    counts=collections.Counter();events=[];n=len(grid)-1
    for i in range(n):
        if grid[i]==grid[i+1]:counts['degenerate_pairs']+=1
    for i in range(n):
        if grid[i]==grid[i+1]:continue
        for j in range(i+1,n):
            if grid[j]==grid[j+1]:continue
            # Bounding-box filter is only an accelerator, exact predicate decides.
            a,b,c,d=grid[i],grid[i+1],grid[j],grid[j+1]
            if max(min(a[0],b[0]),min(c[0],d[0]))>min(max(a[0],b[0]),max(c[0],d[0])) or max(min(a[1],b[1]),min(c[1],d[1]))>min(max(a[1],b[1]),max(c[1],d[1])):continue
            kind=relation(a,b,c,d)
            normal=(j==i+1 or (i==0 and j==n-1 and grid[0]==grid[-1]))
            if not kind or (normal and kind=='touch'):continue
            counts[kind]+=1;events.append({'seq':[i,j],'type':kind,'node_ids':[nodes[i:i+2],nodes[j:j+2]],'coordinates':[coords[i:i+2],coords[j:j+2]]})
    # Closing vertex is valid; do not count it as an anomalous repeated vertex.
    interior=grid[:-1] if len(grid)>1 and grid[0]==grid[-1] else grid
    counts['repeated_coordinates']=len(interior)-len(set(interior))
    node_interior=nodes[:-1] if len(nodes)>1 and nodes[0]==nodes[-1] else nodes
    counts['repeated_node_ids']=len(node_interior)-len(set(node_interior))
    exact_simple=not any(counts[k] for k in ['cross','touch','overlap'])
    line=LineString(coords)
    return {'counts':dict(counts),'events':events,'exact_simple':exact_simple,'shapely_simple':bool(line.is_simple),'valid':bool(line.is_valid),'wkt':line.wkt}


def run(db_path,out):
    start=time.monotonic();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect('file:'+str(Path(db_path).resolve())+'?mode=ro',uri=True)
    db.execute('PRAGMA temp_store=FILE')
    summary={'status':'research_only','source_sha256':json.loads(Path('data/stage4/expected-summary.json').read_text())['source_sha256'],'ways_checked':0,'nonsimple_ways':0,'categories':{},'exact_shapely_disagreements':0,'repairs_applied':0}
    totals=collections.Counter();flagged=[];geometry_hashes={};duplicate_geometries=[]
    sql=(out/'geometry-postgis.sql').open('w');sql.write("\\set ON_ERROR_STOP on\nDO $$ BEGIN IF current_database() !~ '^trucksil_stage4_test_' OR inet_server_addr() IS NOT NULL THEN RAISE EXCEPTION 'isolated Unix socket test database required'; END IF; END $$;\nBEGIN;\nCREATE EXTENSION IF NOT EXISTS postgis;\nCREATE TEMP TABLE geometry_audit(way_id bigint,geom geometry(LineString,4326),expected_simple boolean,expected_valid boolean);\nCOPY geometry_audit FROM STDIN WITH(FORMAT csv);\n")
    writer=csv.writer(sql,lineterminator='\n')
    output=(out/'nonsimple-ways.jsonl').open('w')
    rows=db.execute('SELECT way_id,seq,geom FROM segments ORDER BY way_id,seq')
    for way_id,group in itertools.groupby(rows,key=lambda x:x[0]):
        coords=[]
        for _,seq,wkt in group:
            pts=[tuple(map(float,s.split())) for s in wkt[wkt.index('(')+1:wkt.index(')')].split(',')]
            if not coords:coords.append(pts[0])
            coords.append(pts[1])
        summary['ways_checked']+=1
        canonical=min(tuple(coords),tuple(reversed(coords)))
        digest=hashlib.sha256(repr(canonical).encode()).hexdigest()
        if digest in geometry_hashes:duplicate_geometries.append({'way_ids':[geometry_hashes[digest],way_id],'status':'UNKNOWN','reason':'Identical coordinate sequence allowing reversal; semantic duplication not established.'})
        else:geometry_hashes[digest]=way_id
        if LineString(coords).is_simple:continue
        row=db.execute('SELECT version,timestamp,tags,nodes FROM ways WHERE id=?',(way_id,)).fetchone();nodes=json.loads(row[3]);full=[list(db.execute('SELECT lon,lat FROM nodes WHERE id=?',(n,)).fetchone()) for n in nodes]
        result=classify(nodes,full);writer.writerow([way_id,'SRID=4326;'+result.pop('wkt'),str(result['shapely_simple']).lower(),str(result['valid']).lower()])
        summary['nonsimple_ways']+=1;summary['exact_shapely_disagreements']+=result['exact_simple']!=result['shapely_simple']
        for k,v in result['counts'].items():
            if v:totals[k+'_ways']+=1;totals[k+'_events']+=v
        result.update({'way_id':way_id,'version':row[0],'timestamp':row[1],'tags':json.loads(row[2]),'status':'UNKNOWN','reason':'Geometry anomaly observed; road function and legitimacy require review. No source or graph repair.'})
        output.write(json.dumps(result)+'\n');flagged.append(way_id)
    output.close();sql.write('\\.\n');sql.write("DO $$ BEGIN IF EXISTS(SELECT FROM geometry_audit WHERE ST_IsSimple(geom)<>expected_simple OR ST_IsValid(geom)<>expected_valid) THEN RAISE EXCEPTION 'Geometry engine mismatch'; END IF; END $$;\nSELECT count(*) AS all_flagged_ways_checked FROM geometry_audit;\n")
    for item in duplicate_geometries:
        item['objects']=[]
        for wid in item['way_ids']:
            version,stamp,tags,nodes=db.execute('SELECT version,timestamp,tags,nodes FROM ways WHERE id=?',(wid,)).fetchone()
            ids=json.loads(nodes)
            item['objects'].append({'way_id':wid,'version':version,'timestamp':stamp,'tags':json.loads(tags),'node_ids':ids,'coordinates':[list(db.execute('SELECT lon,lat FROM nodes WHERE id=?',(nid,)).fetchone()) for nid in ids]})
        item['reason']='Identical coordinate sequence; different layer/building passage tags require review. No semantic duplicate established.' if len({json.dumps(o['tags'],sort_keys=True) for o in item['objects']})>1 else item['reason']
    (out/'identical-way-geometries.json').write_text(json.dumps(duplicate_geometries,indent=2)+'\n')
    degenerate=[]
    for wid,raw_nodes,count in db.execute('SELECT ways.id,ways.nodes,count(segments.id) FROM ways LEFT JOIN segments ON segments.way_id=ways.id GROUP BY ways.id HAVING json_array_length(ways.nodes)-1<>count(segments.id)'):
        ids=json.loads(raw_nodes);present={r[0] for r in db.execute('SELECT seq FROM segments WHERE way_id=?',(wid,))}
        for seq in set(range(len(ids)-1))-present:
            pair=ids[seq:seq+2];coords=[list(db.execute('SELECT lon,lat FROM nodes WHERE id=?',(nid,)).fetchone()) for nid in pair]
            degenerate.append({'way_id':wid,'seq':seq,'node_ids':pair,'coordinates':coords,'same_node_id':pair[0]==pair[1],'same_coordinate':coords[0]==coords[1],'status':'QUARANTINE','reason':'Excluded by original processor; no new repair.'})
    (out/'degenerate-pairs.json').write_text(json.dumps(degenerate,indent=2)+'\n')
    summary['degenerate_pairs_rechecked']=len(degenerate)

    repeated=(out/'repeated-pairs.jsonl').open('w');groups=extras=same=cross=0;pair_classes=collections.Counter()
    sql.write('CREATE TEMP TABLE repeated_audit(a bigint,b bigint,geom geometry(LineString,4326));\nCOPY repeated_audit FROM STDIN WITH(FORMAT csv);\n')
    repeat_keys={tuple(r[:2]):r[2] for r in db.execute('SELECT min(a,b) aa,max(a,b) bb,count(*) FROM segments GROUP BY aa,bb HAVING count(*)>1')}
    groups=len(repeat_keys);extras=sum(n-1 for n in repeat_keys.values())
    records=collections.defaultdict(list)
    for sid,wid,seq,a,b,geom in db.execute('SELECT id,way_id,seq,a,b,geom FROM segments'):
        key=(min(a,b),max(a,b))
        if key in repeat_keys:records[key].append({'segment_id':sid,'way_id':wid,'seq':seq,'nodes':[a,b],'wkt':geom})
    for (a,b),members in sorted(records.items()):
        distinct=len({m['way_id'] for m in members});same+=distinct==1;cross+=distinct>1
        for m in members:writer.writerow([a,b,'SRID=4326;'+m['wkt']]);m['tags']=json.loads(db.execute('SELECT tags FROM ways WHERE id=?',(m['way_id'],)).fetchone()[0])
        tagsets=[m['tags'] for m in members]
        levels={t.get('layer') for t in tagsets};highways={t.get('highway') for t in tagsets}
        flags=[]
        if len(levels)>1:flags.append('layer_tag_disagreement')
        if len(highways)>1:flags.append('different_highway_classes')
        if len({json.dumps(t,sort_keys=True) for t in tagsets})==1:flags.append('identical_tags')
        else:flags.append('different_tags')
        for flag in flags:pair_classes[flag]+=1
        repeated.write(json.dumps({'evidence_flags':flags,'nodes':[a,b],'members':members,'classification':'within_way_retracing' if distinct==1 else 'shared_geometry_between_ways','status':'UNKNOWN','action':'Do not merge/delete; determine semantic duplication and road levels from source evidence.'})+'\n')
    repeated.close();sql.write("\\.\nDO $$ BEGIN IF EXISTS(SELECT FROM repeated_audit GROUP BY a,b HAVING NOT ST_Equals(ST_Collect(geom),ST_GeometryN(ST_Collect(geom),1))) THEN RAISE EXCEPTION 'Repeated pair geometries differ'; END IF; END $$;\nSELECT 'GEOMETRY AUDIT PASS';\nROLLBACK;\n")
    sql.close();summary.update({'categories':dict(totals),'repeated_pair_groups':groups,'repeated_pair_extra_occurrences':extras,'within_way_only_groups':same,'cross_way_groups':cross,'elapsed_seconds':time.monotonic()-start,'postgis':'NOT_EXECUTED_BY_THIS_SCRIPT','identical_coordinate_sequence_extra_ways':len(duplicate_geometries),'repeat_pair_evidence_flags':dict(pair_classes),'confirmed_semantic_duplicates':0,'national_cross_way_overlaps':'owned by separate infrastructure audit; not inferred from pair counts'})
    summary['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file() and p.name!='summary.json'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));db.close()

def automotive_overlay(output, automotive_database):
    """Read-only membership overlay; does not reclassify or edit either graph."""
    out=Path(output);db=sqlite3.connect('file:'+str(Path(automotive_database).resolve())+'?mode=ro',uri=True)
    groups={'nonsimple_ways':{json.loads(line)['way_id'] for line in (out/'nonsimple-ways.jsonl').read_text().splitlines()},'repeated_pair_ways':{m['way_id'] for line in (out/'repeated-pairs.jsonl').read_text().splitlines() for m in json.loads(line)['members']}}
    statuses={wid:status for wid,status in db.execute('SELECT id,status FROM ways')}
    counts={name:{'ways_by_status':dict(collections.Counter(statuses[wid] for wid in ids)),'segments_by_status':collections.Counter()} for name,ids in groups.items()}
    for wid,status in db.execute('SELECT s.way_id,w.status FROM segments s JOIN ways w ON w.id=s.way_id'):
        for name,ids in groups.items():
            if wid in ids:counts[name]['segments_by_status'][status]+=1
    (out/'automotive-impact.json').write_text(json.dumps(counts,indent=2)+'\n')
    summary=json.loads((out/'summary.json').read_text());summary['automotive_impact']=counts
    summary['artifacts']['automotive-impact.json']=hashlib.sha256((out/'automotive-impact.json').read_bytes()).hexdigest()
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');db.close();return counts

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('database');p.add_argument('output');p.add_argument('--automotive');a=p.parse_args();run(a.database,a.output)
    if a.automotive:automotive_overlay(a.output,a.automotive)
