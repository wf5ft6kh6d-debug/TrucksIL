"""Research-only, full-extract streaming graph. Never authorizes truck travel.
Every edge is an original consecutive node pair; no geometric snapping/connections.
"""
import argparse, collections, hashlib, json, math, resource, sqlite3, time
from pathlib import Path

CATEGORIES=('maxheight','maxweight','maxaxleload','maxwidth','maxlength','hgv','hazmat')
def categories(tags):
    result=[k for k in CATEGORIES if any(t==k or t.startswith(k+':') for t in tags)]
    if any(':conditional' in t for t in tags): result.append('conditional')
    if tags.get('type')=='restriction' or any(t.startswith('restriction') for t in tags):result.append('turn_restriction')
    if tags.get('bridge') not in (None,'no'):result.append('bridge_context')
    if tags.get('tunnel') not in (None,'no'):result.append('tunnel_context')
    return result

def direction(tags):
    # No implicit motorway/roundabout/default national rule is authorized here.
    return {'yes':'forward','1':'forward','true':'forward','-1':'reverse','no':'both','0':'both','false':'both'}.get(tags.get('oneway'),'unknown')

def tile(lon,lat):return f'{math.floor(lon*2)/2:.1f},{math.floor(lat*2)/2:.1f}'
def segment(a,b):
    if a[0]==b[0] or a[1:]==b[1:]:return None
    if not all(math.isfinite(x) for x in (*a[1:],*b[1:])):raise ValueError('nonfinite')
    if not all(-180<=n[1]<=180 and -90<=n[2]<=90 for n in (a,b)):raise ValueError('WGS84 bounds')
    return f'LINESTRING({a[1]} {a[2]},{b[1]} {b[2]})'
class DSU:
    def __init__(self):self.p={};self.size={}
    def find(self,x):
        if x not in self.p:self.p[x]=x;self.size[x]=1
        while x!=self.p[x]:self.p[x]=self.p[self.p[x]];x=self.p[x]
        return x
    def join(self,a,b):
        a,b=self.find(a),self.find(b)
        if a==b:return
        if self.size[a]<self.size[b]:a,b=b,a
        self.p[b]=a;self.size[a]+=self.size[b]
    def sizes(self):return sorted((self.size[x] for x in self.p if self.p[x]==x),reverse=True)

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def build(pbf,out,manifest):
    import osmium
    from shapely.geometry import shape,Point
    from shapely.prepared import prep
    from shapely import wkt
    from pyproj import Geod
    start=time.monotonic();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if (out/'graph.sqlite').exists():raise ValueError('Refuse overwrite; use a new output directory')
    expected=json.loads(Path(manifest).read_text());assert sha(pbf)==expected['sha256'],'source checksum'
    db=sqlite3.connect(out/'graph.sqlite');db.executescript('''
    PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
    CREATE TABLE ways(id INTEGER PRIMARY KEY,version INTEGER,timestamp TEXT,tags TEXT,nodes TEXT);
    CREATE TABLE nodes(id INTEGER PRIMARY KEY,lon REAL,lat REAL);
    CREATE TABLE segments(id INTEGER PRIMARY KEY,way_id INTEGER REFERENCES ways,seq INTEGER,a INTEGER REFERENCES nodes,b INTEGER REFERENCES nodes,direction TEXT,geom TEXT,length_m REAL,tile TEXT);
    CREATE TABLE candidates(type TEXT,id INTEGER,version INTEGER,timestamp TEXT,tags TEXT,categories TEXT,geometry TEXT,status TEXT CHECK(status='QUARANTINE'),PRIMARY KEY(type,id));
    CREATE TABLE relations(id INTEGER PRIMARY KEY,version INTEGER,timestamp TEXT,tags TEXT,members TEXT,missing_refs TEXT,status TEXT CHECK(status='QUARANTINE'));
    ''')
    counts=collections.Counter();cat=collections.Counter();classes=collections.Counter();dirs=collections.Counter();tiles=collections.Counter();levels=collections.Counter();uf=DSU();degrees=collections.Counter();geod=Geod(ellps='WGS84');seen={'n':set(),'w':set(),'r':set()};relations=[];areas=[];errors=[];gf=osmium.geom.GeoJSONFactory()
    def candidate(kind,o,t,g):
        cs=categories(t)
        if cs:
            cat.update(cs);db.execute('INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?)',(kind,o.id,o.version,str(o.timestamp),json.dumps(t,ensure_ascii=False),json.dumps(cs),json.dumps(g),'QUARANTINE'))
    class Handler(osmium.SimpleHandler):
        def node(self,n):
            if n.id in seen['n']:raise ValueError('duplicate node ID')
            seen['n'].add(n.id);counts['source_nodes']+=1
            if len(n.tags) and categories(dict(n.tags)):
                candidate('node',n,dict(n.tags),{'type':'Point','coordinates':[n.location.lon,n.location.lat]})
        def way(self,w):
            if w.id in seen['w']:raise ValueError('duplicate way ID')
            seen['w'].add(w.id);counts['source_ways']+=1;t=dict(w.tags)
            if 'highway' not in t and not categories(t):return
            coords=[];missing=[]
            for n in w.nodes:
                if not n.location.valid():missing.append(n.ref)
                else:coords.append((n.ref,n.lon,n.lat))
            geom=None if missing or len(coords)<2 else {'type':'LineString','coordinates':[[n[1],n[2]] for n in coords]}
            candidate('way',w,t,geom)
            if 'highway' not in t:return
            counts['highway_ways']+=1;classes[t['highway']]+=1
            db.execute('INSERT INTO ways VALUES(?,?,?,?,?)',(w.id,w.version,str(w.timestamp),json.dumps(t,ensure_ascii=False),json.dumps([n.ref for n in w.nodes])))
            if missing:
                counts['ways_missing_nodes']+=1;errors.append({'way':w.id,'missing':missing});return
            counts['complete_highway_ways']+=1
            if geom:
                line=shape(geom)
                counts['nonsimple_ways']+=int(not line.is_simple);counts['invalid_ways']+=int(not line.is_valid)
            db.executemany('INSERT OR IGNORE INTO nodes VALUES(?,?,?)',coords)
            dr=direction(t);levels[str(t.get('layer','unknown'))]+=1
            for seq,(a,b) in enumerate(zip(coords,coords[1:])):
                counts['source_highway_pairs']+=1;g=segment(a,b)
                if g is None:
                    counts['degenerate_pairs_quarantined']+=1;errors.append({'way':w.id,'seq':seq,'reason':'same_id_or_coordinate'});continue
                counts['segments']+=1;uf.join(a[0],b[0]);degrees[a[0]]+=1;degrees[b[0]]+=1;dirs[dr]+=1
                cell=tile((a[1]+b[1])/2,(a[2]+b[2])/2);tiles[cell]+=1
                length=geod.inv(a[1],a[2],b[1],b[2])[2]
                db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?,?,?,?)',(counts['segments'],w.id,seq,a[0],b[0],dr,g,length,cell))
            if counts['highway_ways']%20000==0:db.commit();print('ways',counts['highway_ways'],'segments',counts['segments'],flush=True)
        def relation(self,r):
            if r.id in seen['r']:raise ValueError('duplicate relation ID')
            seen['r'].add(r.id);counts['source_relations']+=1;t=dict(r.tags)
            if categories(t):
                members=[{'type':m.type,'id':m.ref,'role':m.role} for m in r.members]
                candidate('relation',r,t,{'member_references':members,'assembly':'not_inferred'})
                if 'turn_restriction' in categories(t):relations.append((r.id,r.version,str(r.timestamp),json.dumps(t,ensure_ascii=False),members))
        def area(self,a):
            t=dict(a.tags)
            if t.get('boundary')=='administrative' and t.get('admin_level')=='4' and t.get('ISO3166-2','').startswith('IL-'):
                try:
                    g=json.loads(gf.create_multipolygon(a));s=shape(g)
                    areas.append({'osm_relation_id':a.orig_id(),'version':a.version,'timestamp':str(a.timestamp),'name':t.get('name:en',t.get('name')),'code':t['ISO3166-2'],'geometry':g,'valid':s.is_valid,'source':'same OSM snapshot; not official border'})
                except Exception as e:errors.append({'area':a.orig_id(),'reason':str(e)})
    Handler().apply_file(str(pbf),locations=True,idx='flex_mem')
    for rid,v,ts,t,members in relations:
        missing=[m for m in members if m['id'] not in seen[m['type']]]
        counts['turn_relations_missing_refs']+=bool(missing)
        db.execute('INSERT INTO relations VALUES(?,?,?,?,?,?,?)',(rid,v,ts,t,json.dumps(members),json.dumps(missing),'QUARANTINE'))
    counts['turn_relations']=len(relations);counts['road_nodes']=db.execute('SELECT count(*) FROM nodes').fetchone()[0]
    counts['graph_nodes_with_edges']=len(uf.p);counts['leaf_nodes']=sum(v==1 for v in degrees.values());counts['components']=len(uf.sizes())
    db.executescript('CREATE INDEX segment_way ON segments(way_id); CREATE INDEX segment_a ON segments(a); CREATE INDEX segment_b ON segments(b); CREATE INDEX segment_tile ON segments(tile);');db.commit()
    # Identical undirected node pairs are candidates, not automatically duplicates to delete.
    counts['repeated_node_pairs']=db.execute('SELECT coalesce(sum(c-1),0) FROM (SELECT count(*) c FROM segments GROUP BY min(a,b),max(a,b) HAVING count(*)>1)').fetchone()[0]
    counts['foreign_key_errors']=len(db.execute('PRAGMA foreign_key_check').fetchall())
    region_counts=collections.Counter();region_lengths=collections.Counter();geoms=[prep(shape(a['geometry'])) for a in areas]
    for g,length in db.execute('SELECT geom,length_m FROM segments'):
        pt=wkt.loads(g).interpolate(.5,normalized=True);hits=[a['code'] for a,s in zip(areas,geoms) if s.covers(pt)]
        key=hits[0] if len(hits)==1 else ('MULTIPLE_OSM_REGIONS' if hits else 'UNASSIGNED_OR_OUTSIDE_IL_DISTRICTS')
        region_counts[key]+=1;region_lengths[key]+=length
    summary={'source_sha256':expected['sha256'],'snapshot_at':expected['snapshot_at'],'counts':dict(counts),'highway_classes':dict(classes),'direction_segments':dict(dirs),'candidate_categories':dict(cat),'layer_way_counts':dict(levels),'component_sizes':uf.sizes(),'tiles_0_5_degree_segments':dict(tiles),'regions_midpoint_assignment':{k:{'segments':v,'length_km':region_lengths[k]/1000} for k,v in region_counts.items()},'region_boundary_count':len(areas),'verified_restrictions':0,'navigation_approved':False,'coverage_denominator':'all highway tags in source extract, not physical roads of Israel','country_coverage_percent':None,'truck_restriction_completeness_percent':None,'processing_seconds':time.monotonic()-start,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    for name,obj in [('summary.json',summary),('regions.json',areas),('quarantine-errors.json',errors)]: (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    db.close();print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('pbf');p.add_argument('output');p.add_argument('--manifest',default='data/stage4/national-source-manifest.json');a=p.parse_args();build(a.pbf,a.output,a.manifest)
