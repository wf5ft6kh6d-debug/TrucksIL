"""Independent acceptance: source preservation and derived full-record reconciliation.
No producer decision function is imported. Original databases are opened immutable/read-only.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def readonly(path):
    p = Path(path).resolve()
    if Path(str(p)+'-wal').exists() and Path(str(p)+'-wal').stat().st_size:
        raise ValueError('WAL exists: immutable view could omit committed rows')
    return sqlite3.connect(p.as_uri()+'?mode=ro&immutable=1', uri=True)


def same_json(left, right):
    return json.loads(left) == json.loads(right)


def source_reconcile(source, pbf):
    import osmium
    db = readonly(source)
    candidates = {(r[0],r[1]):r[2:] for r in db.execute('SELECT type,id,version,timestamp,tags,geometry,status FROM candidates')}
    counts = dict(nodes=0, highway_ways=0, candidates=0, relations=0)
    class Check(osmium.SimpleHandler):
        def candidate(self, obj, typ):
            row = candidates.get((typ,obj.id))
            if row is None: return
            assert row[0] == obj.version and row[1] == str(obj.timestamp)
            assert json.loads(row[2]) == dict(obj.tags)
            assert row[4] == 'QUARANTINE'
            if typ == 'node':
                assert json.loads(row[3])['coordinates'] == [obj.location.lon,obj.location.lat]
            counts['candidates'] += 1
        def node(self,obj):
            row = db.execute('SELECT lon,lat FROM nodes WHERE id=?',(obj.id,)).fetchone()
            if row:
                assert row == (obj.location.lon,obj.location.lat)
                counts['nodes'] += 1
            self.candidate(obj,'node')
        def way(self,obj):
            if 'highway' in obj.tags:
                row = db.execute('SELECT version,timestamp,tags,nodes FROM ways WHERE id=?',(obj.id,)).fetchone()
                assert row is not None and row[:2] == (obj.version,str(obj.timestamp))
                assert json.loads(row[2]) == dict(obj.tags)
                assert json.loads(row[3]) == [n.ref for n in obj.nodes]
                counts['highway_ways'] += 1
            self.candidate(obj,'way')
        def relation(self,obj):
            row = db.execute('SELECT version,timestamp,tags,members,status FROM relations WHERE id=?',(obj.id,)).fetchone()
            if row:
                assert row[:2] == (obj.version,str(obj.timestamp))
                assert json.loads(row[2]) == dict(obj.tags)
                assert json.loads(row[3]) == [{'type':m.type,'id':m.ref,'role':m.role} for m in obj.members]
                assert row[4] == 'QUARANTINE'
                counts['relations'] += 1
            self.candidate(obj,'relation')
    Check().apply_file(str(pbf))
    for label,table in [('nodes','nodes'),('highway_ways','ways'),('candidates','candidates'),('relations','relations')]:
        assert counts[label] == db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    db.close()
    return counts


def automotive_reconcile(source, derived):
    db = readonly(derived)
    db.execute('ATTACH DATABASE ? AS original',(Path(source).resolve().as_uri()+'?mode=ro&immutable=1',))
    counts={}
    for table in ['ways','nodes','segments']:
        columns = [r[1] for r in db.execute('PRAGMA original.table_info('+table+')')]
        cols = ','.join(columns)
        for a,b in [('main','original'),('original','main')]:
            assert db.execute(f'SELECT {cols} FROM {a}.{table} EXCEPT SELECT {cols} FROM {b}.{table} LIMIT 1').fetchone() is None
        counts[table]=db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    checked=0
    for tags_raw,status,reason,decision_raw in db.execute('SELECT tags,status,reason,decision FROM ways'):
        t=json.loads(tags_raw);d=json.loads(decision_raw);checked+=1
        assert d['truck_access']=='UNKNOWN' and d['independently_verified'] is False
        assert d['status']==status and d['reason']==reason
        key=next((k for k in ['motorcar','motor_vehicle','vehicle','access'] if k in t),None)
        assert d['access_key']==key and d['access_value']==(t[key] if key else None)
        assert d['hgv_tags']=={k:v for k,v in t.items() if k=='hgv' or k.startswith('hgv:')}
        if status=='INCLUDED':
            assert t.get('highway') in {'motorway','motorway_link','trunk','trunk_link','primary','primary_link','secondary','secondary_link','tertiary','tertiary_link','unclassified','residential','living_street','service'}
            assert t.get('area') in (None,'no')
            assert not any(k.startswith(('construction:','proposed:','abandoned:','disused:','demolished:')) for k in t)
            assert not any(k.startswith(prefix+':') for k in t for prefix in ('motorcar','motor_vehicle','vehicle','access','oneway'))
            assert t.get('oneway') in (None,'yes','1','true','-1','no','0','false')
            assert key is None or t[key] in ('yes','designated','permissive')
            assert not (key=='access' and t[key]=='designated')
        if status=='EXCLUDED':
            assert t.get('area')=='yes' or t.get('highway') in {'footway','pedestrian','cycleway','steps','bridleway','corridor','platform','construction','proposed','abandoned','razed'} or (key is not None and t[key] in ('no','private'))
    views=['automotive_segments','quarantine_segments','excluded_segments']
    partition={v:db.execute('SELECT count(*) FROM '+v).fetchone()[0] for v in views}
    assert sum(partition.values())==counts['segments']
    for i,a in enumerate(views):
        for b in views[i+1:]:
            assert db.execute(f'SELECT id FROM {a} INTERSECT SELECT id FROM {b} LIMIT 1').fetchone() is None
    import networkx as nx
    g=nx.Graph()
    g.add_edges_from(db.execute('SELECT a,b FROM automotive_segments'))
    sizes=sorted(map(len,nx.connected_components(g)),reverse=True)
    network={'nodes':g.number_of_nodes(),'unique_undirected_edges':g.number_of_edges(),'components':len(sizes),'largest_components':sizes[:10]}
    assert g.number_of_nodes()==db.execute('SELECT count(*) FROM automotive_nodes').fetchone()[0]
    db.close()
    return {'preserved_rows':counts,'classification_records_independently_checked':checked,'disjoint_complete_segment_partition':partition,'independent_networkx':network}


def records(path):
    with Path(path).open() as f:
        for line in f:
            yield json.loads(line)


def registry_reconcile(source, root):
    from shapely import wkt
    from shapely.geometry import Polygon, LineString
    from shapely.prepared import prep
    root=Path(root);db=readonly(source);result={}
    infrastructure_summary=json.loads((root/'infrastructure/summary.json').read_text())
    for name,expected in infrastructure_summary['artifact_sha256'].items():
        assert digest(root/'infrastructure'/name)==expected
    seen=set()
    for r in records(root/'truck-evidence/candidates.jsonl'):
        key=(r['osm']['type'],r['osm']['id']);assert key not in seen;seen.add(key)
        row=db.execute('SELECT version,timestamp,tags,categories,geometry,status FROM candidates WHERE type=? AND id=?',key).fetchone()
        assert row is not None
        assert (r['osm']['version'],r['osm']['timestamp'])==row[:2]
        assert [r['raw_tags'],r['categories'],r['geometry']]==[json.loads(x) for x in row[2:5]]
        assert [r['source_payload'][x] for x in ['tags_json','categories_json','geometry_json']]==list(row[2:5])
        assert r['status']==row[5]=='QUARANTINE' and r['navigation_eligible'] is False
        assert r['truck_applicability']=='UNKNOWN' and r['independent_evidence']==[]
        assert r['quarantine_reason'] and r['required_additional_evidence']
        assert r['acceptance']['automatic_promotion'] is False
        assert all(v=='UNKNOWN' for v in r['acceptance']['gate_status'].values())
        assert r['provenance']['license']=='ODbL-1.0' and r['provenance']['sha256']=='dff1ce395df33b8df901b85f7fd822bacd7a10985ceb2d893144251455646670'
        for key,m in r['measurements'].items():
            assert m['raw']==r['raw_tags'][key]
            assert m['status'] in ('UNKNOWN','PARSED_EXPLICIT_UNIT')
            if m['status']=='UNKNOWN':assert m['value'] is None and m['unit'] is None
            else:
                from decimal import Decimal
                raw=m['raw'].strip();unit=m['unit']
                assert unit in ('m','t','kg') and raw.endswith(unit)
                assert Decimal(raw[:-len(unit)].strip())==Decimal(str(m['value']))>0
    assert len(seen)==db.execute('SELECT count(*) FROM candidates').fetchone()[0]
    result['truck_evidence_exact_raw_records']=len(seen)
    coords=[]
    for line in Path('data/stage4/source-boundary.poly').read_text().splitlines():
        parts=line.split()
        if len(parts)==2:
            try:coords.append(tuple(map(float,parts)))
            except ValueError:pass
    poly=Polygon(coords); prepared=prep(poly);outside=set()
    for ident,geom in db.execute('SELECT id,geom FROM segments'):
        if not prepared.covers(wkt.loads(geom).interpolate(.5,normalized=True)):outside.add(ident)
    seen=set()
    for r in records(root/'boundary/outside-segments.jsonl'):
        ident=r['segment_id'];assert ident not in seen;seen.add(ident)
        row=db.execute('SELECT way_id,a,b,seq,geom FROM segments WHERE id=?',(ident,)).fetchone()
        assert [row[0],row[1],row[2],row[3]]==[r['osm_way_id'],*r['osm_node_ids'],r['sequence']]
        line=wkt.loads(row[4]);assert list(map(list,line.coords))==r['coordinates_wgs84']
        assert line.relate(poly)==r['line_polygon_de9im']
        assert r['cause_status']=='UNKNOWN' and r['source_polygon_is_country_border'] is False
        source_way=db.execute('SELECT version,timestamp,tags FROM ways WHERE id=?',(r['osm_way_id'],)).fetchone()
        assert source_way[:2]==(r['osm_way_version'],r['osm_way_timestamp']) and json.loads(source_way[2])==r['tags']
    assert seen==outside
    result['boundary_complete_recomputed_outside_ids']=len(seen)
    nonsimple={}
    for r in records(root/'geometry/nonsimple-ways.jsonl'):
        ident=r['way_id'];assert ident not in nonsimple;nonsimple[ident]=r
        row=db.execute('SELECT version,timestamp,tags,nodes FROM ways WHERE id=?',(ident,)).fetchone()
        assert row[:2]==(r['version'],r['timestamp']) and json.loads(row[2])==r['tags']
        coords=[db.execute('SELECT lon,lat FROM nodes WHERE id=?',(n,)).fetchone() for n in json.loads(row[3])]
        assert not LineString(coords).is_simple and r['exact_simple'] is False and r['status']=='UNKNOWN'
    # Independent SQL establishes complete repeated-node-pair membership.
    groups={(a,b):n for a,b,n in db.execute('SELECT min(a,b),max(a,b),count(*) FROM segments GROUP BY min(a,b),max(a,b) HAVING count(*)>1')}
    seen=set();extra=0
    for r in records(root/'geometry/repeated-pairs.jsonl'):
        key=tuple(r['nodes']);assert key not in seen;seen.add(key)
        assert len(r['members'])==groups[key];extra+=len(r['members'])-1
        for member in r['members']:
            row=db.execute('SELECT way_id,seq,a,b,geom FROM segments WHERE id=?',(member['segment_id'],)).fetchone()
            assert list(row)==[member['way_id'],member['seq'],*member['nodes'],member['wkt']]
        assert r['status']=='UNKNOWN'
    assert seen==set(groups)
    result['geometry']={'nonsimple_rows_source_rechecked':len(nonsimple),'repeated_pair_groups_complete':len(groups),'extra_pair_occurrences':extra,'nonsimple_completeness':'producer full-scan plus independent integer geometry; audit rechecks each flagged way'}
    expected_infra={ident for ident,tags in db.execute('SELECT id,tags FROM ways') if any(json.loads(tags).get(k) is not None and str(json.loads(tags)[k]).lower() not in ('no','false','0') for k in ['bridge','tunnel'])}
    infra_seen=set()
    for r in records(root/'infrastructure/infrastructure-ways.jsonl'):
        ident=r['id'];assert ident not in infra_seen;infra_seen.add(ident)
        row=db.execute('SELECT version,timestamp,tags,nodes FROM ways WHERE id=?',(ident,)).fetchone()
        assert row[:2]==(r['version'],r['timestamp']) and json.loads(row[2])==r['tags'] and json.loads(row[3])==r['nodes']
        assert r['status']=='UNKNOWN' and r['truck_permission']=='UNKNOWN'
        assert all(e['physical_portal_status']=='UNKNOWN' for e in r['endpoints'])
        assert [e['node_id'] for e in r['endpoints']]==[r['nodes'][0],r['nodes'][-1]]
        for e in r['endpoints']:
            assert list(db.execute('SELECT lon,lat FROM nodes WHERE id=?',(e['node_id'],)).fetchone())==e['coordinate']
    assert infra_seen==expected_infra
    from functools import lru_cache
    @lru_cache(maxsize=40000)
    def way(ident):
        row=db.execute('SELECT version,tags,nodes FROM ways WHERE id=?',(ident,)).fetchone()
        nodes=json.loads(row[2]);shape=LineString([db.execute('SELECT lon,lat FROM nodes WHERE id=?',(n,)).fetchone() for n in nodes])
        return row[0],json.loads(row[1]),set(nodes),shape
    pairs=set()
    for r in records(root/'infrastructure/infrastructure-intersections.jsonl'):
        a,b=r['way_ids'];key=tuple(sorted((a,b)));assert key not in pairs;pairs.add(key)
        x,y=way(a),way(b)
        assert r['source_versions']==[x[0],y[0]]
        if 'tags' in r:assert r['tags']==[x[1],y[1]]
        assert set(r['common_node_ids'])==x[2]&y[2]
        assert x[3].relate(y[3])==r['relate']
        for k,value in r['predicates'].items():assert bool(getattr(x[3],k)(y[3]))==value
        assert r['status']=='UNKNOWN' and r['physical_connection_verified'] is False
        if 'geometry' in r:
            from shapely.geometry import shape
            assert shape(r['geometry']).equals(x[3].intersection(y[3]))
    turns=set()
    for r in records(root/'infrastructure/turn-relations.jsonl'):
        ident=r['id'];assert ident not in turns;turns.add(ident)
        row=db.execute('SELECT version,timestamp,tags,members,missing_refs,status FROM relations WHERE id=?',(ident,)).fetchone()
        assert row[:2]==(r['version'],r['timestamp'])
        assert [json.loads(v) for v in row[2:5]]==[r['tags'],r['members'],r['missing_source_refs']]
        assert r['status']==row[5]=='QUARANTINE'
    assert len(turns)==db.execute('SELECT count(*) FROM relations').fetchone()[0]
    assert len(pairs)==infrastructure_summary['intersecting_pairs']
    result['infrastructure']={'complete_infrastructure_way_ids':len(infra_seen),'pair_records_predicates_recomputed':len(pairs),'complete_turn_raw_records':len(turns),'physical_or_official_verification':0}
    db.close();return result

def run(args):
    source=Path(args.source); pbf=Path(args.pbf)
    before={'sqlite':digest(source),'pbf':digest(pbf)}
    assert before['pbf']=='dff1ce395df33b8df901b85f7fd822bacd7a10985ceb2d893144251455646670'
    result={'source_hashes_before':before,'source_pbf_reconciliation':source_reconcile(source,pbf)}
    if args.automotive:
        result['automotive']=automotive_reconcile(source,args.automotive)
    if args.audit_root:
        result['registries']=registry_reconcile(source,args.audit_root)
    after={'sqlite':digest(source),'pbf':digest(pbf)}
    assert after==before
    result['source_hashes_after']=after
    result['source_preservation']='PASS'
    result['claims_excluded']=['official truck restriction verification','physical road safety','legal national boundary','full national pairwise intersection audit']
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--pbf',required=True);p.add_argument('--output',required=True);p.add_argument('--automotive');p.add_argument('--audit-root');run(p.parse_args())
