"""Independent NetworkX checks reconstructed directly from raw nodes/ways."""
import gzip,json,sys
from pathlib import Path
import networkx as nx
r=json.loads(Path(sys.argv[1]).read_text())
p=json.loads(gzip.decompress(Path('data/stage3/osm-haifa-20261010/raw.json.gz').read_bytes()))
o={(e['type'],e['id']):e for e in p['elements']}
# Independent spelling of the existing road-class contract, no imports of audit algorithms.
classes=set('motorway trunk primary secondary tertiary unclassified residential living_street service motorway_link trunk_link primary_link secondary_link tertiary_link road'.split())
full=nx.MultiGraph();clipped=nx.MultiGraph();outside=set();filtered=set();unknown=0
bbox=[34.990,32.811,35.004,32.821]
def point(n):e=o['node',n];return e['lon'],e['lat']
def within(n):x,y=point(n);return bbox[0]<=x<=bbox[2] and bbox[1]<=y<=bbox[3]
for e in p['elements']:
 if e['type']!='way':continue
 t=e.get('tags',{});eligible=t.get('highway') in classes and t.get('area')!='yes'
 for a,b in zip(e['nodes'],e['nodes'][1:]):
  if a==b or point(a)==point(b):continue
  if not eligible:filtered.update((a,b));continue
  full.add_edge(a,b)
  if within(a) and within(b):
   clipped.add_edge(a,b)
   if 'oneway' not in t:unknown+=1
  else:
   if within(a):outside.add(a)
   if within(b):outside.add(b)
leaves={n for n,d in clipped.degree() if d==1}
s=r['topology']['summary'];findings=s['leaf_findings']
assert len(leaves&outside)==findings['bbox_cut']
assert len((leaves-outside)&filtered)==findings['filtered_class_adjacency']
assert len(leaves-outside-filtered)==findings['source_endpoint_unresolved']
assert unknown==s['unknown_direction_reasons']['missing_oneway']
cc=list(nx.connected_components(full));assert sum(bool(c&set(clipped)) for c in cc)==s['full_raw_components_touching_pilot']
for row in r['topology']['components']:
 assert set(row['nodes']) in list(nx.connected_components(clipped))
# Per-way directed adjacency, not an aggregate road graph that could choose the wrong way.
for row in r['relations']:
 rel=o['relation',row['id']];roles={k:[x for x in rel['members'] if x['role']==k] for k in ('from','via','to')}
 if not roles['from']:
  assert row['finding']=='missing_from_member';continue
 v=roles['via'][0]['ref']
 for role,field in [('from','incoming_arcs'),('to','outgoing_arcs')]:
  w=o['way',roles[role][0]['ref']];dg=nx.DiGraph();dg.add_nodes_from(w['nodes']);tag=w['tags'].get('oneway')
  for a,b in zip(w['nodes'],w['nodes'][1:]):
   if tag in ('yes','1','true','no','0','false'):dg.add_edge(a,b)
   if tag in ('-1','no','0','false'):dg.add_edge(b,a)
  arcs=dg.in_edges(v) if role=='from' else dg.out_edges(v)
  assert sorted(map(list,arcs))==sorted(row[field])
 assert not row['outgoing_arcs'] and row['finding']=='prohibited_manoeuvre_already_unreachable'
print('NetworkX independent raw-source review PASS: four relations, 100 leaves, five clipped/four context components, 575 absent oneway tags.')
