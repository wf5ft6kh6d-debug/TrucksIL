"""ODbL research graph and quarantined observations, NEVER routing restrictions."""
from collections import Counter
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

from ingest_restrictions import SCHEMA, _schema, timestamp, _unique_object, _no_constant

ROAD_CLASSES = frozenset('motorway trunk primary secondary tertiary unclassified residential living_street service motorway_link trunk_link primary_link secondary_link tertiary_link road'.split())
DIMENSIONS = {'maxheight': ('max_height','m'), 'maxwidth': ('max_width','m'),
              'maxlength': ('max_length','m'), 'maxweight': ('max_gross_weight','t'),
              'maxaxleload': ('max_axle_weight','t'), 'hgv': ('truck_prohibited','boolean'),
              'hazmat': ('hazmat_restriction','boolean')}
OBSERVATION_KEYS = set(DIMENSIONS) | {'access','vehicle','motor_vehicle','oneway','restriction'}


def loads(raw):
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_no_constant)


def positive_id(value):
    if type(value) is not int or value <= 0:
        raise ValueError('OSM id/version must be positive integer')
    return value


def coordinate(lon, lat):
    g={'type':'Point','coordinates':[lon,lat]}
    _schema(g, SCHEMA['properties']['geometry'])
    if not all(type(x) in (int,float) and math.isfinite(x) for x in (lon,lat)):
        raise ValueError('Nonfinite/boolean coordinate')
    return [lon,lat]


def decode_tag(key, value):
    """Decode only exact supported forms, no expiry/scope/verified inference."""
    base, *suffix = key.split(':')
    if base not in DIMENSIONS or suffix not in ([],['forward'],['backward']):
        return None
    kind,unit=DIMENSIONS[base]
    direction={'forward':'forward','backward':'reverse'}.get(suffix[0] if suffix else '', 'unknown')
    if unit == 'boolean':
        if value != 'no': return None  # destination/yes/conditional never become permissions
        number=Decimal(1)
    else:
        # OSM default metres/metric tonnes; only these explicit units supported.
        match=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*(m|t|kg)?',value)
        if not match: return None
        number=Decimal(match[1]); supplied=match[2] or unit
        if supplied==unit: pass
        elif supplied=='kg' and unit=='t': number/=1000
        else: return None
        if not number.is_finite() or number <= 0 or not math.isfinite(float(number)): return None
    return {'restrictionType':kind,'value':str(number),'unit':unit,'direction':direction}


def load_snapshot(folder):
    folder=Path(folder); m=loads((folder/'manifest.json').read_bytes())
    raw=gzip.decompress((folder/'raw.json.gz').read_bytes())
    if len(raw)!=m['bytes'] or hashlib.sha256(raw).hexdigest()!=m['sha256']:
        raise ValueError('Raw checksum/size mismatch')
    if m['license']['decision']!='permitted' or m['license']['identifier']!='ODbL-1.0':
        raise ValueError('Source license not approved for this adapter')
    if m['license']['evidence_url']!='https://www.openstreetmap.org/copyright':
        raise ValueError('Missing OSM license evidence')
    if m['authenticated_official'] is not False or m['crs']!='EPSG:4326':
        raise ValueError('Unsupported source/CRS')
    if m['endpoint']!='https://overpass-api.de/api/interpreter':
        raise ValueError('Unreviewed provider')
    p=loads(raw)
    if 'remark' in p or not p.get('elements'): raise ValueError('Partial/error/empty snapshot')
    if p['osm3s']['timestamp_osm_base']!=m['source_snapshot_at']:
        raise ValueError('Snapshot revision mismatch')
    if timestamp(m['source_snapshot_at']) > timestamp(m['retrieved_at']):
        raise ValueError('Snapshot from future')
    return p,m


def inside(point,bbox):
    return bbox[0]<=point[0]<=bbox[2] and bbox[1]<=point[1]<=bbox[3]


def distance(a,b):
    lon1,lat1,lon2,lat2=map(math.radians,(*a,*b))
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371008.8*2*math.asin(min(1,math.sqrt(h)))


def normalize(payload, manifest):
    bbox=manifest['bbox_wgs84']; coordinate(bbox[0],bbox[1]);coordinate(bbox[2],bbox[3])
    if bbox[0]>=bbox[2] or bbox[1]>=bbox[3]: raise ValueError('Invalid bbox')
    elements={}; nodes={}; observations=[]; segments=[]; used_nodes=set()
    for e in payload['elements']:
        if e['type'] not in ('node','way','relation'): raise ValueError('Unknown element type')
        identity=(e['type'],positive_id(e['id']))
        if identity in elements: raise ValueError('Duplicate OSM element')
        positive_id(e['version'])
        if timestamp(e['timestamp'])>timestamp(manifest['source_snapshot_at']):
            raise ValueError('Element revision newer than snapshot')
        tags=e.get('tags',{})
        if not isinstance(tags,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in tags.items()):
            raise ValueError('Invalid OSM tags')
        elements[identity]=e
        if e['type']=='node': nodes[e['id']]=coordinate(e['lon'],e['lat'])
    revision=manifest['sha256']
    def nid(n): return f'osm:{revision}:node:{n}'
    excluded=Counter(); boundary_pairs=0; degenerate_pairs=0; road_ways=0
    for ident,e in sorted(elements.items()):
        tags=e.get('tags',{})
        for key,value in sorted(tags.items()):
            if key.split(':')[0] in OBSERVATION_KEYS:
                observations.append({'source_element':f"{e['type']}/{e['id']}",
                    'source_version':e['version'],'source_edit_at':e['timestamp'],
                    'key':key,'raw_value':value,'decoded':decode_tag(key,value),
                    'status':'unverified','disposition':'quarantine',
                    'observed_at':None,'valid_from':None,'valid_to':None,
                    'reason':'Community tag; field observation, current applicability and independent review absent'})
        if e['type']!='way': continue
        highway=tags.get('highway')
        if highway not in ROAD_CLASSES or tags.get('area')=='yes':
            excluded[highway or 'missing_highway']+=1;continue
        road_ways+=1
        refs=e['nodes']
        if len(refs)<2 or any(type(n) is not int or n not in nodes for n in refs):
            raise ValueError('Missing node/invalid way references')
        for i,(a,b) in enumerate(zip(refs,refs[1:])):
            if not inside(nodes[a],bbox) or not inside(nodes[b],bbox):
                boundary_pairs+=1; continue
            if a==b or nodes[a]==nodes[b]: degenerate_pairs+=1;continue
            g={'type':'LineString','coordinates':[nodes[a],nodes[b]]}
            _schema(g,SCHEMA['properties']['geometry'])
            direction={'yes':'forward','1':'forward','true':'forward','-1':'reverse',
                       'no':'both','0':'both','false':'both'}.get(tags.get('oneway'),'unknown')
            # Conditional one-way must not collapse to unconditional direction.
            if any(k.startswith('oneway:') for k in tags): direction='unknown'
            segments.append({'id':f"osm:{revision}:way:{e['id']}:v{e['version']}:{i}",
                 'from_node':nid(a),'to_node':nid(b),'geometry':g,'direction':direction,
                 'source_way':e['id'],'source_version':e['version'],'source_edit_at':e['timestamp'],
                 'source_pair_index':i,'source_revision':revision,'tags':tags,
                 'topology_status':'unverified'})
            used_nodes.update((a,b))
    graph_nodes=[{'id':nid(n),'source_node':n,'source_version':elements[('node',n)]['version'],
                 'source_edit_at':elements[('node',n)]['timestamp'],'source_revision':revision,
                 'geometry':{'type':'Point','coordinates':nodes[n]}} for n in sorted(used_nodes)]
    relations=[{k:v for k,v in e.items() if k not in ('user','uid')} for (typ,_),e in sorted(elements.items()) if typ=='relation']
    missing_members=sum((x['type'],x['ref']) not in elements for e in relations for x in e['members'])
    keys=Counter(o['key'].split(':')[0] for o in observations)
    counts=Counter(e['type'] for e in elements.values())
    measured={k:keys[k] for k in DIMENSIONS}
    digest=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    summary={'normalizer_version':'stage3-v1','raw_sha256':revision,'bbox_wgs84':bbox,
        'source_snapshot_at':manifest['source_snapshot_at'],'retrieved_at':manifest['retrieved_at'],
        'source_elements':dict(sorted(counts.items())),'eligible_road_ways':road_ways,
        'excluded_way_classes':dict(sorted(excluded.items())),'graph_nodes':len(graph_nodes),
        'graph_segments':len(segments),'boundary_pairs_excluded':boundary_pairs,
        'degenerate_pairs_excluded':degenerate_pairs,'relation_member_references_missing':missing_members,
        'restriction_tag_observations':measured,'all_access_direction_turn_observations':len(observations),
        'turn_relations_quarantined':len(relations),'verified_restrictions':0,
        'restriction_records_emitted':0,'road_length_m_spherical':round(sum(distance(*s['geometry']['coordinates']) for s in segments),3),
        'window_area_km2_spherical':round(6371008.8**2*math.radians(bbox[2]-bbox[0])*(math.sin(math.radians(bbox[3]))-math.sin(math.radians(bbox[1])))/1e6,6),
        'infrastructure_way_tags':{k:sum(k in e.get('tags',{}) for e in elements.values() if e['type']=='way') for k in ('bridge','tunnel')},
        'geometry_completeness':None,'national_coverage':None,'restriction_coverage':'unknown',
        'route_safety_certified':False,'route_suitability':'unknown',
        'normalized_sha256':digest([graph_nodes,segments,observations,relations])}
    return {'nodes':graph_nodes,'segments':segments,'observations':observations,'relations':relations,'summary':summary}
