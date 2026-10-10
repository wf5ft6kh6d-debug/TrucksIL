"""Offline evidence crosswalk. OSM observations never promote official verification."""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from osm_pilot import load_snapshot
from topology_audit import relation

def build():
 raw,m=load_snapshot('data/stage3/osm-haifa-20261010')
 topo_path=Path('data/stage3/topology-audit.json');topo=json.loads(topo_path.read_text())
 assert topo['source_sha256']==m['sha256']
 ways={e['id']:e for e in raw['elements'] if e['type']=='way'}
 nodes={e['id']:e for e in raw['elements'] if e['type']=='node'}
 sources=json.loads(Path('data/stage3/infrastructure-sources.json').read_text())
 def way_info(i):
  w=ways[i]
  return {'way':i,'version':w['version'],'osm_timestamp':w['timestamp'],'osm_url':f'https://www.openstreetmap.org/way/{i}/history','nodes':[{'id':n,'coordinates_wgs84':[nodes[n]['lon'],nodes[n]['lat']]} for n in w['nodes']], 'tags':w['tags'],'physical_function':'unknown','osm_function':w['tags'].get('highway'),'legal_vehicle_access':'unknown'}
 crossings=[]
 for row in topo['infrastructure_contacts']:
  if row['shared_nodes']:continue
  a,b=row['ways'];wa,wb=ways[a],ways[b];support=[]
  for an,bn in zip(wa['nodes'],wa['nodes'][1:]):
   for cn,dn in zip(wb['nodes'],wb['nodes'][1:]):
    coords=lambda ids:[[nodes[n]['lon'],nodes[n]['lat']] for n in ids]
    if relation(coords([an,bn]),coords([cn,dn]))=='crosses':support.append({'way_a_nodes':[an,bn],'way_b_nodes':[cn,dn]})
  assert len(support)==1,(a,b,support)
  crossings.append({'id':row['id'],'ways':[way_info(a),way_info(b)],'supporting_segments':support,'coordinates_wgs84':row['coordinates_wgs84']['coordinates'],'geometry_relation':'interior_crossing','de9im':row['matrix'],'shared_node_ids':[],'crossing_osm_node_id':None,'status':'UNKNOWN','navigation_status':'QUARANTINE','physical_connection':'unknown','official_plan':None,'current_level_evidence':None,'candidate_source_ids':['HAIFA-BRIDGE-AUDIT-2016','HAIFA-GIS-35'] if 1053293268 in (a,b) else ['HAIFA-GIS-35','HAIFA-TRAFFIC'],'candidate_match':'Historical bridge description/location only; exact/current asset match unverified' if 1053293268 in (a,b) else 'No site-specific official drawing obtained'})
 tunnels=[]
 for row in topo['infrastructure']:
  if row['tags'].get('tunnel') not in ('yes','building_passage'):continue
  endpoints=[]
  for e in row['endpoints']:
   endpoints.append({'osm_node':e['node'],'osm_way_endpoint_coordinates_wgs84':e['coordinates'],'scope_status':'IN_SCOPE' if e['inside_pilot'] else 'OUT_OF_SCOPE','physical_portal_coordinates_wgs84':None,'status':'UNKNOWN','physical_portal_confirmed':False,'adjacent_osm_ways':e['incident_ways']})
  tunnels.append({'id':f"TUNNEL-{row['way']}",'way':way_info(row['way']),'endpoints':endpoints,'osm_geometry_continuous':row['is_valid'] and row['is_simple'],'physical_connection':'unknown','official_plan':None,'permitted_transport':'unknown','status':'UNKNOWN','navigation_status':'QUARANTINE','source_ids':['HAIFA-GIS-35','HAIFA-TRAFFIC'],'official_currentness':'unknown'})
 parameters={key:{'status':'UNKNOWN','value':None,'unit':None,'expected_unit_if_numeric':unit,'official_source':None,'document_number':None,'effective_from':None,'effective_to':None,'geographic_scope':'OSM way 731754156 is a research locator, not an official extent','truck_applicability':'unknown','license':'unknown','independent_evidence':None} for key,unit in [('maxheight','m'),('maxwidth','m'),('maxweight','t'),('maxaxleload','t'),('maxlength','m'),('hgv_prohibition',None),('hazmat',None),('direction',None),('time_restrictions',None),('special_permits',None)]}
 assert len(crossings)==8 and len(tunnels)==3
 return {'checkpoint':'4fa8498bd5debe2e89d3a5ab6a791e842696a82c','checked_at':sources['checked_at'],'bbox_wgs84':m['bbox_wgs84'],'provenance':{'raw_sha256':m['sha256'],'source_snapshot_at':m['source_snapshot_at'],'retrieved_at':m['retrieved_at'],'source_url':m['source_url'],'license':m['license'],'topology_audit_sha256':hashlib.sha256(topo_path.read_bytes()).hexdigest(),'official_sources_register':'data/stage3/infrastructure-sources.json'},'crossings':crossings,'tunnels':tunnels,'natanzon_parameters':parameters,'mailbox_review':{'checked_at':sources['checked_at'],'queries':['from:Rasha@haifa.muni.il received>=2026-10-10','from:haifa.muni.il received>=2026-10-10','TrucksIL received>=2026-10-10','TIL-HAIFA-001 received>=2026-10-10'],'status':'awaiting_response','municipal_replies_found':0,'outgoing_and_owner_copy_observed':True,'receipt_confirmed':False,'registration_number':None,'private_message_ids_and_content_published':False,'limitation':'No matching municipal response found at check time; not a guarantee against indexing delays or an unrelated subject/sender'},'summary':{'crossings_reviewed':8,'tunnels_reviewed':3,'current_levels_verified':0,'physical_portals_verified':0,'truck_restrictions_verified':0,'official_documents_imported':0,'graph_changed':False}}

if __name__=='__main__':
 r=build();out=Path(sys.argv[1]);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r['summary']))
