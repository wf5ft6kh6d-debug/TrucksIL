"""Read-only full-extract boundary audit; classifications are geometric, not legal."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import shapely
from shapely.geometry import LineString, Polygon, MultiPolygon


def load_poly(path):
    lines=iter(Path(path).read_text().splitlines());next(lines)
    outers=[];holes=[]
    for label in lines:
        label=label.strip()
        if label=='END':break
        if not label:continue
        ring=[]
        for row in lines:
            if row.strip()=='END':break
            ring.append(tuple(map(float,row.split())))
        (holes if label.startswith('!') else outers).append(Polygon(ring))
    if not outers:raise ValueError('No polygon rings')
    polygon=shapely.union_all(outers)
    if holes:polygon=polygon.difference(shapely.union_all(holes))
    if not polygon.is_valid:raise ValueError('Invalid source polygon')
    return polygon


def classify(line, parent, polygon):
    """Never infer source-extraction mechanism or geographic sovereignty."""
    if polygon.covers(line.interpolate(.5,normalized=True)):
        return 'MIDPOINT_COVERED'
    if line.crosses(polygon):return 'SEGMENT_CROSSES_SOURCE_BOUNDARY'
    if line.touches(polygon):return 'SEGMENT_TOUCHES_SOURCE_BOUNDARY'
    if line.intersects(polygon):return 'SEGMENT_INTERSECTS_SOURCE_POLYGON'
    if parent.intersects(polygon):return 'OUTSIDE_SEGMENT_OF_INTERSECTING_WAY'
    return 'ENTIRE_WAY_OUTSIDE_SOURCE_POLYGON'


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def run(database, boundary, out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    target=out/'outside-segments.jsonl'
    if target.exists():raise ValueError('Refuse overwrite of audit registry')
    started=time.monotonic();poly=load_poly(boundary);shapely.prepare(poly)
    source_summary=json.loads((Path(database).parent/'summary.json').read_text())
    db=sqlite3.connect('file:'+str(Path(database).resolve())+'?mode=ro',uri=True)
    counts=Counter();ways={};n=0
    with target.open('w') as f:
        cursor=db.execute('SELECT id,way_id,seq,a,b,geom FROM segments ORDER BY id')
        while rows:=cursor.fetchmany(50000):
            geoms=shapely.from_wkt([r[5] for r in rows]);mids=shapely.line_interpolate_point(geoms,.5,normalized=True)
            covered=shapely.covers(poly,mids);n+=len(rows)
            for row,line,mid,inside in zip(rows,geoms,mids,covered):
                if inside:continue
                sid,wid,seq,a,b,_=row
                if wid not in ways:
                    version,stamp,tags,nodes=db.execute('SELECT version,timestamp,tags,nodes FROM ways WHERE id=?',(wid,)).fetchone()
                    nodes=json.loads(nodes)
                    coords=[db.execute('SELECT lon,lat FROM nodes WHERE id=?',(node,)).fetchone() for node in nodes]
                    if any(x is None for x in coords):raise ValueError('Missing road node in parent way')
                    ways[wid]=(LineString(coords),version,stamp,json.loads(tags),nodes)
                parent,version,stamp,tags,nodes=ways[wid];kind=classify(line,parent,poly);counts[kind]+=1
                rec={'segment_id':sid,'osm_way_id':wid,'osm_way_version':version,'osm_way_timestamp':stamp,'sequence':seq,'osm_node_ids':[a,b],'coordinates_wgs84':list(line.coords),'midpoint_wgs84':[mid.x,mid.y],'classification':kind,'geometry_observation_status':'VERIFIED','cause_status':'UNKNOWN','status':'QUARANTINE','source_polygon_is_country_border':False,'line_polygon_de9im':line.relate(poly),'parent_way_intersects_source_polygon':parent.intersects(poly),'tags':tags,'next_action':'Retain source geometry; do not infer national membership or extraction cause from this polygon.'}
                f.write(json.dumps(rec,sort_keys=True,ensure_ascii=False)+'\n')
    relation=db.execute('SELECT version,timestamp,tags,members,missing_refs,status FROM relations WHERE id=12411556').fetchone()
    missing={'osm_relation_id':12411556,'version':relation[0],'timestamp':relation[1],'tags':json.loads(relation[2]),'members':json.loads(relation[3]),'missing_refs':json.loads(relation[4]),'status':relation[5],'missing_way_in_highway_table':db.execute('SELECT count(*) FROM ways WHERE id=914423926').fetchone()[0]==0,'via_node_wgs84':db.execute('SELECT lon,lat FROM nodes WHERE id=330815713').fetchone(),'reconstruction':'NOT PERFORMED','cause':'UNKNOWN; absence alone does not distinguish clipping, deletion or incomplete membership'}
    result={'schema_version':1,'source_sha256':source_summary['source_sha256'],'source_boundary_sha256':digest(boundary),'boundary_semantics':'Geofabrik extract polygon; not an official national border','segments_scanned':n,'outside_midpoint_segments':sum(counts.values()),'affected_ways':len(ways),'classifications':dict(sorted(counts.items())),'registry_sha256':digest(target),'registry_file':target.name,'missing_relation':missing,'graph_modified':False,'elapsed_seconds':time.monotonic()-started}
    (out/'boundary-summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n');db.close();return result



def export_postgis(database,boundary,registry,output):
    """Independent PostGIS replay of every outside-midpoint candidate. No graph writes."""
    db=sqlite3.connect('file:'+str(Path(database).resolve())+'?mode=ro',uri=True)
    records=[json.loads(x) for x in Path(registry).read_text().splitlines()]
    poly=load_poly(boundary)
    with Path(output).open('w') as f:
        f.write("\\set ON_ERROR_STOP on\nBEGIN;\nDO $$ BEGIN IF current_database() !~ '^trucksil_stage4_test_' OR inet_server_addr() IS NOT NULL THEN RAISE EXCEPTION 'isolated stage4 Unix socket test database required'; END IF; END $$;\n")
        f.write("CREATE TEMP TABLE boundary_polygon(geom geometry);\nINSERT INTO boundary_polygon VALUES(ST_GeomFromText('%s',4326));\n"%poly.wkt)
        f.write("CREATE TEMP TABLE boundary_parents(id bigint PRIMARY KEY,geom geometry);\nCOPY boundary_parents FROM STDIN;\n")
        for wid in sorted({r['osm_way_id'] for r in records}):
            ns=json.loads(db.execute('SELECT nodes FROM ways WHERE id=?',(wid,)).fetchone()[0]);coords=[db.execute('SELECT lon,lat FROM nodes WHERE id=?',(n,)).fetchone() for n in ns]
            f.write(f'{wid}\tSRID=4326;{LineString(coords).wkt}\n')
        f.write('\\.\nCREATE TEMP TABLE boundary_cases(id bigint PRIMARY KEY,way_id bigint,geom geometry,expected text,relate text);\nCOPY boundary_cases FROM STDIN;\n')
        for r in records:f.write(f"{r['segment_id']}\t{r['osm_way_id']}\tSRID=4326;{LineString(r['coordinates_wgs84']).wkt}\t{r['classification']}\t{r['line_polygon_de9im']}\n")
        f.write('\\.\n')
        f.write("""DO $$ DECLARE mismatches bigint; BEGIN
 SELECT count(*) INTO mismatches FROM boundary_cases c JOIN boundary_parents w ON w.id=c.way_id CROSS JOIN boundary_polygon p
 WHERE ST_Covers(p.geom,ST_LineInterpolatePoint(c.geom,0.5)) OR ST_Relate(c.geom,p.geom)<>c.relate OR c.expected<>
 CASE WHEN ST_Crosses(c.geom,p.geom) THEN 'SEGMENT_CROSSES_SOURCE_BOUNDARY'
 WHEN ST_Touches(c.geom,p.geom) THEN 'SEGMENT_TOUCHES_SOURCE_BOUNDARY'
 WHEN ST_Intersects(c.geom,p.geom) THEN 'SEGMENT_INTERSECTS_SOURCE_POLYGON'
 WHEN ST_Intersects(w.geom,p.geom) THEN 'OUTSIDE_SEGMENT_OF_INTERSECTING_WAY'
 ELSE 'ENTIRE_WAY_OUTSIDE_SOURCE_POLYGON' END;
 IF mismatches<>0 THEN RAISE EXCEPTION 'boundary predicate mismatch count %',mismatches; END IF;
END $$;
SELECT 'BOUNDARY PREDICATES PASS',count(*) FROM boundary_cases;
ROLLBACK;
""")
    db.close()


def sanitized_osm_history(xml_bytes,object_type):
    """Retain technical OSM evidence but never contributor identity/changeset metadata."""
    import xml.etree.ElementTree as ET
    if object_type not in {'way','relation','node'}:raise ValueError('Unsupported OSM object type')
    result=[]
    for el in ET.fromstring(xml_bytes).findall(object_type):
        record={k:el.get(k) for k in ('id','version','timestamp','visible')}
        record['tags']={x.get('k'):x.get('v') for x in el.findall('tag')}
        record['nodes']=[x.get('ref') for x in el.findall('nd')]
        record['members']=[{k:x.get(k) for k in ('type','ref','role')} for x in el.findall('member')]
        result.append(record)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--database',required=True);p.add_argument('--boundary',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=run(a.database,a.boundary,a.output)
    export_postgis(a.database,a.boundary,Path(a.output)/'outside-segments.jsonl',Path(a.output)/'boundary-postgis.sql')
    print(json.dumps(result,indent=2))
