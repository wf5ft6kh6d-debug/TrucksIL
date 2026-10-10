"""Frozen-source gap inventory; no connection, direction or restriction is inferred."""
import json,sys
from collections import Counter,defaultdict
from decimal import Decimal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from osm_pilot import load_snapshot,normalize


def integer_point(p):
    values=[Decimal(str(v))*10**9 for v in p]
    if any(v!=v.to_integral_value() for v in values):raise ValueError('Coordinate precision unsupported')
    return tuple(map(int,values))


def proper_crossing(a,b,c,d):
    """Strict interior crossing in lon/lat plane; touches/overlaps are separate unknowns."""
    a,b,c,d=map(integer_point,(a,b,c,d))
    def orient(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    return orient(a,b,c)*orient(a,b,d)<0 and orient(c,d,a)*orient(c,d,b)<0


def research():
    p,m=load_snapshot('data/stage3/osm-haifa-20261010');g=normalize(p,m)
    ends=json.loads(Path('data/stage3/endpoint-review-20261010.json').read_text())['endpoints']
    way_lookup={e['id']:e for e in p['elements'] if e['type']=='way'}
    endpoint_rows=[]
    for row in ends:
        n=row['osm_node'];ways=[w for w in way_lookup.values() if n in w['nodes']]
        endpoint_rows.append({**row,'incident_ways':[{'id':w['id'],'version':w['version'],'tags':w['tags']} for w in ways],
            'closure':'open; community tags do not establish physical endpoint or truck permission'})
    unknown=defaultdict(list)
    for s in g['segments']:
        if s['direction']=='unknown':unknown[s['source_way']].append(s['id'])
    directions=[{'way':w,'version':way_lookup[w]['version'],'tags':way_lookup[w]['tags'],'segments':ids,'reason':'oneway absent' if 'oneway' not in way_lookup[w]['tags'] else 'requires review'} for w,ids in sorted(unknown.items())]
    crossings=[];segs=g['segments']
    for i,s in enumerate(segs):
        a,b=s['geometry']['coordinates']
        for t in segs[i+1:]:
            if {s['from_node'],s['to_node']}&{t['from_node'],t['to_node']}:continue
            c,d=t['geometry']['coordinates']
            if max(a[0],b[0])<min(c[0],d[0]) or max(c[0],d[0])<min(a[0],b[0]) or max(a[1],b[1])<min(c[1],d[1]) or max(c[1],d[1])<min(a[1],b[1]):continue
            if proper_crossing(a,b,c,d):
                layers=[s['tags'].get('layer'),t['tags'].get('layer')]
                crossings.append({'segments':[s['id'],t['id']],'ways':[s['source_way'],t['source_way']],'layers':layers,
                   'finding':'explicit_different_layers' if None not in layers and layers[0]!=layers[1] else 'vertical_separation_unknown','connected':False})
    coords=defaultdict(list)
    for n in g['nodes']:coords[tuple(n['geometry']['coordinates'])].append(n['source_node'])
    infrastructure=[{'id':w['id'],'version':w['version'],'nodes':w['nodes'],'tags':w['tags'],'retained_segments':sum(s['source_way']==w['id'] for s in segs)} for w in way_lookup.values() if any(k in w['tags'] for k in ('bridge','tunnel','layer'))]
    summary={'endpoints_reviewed':len(endpoint_rows),'unknown_segments':sum(len(x) for x in unknown.values()),'unknown_ways':len(unknown),
      'unknown_by_highway':dict(sorted(Counter(s['tags']['highway'] for s in segs if s['direction']=='unknown').items())),
      'proper_crossings_without_shared_node':len(crossings),'crossing_findings':dict(Counter(x['finding'] for x in crossings)),
      'coincident_distinct_node_groups':sum(len(v)>1 for v in coords.values()),
      'relation_types':dict(sorted(Counter(r['tags']['restriction'] for r in g['relations']).items())),
      'quarantined_relations':len(g['relations']),'verified_restrictions':0,'graph_changed':False}
    result={'raw_sha256':m['sha256'],'scope_bbox':m['bbox_wgs84'],'summary':summary,'endpoints':endpoint_rows,'directions':directions,'infrastructure':infrastructure,'crossings':crossings,'coincident_distinct_nodes':[v for v in coords.values() if len(v)>1],
       'limits':'Strict interior crossings only; collinear overlaps and endpoint-to-interior contacts not classified; missing layer is unknown, not zero. No physical or legal verification.'}
    return result


def append_crossing_check(sql, result):
    if sql.count("ROLLBACK;") != 1:
        raise ValueError("Expected one rollback in existing guarded replay")
    check=f"""DO $$ BEGIN
 IF (SELECT count(*) FROM road_segments a JOIN road_segments b ON a.segment_id<b.segment_id
    AND a.geometry && b.geometry WHERE ST_Crosses(a.geometry,b.geometry))<>{result["summary"]["proper_crossings_without_shared_node"]} THEN
  RAISE EXCEPTION 'Independent PostGIS crossing count mismatch'; END IF;
END $$;
\\echo 'Independent PostGIS proper crossing count PASS'
"""
    return sql.replace('ROLLBACK;',check+'ROLLBACK;')

if __name__=='__main__':
    r=research();sql=append_crossing_check(Path(sys.argv[2]).read_text(),r);out=Path(sys.argv[1]);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');out.with_suffix('.sql').write_text(sql)
    print(json.dumps(r['summary']))
