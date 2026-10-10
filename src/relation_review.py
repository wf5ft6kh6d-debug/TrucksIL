"""Evidence diagnostics only: raw topology is not verified traffic permission."""
from collections import Counter,defaultdict
import gzip,hashlib,json
from pathlib import Path
from osm_pilot import ROAD_CLASSES,inside,loads,coordinate,positive_id
from pilot_graph_audit import components
from ingest_restrictions import timestamp
IDS=(10115408,10115411,12303230,13395546)


def direction(tags):
    if any(k.startswith('oneway:') for k in tags):return 'unknown'
    return {'yes':'forward','1':'forward','true':'forward','-1':'reverse','no':'both','0':'both','false':'both'}.get(tags.get('oneway'),'unknown')


def review_relation(relation,objects,bbox):
    roles={k:[x for x in relation['members'] if x['role']==k] for k in ('from','via','to')}
    r={'id':relation['id'],'version':relation['version'],'tags':relation['tags'],
       'members':relation['members'],'status':'quarantine','truck_applicability':'unknown',
       'conditional_or_modal_tags':{k:v for k,v in relation['tags'].items() if k not in ('type','restriction')},
       'role_counts':{k:len(v) for k,v in roles.items()},'member_evidence':[]}
    for x in relation['members']:
        e=objects.get((x['type'],x['ref']))
        if e is None:r['member_evidence'].append({'type':x['type'],'id':x['ref'],'missing':True});continue
        obj={k:v for k,v in e.items() if k not in ('user','uid')}
        if e['type']=='way':
            obj['coordinates']=[[objects['node',n]['lon'],objects['node',n]['lat']] for n in e['nodes']]
            obj['direction_model']=direction(e.get('tags',{}))
        if e['type']=='node':obj['inside_pilot']=inside([e['lon'],e['lat']],bbox)
        r['member_evidence'].append(obj)
    if not roles['from']:r['finding']='missing_from_member';return r
    if len(relation['members'])!=3 or any(len(v)!=1 for v in roles.values()) or roles['via'][0]['type']!='node' or any(roles[k][0]['type']!='way' for k in ('from','to')):
        r['finding']='unsupported_structure';return r
    if any((x['type'],x['ref']) not in objects for x in relation['members']):r['finding']='missing_object';return r
    via=roles['via'][0]['ref'];fw=objects['way',roles['from'][0]['ref']];tw=objects['way',roles['to'][0]['ref']]
    def adjacent(w,incoming):
        matches=[];d=direction(w.get('tags',{}))
        for a,b in zip(w['nodes'],w['nodes'][1:]):
            for x,y in ([(a,b)] if d=='forward' else [(b,a)] if d=='reverse' else [(a,b),(b,a)] if d=='both' else []):
                if (y if incoming else x)==via:matches.append([x,y])
        return matches
    r['incoming_arcs']=adjacent(fw,True);r['outgoing_arcs']=adjacent(tw,False)
    if via not in fw['nodes'] or via not in tw['nodes']:r['finding']='disconnected_geometry'
    elif r['conditional_or_modal_tags'] or any(direction(w.get('tags',{}))=='unknown' for w in (fw,tw)):r['finding']='unknown_semantics_or_direction'
    elif not r['incoming_arcs'] or not r['outgoing_arcs']:
        r['finding']='prohibited_manoeuvre_already_unreachable' if relation['tags'].get('restriction','').startswith('no_') else 'required_manoeuvre_direction_conflict'
    else:r['finding']='structurally_connected_unverified'
    return r


def topology_diagnostics(base,manifest,graph):
    objects={(e['type'],e['id']):e for e in base['elements']};bbox=manifest['bbox_wgs84']
    full_edges=[];incidents=defaultdict(list)
    for e in base['elements']:
        if e['type']!='way':continue
        tags=e.get('tags',{});eligible=tags.get('highway') in ROAD_CLASSES and tags.get('area')!='yes'
        for a,b in zip(e['nodes'],e['nodes'][1:]):
            pa=[objects['node',a]['lon'],objects['node',a]['lat']];pb=[objects['node',b]['lon'],objects['node',b]['lat']]
            if a==b or pa==pb:continue
            if eligible:full_edges.append((a,b))
            for n,other,point in [(a,b,pb),(b,a,pa)]:
                incidents[n].append({'way':e['id'],'other':other,'eligible':eligible,'other_outside':not inside(point,bbox),'highway':tags.get('highway')})
    nodeids={n['id']:n['source_node'] for n in graph['nodes']};edges=[(nodeids[s['from_node']],nodeids[s['to_node']]) for s in graph['segments']]
    deg=Counter(n for pair in edges for n in pair);leaves=[]
    for n in sorted(k for k,v in deg.items() if v==1):
        boundary=[x for x in incidents[n] if x['eligible'] and x['other_outside']]
        excluded=[x for x in incidents[n] if not x['eligible']]
        leaves.append({'node':n,'tags':objects['node',n].get('tags',{}),'boundary_continuations':boundary,'filtered_continuations':excluded,
          'finding':'bbox_cut' if boundary else 'filtered_class_adjacency' if excluded else 'source_endpoint_unresolved'})
    full=components({n for pair in full_edges for n in pair},full_edges)
    full_index={n:i for i,c in enumerate(full) for n in c}
    clipped=components(set(nodeids.values()),edges)
    rows=[{'nodes':c,'size':len(c),'full_raw_component':full_index[c[0]],'boundary_leaves':[l['node'] for l in leaves if l['node'] in c and l['boundary_continuations']]} for c in clipped]
    reasons=Counter();unknown_ways=set()
    for s in graph['segments']:
        if s['direction']!='unknown':continue
        unknown_ways.add(s['source_way']);t=s['tags']
        reasons['qualified_oneway' if any(k.startswith('oneway:') for k in t) else 'missing_oneway' if 'oneway' not in t else 'unsupported_oneway_value']+=1
    return {'leaves':leaves,'components':rows,'full_raw_eligible_edges':full_edges,
      'summary':{'leaf_findings':dict(sorted(Counter(l['finding'] for l in leaves).items())),
       'unknown_direction_reasons':dict(sorted(reasons.items())),'unknown_direction_ways':len(unknown_ways),
       'clipped_components':len(clipped),'full_raw_components_touching_pilot':len({x['full_raw_component'] for x in rows}),
       'verified_restrictions':0,'graph_changed':False}}


def load_current(folder):
    p=Path(folder);m=loads((p/'manifest.json').read_bytes());raw=gzip.decompress((p/'raw.json.gz').read_bytes())
    if len(raw)!=m['bytes'] or hashlib.sha256(raw).hexdigest()!=m['sha256']:raise ValueError('Review checksum mismatch')
    if m['license']['identifier']!='ODbL-1.0' or m['license']['decision']!='permitted' or m['license']['evidence_url']!='https://www.openstreetmap.org/copyright':raise ValueError('Unlicensed review')
    if m['scope']!='four relation version comparisons only; never merge into pilot':raise ValueError('Review scope mismatch')
    if m['bbox_wgs84']!=[34.990,32.811,35.004,32.821] or timestamp(m['source_snapshot_at'])>timestamp(m['retrieved_at']):raise ValueError('Review bbox/date mismatch')
    d=loads(raw)
    if 'remark' in d or d['osm3s']['timestamp_osm_base']!=m['source_snapshot_at']:raise ValueError('Partial/stale review')
    objects={(e['type'],e['id']):e for e in d['elements']}
    if len(objects)!=len(d['elements']) or {i for t,i in objects if t=='relation'}!=set(IDS):raise ValueError('Duplicate/missing relations')
    wanted={('relation',i) for i in IDS}
    for i in IDS:
        for x in objects['relation',i]['members']:wanted.add((x['type'],x['ref']))
    for typ,ident in list(wanted):
        if (typ,ident) not in objects:raise ValueError('Missing review member')
        if typ=='way':wanted.update(('node',n) for n in objects[typ,ident]['nodes'])
    if wanted!=set(objects):raise ValueError('Extraneous/missing review dependency')
    for e in objects.values():
        positive_id(e['id']);positive_id(e['version'])
        if timestamp(e['timestamp'])>timestamp(m['source_snapshot_at']):raise ValueError('Future review object')
        if e['type']=='node':coordinate(e['lon'],e['lat'])
    return objects,m
