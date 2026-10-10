"""Independent NetworkX connectivity comparison, without inferring unknown directions."""
import json
import sys
from pathlib import Path
import networkx as nx

g=json.loads(Path(sys.argv[1]).read_text());a=json.loads(Path(sys.argv[2]).read_text())
u=nx.MultiGraph();d=nx.MultiDiGraph()
for n in g['nodes']:u.add_node(n['id']);d.add_node(n['id'])
for s in g['segments']:
    x,y=s['from_node'],s['to_node'];u.add_edge(x,y)
    if s['direction'] in ('forward','both'):d.add_edge(x,y)
    if s['direction'] in ('reverse','both'):d.add_edge(y,x)
wcc=sorted((sorted(c) for c in nx.connected_components(u)),key=lambda c:(-len(c),c))
strong=sorted((sorted(c) for c in nx.strongly_connected_components(d)),key=lambda c:(-len(c),c))
assert strong==a['strong_components']
scc=[len(c) for c in strong]
s=a['summary']
assert wcc==a['weak_components']
assert len(scc)==s['strong_components_explicit_directions_only'] and scc[0]==s['largest_strong_component']
assert sum(deg==1 for _,deg in u.degree())==s['degree_one_nodes']
assert d.number_of_edges()==s['explicit_direction_arcs']
print(f'NetworkX {nx.__version__}: {len(wcc)} weak / {len(scc)} strong components, degree counts and {d.number_of_edges()} explicit arcs agree. Truck permissions unverified.')
