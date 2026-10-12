"""Stage 7 evidence registry. Validation is not proof of a road fact."""
import datetime
import json
from pathlib import Path
from scripts.stage6.contract import canonical, sha256

VERSION = 'stage7.restriction.v1'
SOURCE_REQUIRED = ('source_id','url','locator','checked_at','document_date','rights','source_status')

def validate_source(source):
    if not isinstance(source,dict) or any(k not in source for k in SOURCE_REQUIRED):
        raise ValueError('Incomplete source metadata')
    for key in ('source_id','url','locator','checked_at','rights','source_status'):
        if not isinstance(source[key],str) or not source[key].strip():
            raise ValueError('Source metadata must be nonempty strings: '+key)
    if not source['url'].startswith(('https://','http://')):
        raise ValueError('Exact source URL required')
    datetime.date.fromisoformat(source['checked_at'])
    if source['document_date'] is not None:
        datetime.date.fromisoformat(source['document_date'])
    canonical(source)
    return source

def validate_record(row, sources=None):
    from jsonschema import Draft202012Validator, FormatChecker
    schema=json.loads((Path(__file__).resolve().parents[2]/'data/stage7/restriction.schema.json').read_text())
    Draft202012Validator(schema,format_checker=FormatChecker()).validate(row)
    if row['interpretation_status'] in ('UNKNOWN','UNSUPPORTED','CONFLICT') and not row['unknown_reasons']:
        raise ValueError('Uncertainty requires a reason')
    if row['evidence_status']=='UNKNOWN' and not row['unknown_reasons']:
        raise ValueError('Unknown evidence requires a reason')
    if sources is not None and any(s not in sources for s in row['sources']):
        raise ValueError('Unregistered evidence source')
    if row['evidence_status']=='VERIFIED':
        review=row['independent_review']
        required=('reviewer','reviewed_at','criteria','evidence_ids','decision')
        if not isinstance(review,dict) or any(not review.get(k) for k in required):
            raise ValueError('VERIFIED requires documented independent review')
        if review['decision']!='PASS' or row['unknown_reasons'] or row['interpretation_status']!='SUPPORTED':
            raise ValueError('Unresolved record cannot be VERIFIED')
        if not set(review['evidence_ids']).issubset(row['sources']):
            raise ValueError('Review cites unknown evidence')
        datetime.date.fromisoformat(review['reviewed_at'])
    validity=row['validity']
    for key in ('effective_from','effective_to'):
        if validity[key] is not None:datetime.date.fromisoformat(validity[key])
    if validity['effective_from'] and validity['effective_to'] and validity['effective_from']>validity['effective_to']:
        raise ValueError('Reversed validity interval')
    geometry=row['geometry']
    if geometry is not None:
        points=[geometry['coordinates']] if geometry['type']=='Point' else geometry['coordinates']
        if not points or (geometry['type']=='LineString' and len(points)<2):raise ValueError('Empty geometry')
        for p in points:
            if len(p)!=2 or any(type(v) not in (float,int) for v in p) or not(-180<=p[0]<=180 and -90<=p[1]<=90):raise ValueError('WGS84 required')
    canonical(row)
    return row
