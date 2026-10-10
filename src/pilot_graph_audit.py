"""Research-only connectivity/turn diagnostics. No inferred truck permission."""
from collections import Counter,defaultdict
import gzip,hashlib,json
from pathlib import Path
from osm_pilot import loads,coordinate,inside
from ingest_restrictions import timestamp


def components(vertices, edges, strong=False):
    adj={v:set() for v in vertices};rev={v:set() for v in vertices}
    for a,b in edges:
        adj[a].add(b);rev[b].add(a)
        if not strong:adj[b].add(a);rev[a].add(b)
    seen=set();order=[]
    for root in sorted(vertices):
        if root in seen:continue
        stack=[(root,False)]
        while stack:
            v,done=stack.pop()
            if done:order.append(v);continue
            if v in seen:continue
            seen.add(v);stack.append((v,True))
            stack.extend((w,False) for w in sorted(adj[v],reverse=True) if w not in seen)
    seen=set();groups=[]
    for root in reversed(order):
        if root in seen:continue
        group=[];stack=[root];seen.add(root)
        while stack:
            v=stack.pop();group.append(v)
            for w in rev[v]:
                if w not in seen:seen.add(w);stack.append(w)
        groups.append(sorted(group))
    return sorted(groups,key=lambda g:(-len(g),g))


def supplement(folder,base,manifest):
    p=Path(folder);m=loads((p/'manifest.json').read_bytes());raw=gzip.decompress((p/'raw.json.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest()!=m['sha256'] or len(raw)!=m['bytes']:raise ValueError('Supplement checksum mismatch')
    if m['license']['identifier']!='ODbL-1.0' or m['license']['decision']!='permitted' or m['license']['evidence_url']!='https://www.openstreetmap.org/copyright':raise ValueError('Unlicensed supplement')
    if m['source_snapshot_at']!=manifest['source_snapshot_at'] or '[date:"'+manifest['source_snapshot_at']+'"]' not in m['query']:raise ValueError('Mixed snapshot dates')
    if m['bbox_wgs84']!=manifest['bbox_wgs84'] or m['scope']!='relation context only; never added to pilot graph':raise ValueError('Scope expansion refused')
    d=loads(raw)
    if 'remark' in d:raise ValueError('Partial Overpass response')
    original={(e['type'],e['id']):e for e in base['elements']}
    missing={(x['type'],x['ref']) for r in base['elements'] if r['type']=='relation' for x in r['members'] if (x['type'],x['ref']) not in original}
    extra={(e['type'],e['id']):e for e in d['elements']}
    if len(extra)!=len(d['elements']):raise ValueError('Duplicate supplemental object')
    ways={e['id'] for e in d['elements'] if e['type']=='way'}
    if ways!={n for t,n in missing if t=='way'}:raise ValueError('Unexpected/missing dependency ways')
    wanted_nodes={n for e in d['elements'] if e['type']=='way' for n in e['nodes']}
    if set(extra)!={('way',w) for w in ways}|{('node',n) for n in wanted_nodes}:raise ValueError('Incomplete/extraneous dependency nodes')
    for ident,e in extra.items():
        if type(e['version']) is not int or e['version']<1 or timestamp(e['timestamp'])>timestamp(m['source_snapshot_at']):raise ValueError('Invalid dependency revision')
        if e['type']=='node':coordinate(e['lon'],e['lat'])
        if ident in original:
            strip=lambda x:{k:v for k,v in x.items() if k not in ('uid','user')}
            if strip(e)!=strip(original[ident]):raise ValueError('Conflicting duplicate snapshot object')
    return {**original,**extra},m


def audit(base,manifest,graph,merged):
    old={(e['type'],e['id']):e for e in base['elements']};bbox=manifest['bbox_wgs84']
    fixes=[]
    for r in base['elements']:
        if r['type']!='relation':continue
        for x in r['members']:
            ident=(x['type'],x['ref'])
            if ident in old:continue
            e=merged.get(ident)
            points=[coordinate(merged[('node',n)]['lon'],merged[('node',n)]['lat']) for n in e['nodes']] if e else []
            fixes.append({'relation_id':r['id'],'role':x['role'],'type':x['type'],'id':x['ref'],
                'resolved':e is not None,'version':e['version'] if e else None,
                'all_nodes_outside_bbox':bool(points) and all(not inside(p,bbox) for p in points),
                'cause':'outside_bbox_dependency_not_recursed' if points and all(not inside(p,bbox) for p in points) else 'incomplete_query_or_unresolved',
                'added_to_graph':False})
    vertices={n['id'] for n in graph['nodes']};edges=[(s['from_node'],s['to_node']) for s in graph['segments']]
    arcs=[];degrees=Counter();direction_counts=Counter()
    for s in graph['segments']:
        a,b=s['from_node'],s['to_node'];degrees[a]+=1;degrees[b]+=1;direction_counts[s['direction']]+=1
        if s['direction'] in ('forward','both'):arcs.append((a,b))
        if s['direction'] in ('reverse','both'):arcs.append((b,a))
    wcc=components(vertices,edges);scc=components(vertices,arcs,True)
    def nodeid(v):return 'osm:'+manifest['sha256']+':node:'+str(v)
    turns=[];groups=defaultdict(list)
    for r in sorted((e for e in base['elements'] if e['type']=='relation'),key=lambda e:e['id']):
        roles={k:[x for x in r['members'] if x['role']==k] for k in ('from','via','to')}
        missing=[x for x in r['members'] if (x['type'],x['ref']) not in merged]
        row={'id':r['id'],'version':r['version'],'tags':r['tags'],'status':'quarantine',
             'truck_applicability':'unknown','missing_members':missing}
        if missing:row['reason']='incomplete'
        elif len(r['members'])!=3 or any(len(roles[k])!=1 for k in roles) or roles['via'][0]['type']!='node' or any(roles[k][0]['type']!='way' for k in ('from','to')):
            row['reason']='unsupported_member_structure'
        elif any(k!='type' and k!='restriction' for k in r['tags']):row['reason']='qualified_or_conditional_semantics'
        elif r['tags'].get('restriction') not in ('no_left_turn','no_right_turn','no_straight_on','no_u_turn','only_left_turn','only_right_turn','only_straight_on','only_u_turn'):
            row['reason']='unsupported_turn_value'
        else:
            via=roles['via'][0]['ref'];fw=roles['from'][0]['ref'];tw=roles['to'][0]['ref'];v=nodeid(via)
            row.update({'via':via,'from_way':fw,'to_way':tw})
            if any(via not in merged[('way',w)]['nodes'] for w in (fw,tw)):row['reason']='disconnected_member_geometry'
            else:
                incoming=[s for s in graph['segments'] if s['source_way']==fw and (s['to_node']==v or s['from_node']==v)]
                outgoing=[s for s in graph['segments'] if s['source_way']==tw and (s['from_node']==v or s['to_node']==v)]
                allowed_in=[s for s in incoming if (s['to_node']==v and s['direction'] in ('forward','both')) or (s['from_node']==v and s['direction'] in ('reverse','both'))]
                allowed_out=[s for s in outgoing if (s['from_node']==v and s['direction'] in ('forward','both')) or (s['to_node']==v and s['direction'] in ('reverse','both'))]
                if not incoming or not outgoing:row['reason']='outside_clipped_graph'
                elif any(s['direction']=='unknown' for s in incoming+outgoing):row['reason']='unknown_direction'
                elif not allowed_in or not allowed_out:row['reason']='direction_conflict_candidate'
                else:row['reason']='structurally_resolved_unverified'
                row['incoming_candidates']=[s['id'] for s in allowed_in];row['outgoing_candidates']=[s['id'] for s in allowed_out]
                groups[(fw,via)].append(row)
        turns.append(row)
    conflicts=[]
    for key,rows in sorted(groups.items()):
        only={r['to_way'] for r in rows if r['tags']['restriction'].startswith('only_')}
        banned={r['to_way'] for r in rows if r['tags']['restriction'].startswith('no_')}
        if len(only)>1 or only & banned:conflicts.append({'from_way':key[0],'via':key[1],'relations':[r['id'] for r in rows],'reason':'contradictory_targets_candidate'})
    summary={'missing_references_before':len(fixes),'resolved_references':sum(f['resolved'] for f in fixes),
      'unique_dependency_ways':len({f['id'] for f in fixes}),'missing_references_after':sum(not f['resolved'] for f in fixes),
      'graph_nodes':len(vertices),'graph_segments':len(edges),'weak_components':len(wcc),'weak_component_sizes':[len(g) for g in wcc],
      'degree_one_nodes':sum(v==1 for v in degrees.values()),'explicit_direction_arcs':len(arcs),'direction_counts':dict(sorted(direction_counts.items())),
      'strong_components_explicit_directions_only':len(scc),'largest_strong_component':len(scc[0]) if scc else 0,
      'turn_reasons':dict(sorted(Counter(r['reason'] for r in turns).items())),
      'turn_conflict_candidates':len(conflicts),'verified_restrictions':0,'route_safety_certified':False,
      'scope_bbox':bbox,'graph_changed':False}
    return {'summary':summary,'missing_reference_report':fixes,'turns':turns,'conflicts':conflicts,'weak_components':wcc,'strong_components':scc}
