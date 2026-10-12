"""Private verbatim claim registry. Does not infer a routing rule or verify road law."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path

FIELDS = ('road','section','direction','vehicle_type','mass','times','days','exceptions','valid_from','valid_to','hazmat_class')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def extract(text, span):
    if not isinstance(span, list) or len(span) != 2 or any(type(x) is not int for x in span):
        raise ValueError('span must be two integer Unicode codepoint offsets')
    start, end = span
    if not 0 <= start < end <= len(text):
        raise ValueError('span out of bounds or empty')
    return text[start:end]


def build_registry(text, specifications, source):
    """Manual atomic claim spans; field values are copied verbatim, never inferred.

    All spans use Unicode codepoint [start,end) offsets in the original full text.
    Multiple claims may share source spans when a sentence names several roads.
    Spec field_spans only identify actual text; absent fields stay null.
    """
    if not isinstance(text, str) or not text:
        raise ValueError('original text required')
    source = deepcopy(source)
    for key in ('source_id', 'locator', 'original_date', 'received_date', 'testimony'):
        if key not in source:
            raise ValueError('missing source '+key)
    date.fromisoformat(source['original_date']); date.fromisoformat(source['received_date'])
    if not source['source_id'] or not source['locator'] or not isinstance(source['testimony'], dict):
        raise ValueError('incomplete provenance')
    source.update(source_type='user_testimony', sha256=digest(text), size_bytes=len(text.encode('utf-8')),
                  independent_official_evidence=False, publication_authorized=False)
    records = []
    for spec in specifications:
        raw = extract(text, spec['span'])
        fields = {key: None for key in FIELDS}
        if set(spec.get('field_spans', {})) - set(FIELDS):
            raise ValueError('unknown field name')
        for key, spans in spec.get('field_spans', {}).items():
            if not spans:
                raise ValueError('use null by omitting absent field')
            values = []
            for span in spans:
                value = extract(text, span)
                if not spec['span'][0] <= span[0] < span[1] <= spec['span'][1]:
                    raise ValueError('field evidence outside claim; no inherited assumptions')
                values.append({'text': value, 'span': span})
            fields[key] = values
        records.append({'claim_id': spec['claim_id'], 'span': spec['span'], 'raw_text': raw,
                        'source': source, 'fields': fields, 'status': 'QUARANTINE',
                        'navigation_eligible': False, 'independent_official_verification': 'BLOCKED',
                        'evidence': deepcopy(spec.get('evidence', [])),
                        'missing_fields': [k for k in FIELDS if fields[k] is None]})
    result = {'schema_version':'stage6.private_claims.v1','original_text':text,'source':source,'claims':records,
              'navigation_eligible':False,'public_export_allowed':False}
    validate_registry(result)
    return result


def validate_registry(registry):
    text = registry['original_text']; source = registry['source']
    if source['sha256'] != digest(text) or source['size_bytes'] != len(text.encode('utf-8')):
        raise ValueError('original integrity mismatch')
    if registry.get('navigation_eligible') is not False or registry.get('public_export_allowed') is not False:
        raise ValueError('private research cannot become navigation/public source')
    if source.get('source_type') != 'user_testimony' or source.get('independent_official_evidence') is not False or source.get('publication_authorized') is not False:
        raise ValueError('testimony evidence escalation')
    ids = set()
    for row in registry['claims']:
        if not row['claim_id'] or row['claim_id'] in ids:
            raise ValueError('duplicate or empty claim id')
        ids.add(row['claim_id'])
        if row['raw_text'] != extract(text,row['span']) or row['source'] != source:
            raise ValueError('claim source mismatch')
        if row['status'] not in ('QUARANTINE','UNKNOWN') or row['navigation_eligible'] is not False:
            raise ValueError('unverified testimony promotion')
        if row['independent_official_verification'] != 'BLOCKED':
            raise ValueError('verification requires separate independently audited process')
        if set(row['fields']) != set(FIELDS):
            raise ValueError('closed field inventory required')
        for values in row['fields'].values():
            if values is not None:
                if not isinstance(values,list) or not values: raise ValueError('invalid field values')
                for item in values:
                    if item['text'] != extract(text,item['span']) or not row['span'][0] <= item['span'][0] < item['span'][1] <= row['span'][1]:
                        raise ValueError('field source mismatch')
        if row['missing_fields'] != [k for k in FIELDS if row['fields'][k] is None]:
            raise ValueError('missing fields mismatch')
        for ev in row['evidence']:
            for key in ('url','authority','document_date','checked_at','locator','checked_scope','limitations','assessment'):
                if key not in ev: raise ValueError('incomplete independent evidence metadata')
            if not ev['url'].startswith('https://') or not ev['locator'] or not ev['limitations']:
                raise ValueError('evidence locator and limitations required')
            date.fromisoformat(ev['checked_at'])
            if ev['assessment'] not in ('HISTORICAL_ONLY','PARTIAL_SUPPORT','CONFLICTING_SCOPE','FETCH_BLOCKED','NO_MATCH'):
                raise ValueError('unsupported evidence assessment')
    return True


def public_summary(registry):
    """Closed aggregate output: no excerpts, message locator, hashes or field values."""
    validate_registry(registry)
    statuses=Counter(r['status'] for r in registry['claims'])
    missing=Counter(k for r in registry['claims'] for k in r['missing_fields'])
    evidence=Counter(e['assessment'] for r in registry['claims'] for e in r['evidence'])
    return {'schema_version':'stage6.claim_summary.v1','claim_count':len(registry['claims']),
            'status_counts':{'VERIFIED':0,'QUARANTINE':statuses['QUARANTINE'],'UNKNOWN':statuses['UNKNOWN']},
            'missing_field_counts':dict(sorted(missing.items())), 'evidence_assessment_counts':dict(sorted(evidence.items())),
            'official_current_validity':'BLOCKED','navigation_eligible':False,'private_original_excluded':True}


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('registry');p.add_argument('--summary',action='store_true');a=p.parse_args()
    r=json.loads(Path(a.registry).read_text());validate_registry(r)
    print(json.dumps(public_summary(r) if a.summary else {'validation':'PASS'},ensure_ascii=False,sort_keys=True,indent=2))
