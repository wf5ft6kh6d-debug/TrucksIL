"""Closed research envelope: interpretation never constitutes permission to navigate."""
import hashlib
import json
import datetime
import re
from pathlib import Path

VERSION = 'stage5.research.v1'
KINDS = ('bridge', 'barrier', 'transport_rule', 'conditional', 'turn', 'scenario')

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
    path = Path(__file__).resolve().parents[2] / 'data/stage5/research.schema.json'
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
