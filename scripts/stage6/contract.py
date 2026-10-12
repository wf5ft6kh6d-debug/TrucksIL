"""Closed research envelope: interpretation never constitutes permission to navigate."""
import hashlib
import json
import datetime
import re
from pathlib import Path

VERSION = 'stage6.research.v1'
KINDS = ('claim', 'bridge_gap', 'route_scenario', 'turn_transition', 'national_summary')

def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def make_record(kind, record_id, source, raw, interpretation, reasons,
                status='QUARANTINE', geometry=None, synthetic=False):
    row = dict(schema_version=VERSION, record_id=record_id, kind=kind,
               source=source, raw=raw, interpretation=interpretation,
               reasons=reasons, status=status, geometry=geometry,
               synthetic=synthetic, navigation_eligible=False)
    validate_record(row)
    return row

def validator():
    from jsonschema import Draft202012Validator, FormatChecker
    path = Path(__file__).resolve().parents[2] / 'data/stage6/research.schema.json'
    return Draft202012Validator(json.loads(path.read_text()), format_checker=FormatChecker())

_VALIDATOR = None

def validate_record(row):
    global _VALIDATOR
    if _VALIDATOR is None:
        _VALIDATOR = validator()
    _VALIDATOR.validate(row)
    stamp=row['source']['retrieved_at']
    if stamp is not None:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})',stamp):
            raise ValueError('source retrieval requires timezone-aware RFC3339 timestamp')
        datetime.datetime.fromisoformat(stamp.replace('Z','+00:00'))
    geometry=row['geometry']
    if geometry is not None:
        points=[geometry['coordinates']] if geometry['type']=='Point' else geometry['coordinates']
        if not points or (geometry['type']=='LineString' and len(points)<2):
            raise ValueError('empty or short geometry')
        for point in points:
            if len(point)!=2 or any(type(x) not in (int,float) for x in point) or not (-180<=point[0]<=180 and -90<=point[1]<=90):
                raise ValueError('WGS84 coordinates required')
    canonical(row)
    return row

def compare_schema_engines():
    """Independent legacy validator vs Draft202012 on an explicitly limited corpus."""
    import copy
    import sys
    root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'src'))
    from ingest_restrictions import _schema
    schema=json.loads((root/'data/stage6/research.schema.json').read_text())
    reference=validator()
    baseline=dict(schema_version=VERSION,record_id='synthetic:comparison',kind='route_scenario',
                  source=dict(source_id='synthetic',source_type='synthetic',locator='synthetic fixture',
                              sha256=None,retrieved_at=None),raw={},interpretation={},
                  reasons=['synthetic corpus'],status='QUARANTINE',geometry=None,
                  synthetic=True,navigation_eligible=False)
    cases=[baseline]
    for key in schema['required']:
        row=copy.deepcopy(baseline);del row[key];cases.append(row)
    for key in schema['properties']['source']['required']:
        row=copy.deepcopy(baseline);del row['source'][key];cases.append(row)
    for key,values in {'status':['UNKNOWN','VERIFIED',None], 'navigation_eligible':[True,0,None],
                       'synthetic':[False,1,None], 'kind':['claim','bridge_gap','unknown'],
                       'record_id':['',None,1], 'reasons':[[],[''],None],
                       'raw':[[],None], 'schema_version':['stage5.research.v1']}.items():
        for value in values:
            row=copy.deepcopy(baseline);row[key]=value;cases.append(row)
    mismatches=[]
    for i,row in enumerate(cases):
        expected=reference.is_valid(row)
        try:_schema(row,schema);actual=True
        except ValueError:actual=False
        if actual!=expected:mismatches.append(i)
    if mismatches:
        raise ValueError('Stage6 independent schema mismatches: '+str(mismatches))
    return {'comparisons':len(cases),'mismatches':0,'scope':'limited closed-envelope corpus; not full conformance'}

if __name__=='__main__':
    print(json.dumps(compare_schema_engines(),sort_keys=True))
