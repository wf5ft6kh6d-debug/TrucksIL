"""Exact planar segment diagnostics. Findings never change graph connectivity."""
from decimal import Decimal

SCALE=10**9

def ip(p):
    q=[Decimal(str(v))*SCALE for v in p]
    if any(v != v.to_integral_value() for v in q):
        raise ValueError('Unsupported coordinate precision')
    return tuple(map(int,q))

def orient(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])

def on(a,b,p):
    return orient(a,b,p)==0 and all(min(a[k],b[k])<=p[k]<=max(a[k],b[k]) for k in (0,1))

def relation(coords1, coords2):
    a,b=map(ip,coords1);c,d=map(ip,coords2)
    if a==b or c==d: raise ValueError('Zero length segment')
    if {a,b}=={c,d}: return 'equals'
    if orient(a,b,c)==orient(a,b,d)==0:
        axis=0 if a[0]!=b[0] else 1
        lo=max(min(a[axis],b[axis]),min(c[axis],d[axis]));hi=min(max(a[axis],b[axis]),max(c[axis],d[axis]))
        if hi>lo:
            return 'contained_overlap' if (on(a,b,c) and on(a,b,d)) or (on(c,d,a) and on(c,d,b)) else 'overlaps'
        if hi==lo:return 'endpoint_touch'
        return 'disjoint'
    if orient(a,b,c)*orient(a,b,d)<0 and orient(c,d,a)*orient(c,d,b)<0:return 'crosses'
    hits=[p for p in (a,b) if on(c,d,p)]+[p for p in (c,d) if on(a,b,p)]
    if not hits:return 'disjoint'
    return 'endpoint_touch' if set((a,b))&set((c,d)) else 'interior_touch'

def classify(kind, shared_nodes, tags1, tags2):
    layers=[tags1.get('layer'),tags2.get('layer')]
    different=None not in layers and layers[0]!=layers[1]
    if shared_nodes and different:
        return 'UNKNOWN','shared_node_different_explicit_layers; possible transition, not proven defect'
    if different:
        return 'UNKNOWN','explicit_different_layers; physical separation unverified'
    if kind=='endpoint_touch' and shared_nodes:
        return 'VERIFIED','shared OSM endpoint; geometry/identity only, truck access unverified'
    if kind in ('equals','overlaps','contained_overlap'):
        return 'SUSPECTED','coincident geometry; duplicate versus shared alignment needs evidence'
    return 'QUARANTINE','geometric contact without proven transport connection'

def endpoint_evidence(way, nodes, ways):
    result=[]
    for n in (way['nodes'][0],way['nodes'][-1]):
        node=nodes.get(n)
        result.append({'node':n,'coordinates':None if node is None else [node['lon'],node['lat']],
          'incident_ways':[{'way':w['id'],'version':w['version'],'tags':w.get('tags',{})} for w in ways if w['id']!=way['id'] and n in w['nodes']],
          'status':'UNKNOWN','physical_portal_confirmed':False,'missing_node':node is None})
    return result
