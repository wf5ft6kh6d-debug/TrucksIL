"""Private stage-6 claim gap review; never promotes testimony or copies it publicly."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.stage6.claims import validate_registry


def build_gaps(registry, reviews, sources, checked_at):
    """Require one human review for every original ID, retain immutable provenance.

    Empty source_ids is a documented failed search, never evidence of free access.
    Reviews cannot override any source fields or assign VERIFIED.
    """
    validate_registry(registry)
    date.fromisoformat(checked_at)
    ids = {r['claim_id'] for r in registry['claims']}
    if set(reviews) != ids:
        raise ValueError('exactly one review per original claim required')
    source_ids = [r['source_id'] for r in sources]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError('duplicate source ID')
    rows = []
    for claim in registry['claims']:
        review = reviews[claim['claim_id']]
        if set(review) != {'source_ids', 'assessment', 'reason'}:
            raise ValueError('closed review fields; no status or value overrides')
        if not isinstance(review['source_ids'], list) or not set(review['source_ids']) <= set(source_ids):
            raise ValueError('unknown source ID')
        if review['assessment'] not in ('SOURCE_BLOCKED', 'NO_CURRENT_PRIMARY_FOUND', 'SCOPE_UNRESOLVED') or not review['reason']:
            raise ValueError('explicit unresolved assessment required')
        rows.append({'claim_id':claim['claim_id'], 'original_claim':deepcopy(claim),
                     'evidence_status':claim['status'], 'interpretation_status':'UNKNOWN',
                     'missing_original_fields':deepcopy(claim['missing_fields']),
                     'review':deepcopy(review), 'checked_at':checked_at,
                     'current_official_rule_confirmed':False, 'navigation_eligible':False})
    return {'schema_version':'stage7.private_temporal_gaps.v1', 'source':deepcopy(registry['source']),
            'original_text':registry['original_text'], 'records':rows, 'public_export_allowed':False}


def public_summary(gaps):
    """Allowlist aggregate export: no private IDs, source values, text, URLs or hashes."""
    if gaps.get('public_export_allowed') is not False:
        raise ValueError('private provenance flag required')
    for row in gaps['records']:
        if row['evidence_status'] not in ('QUARANTINE','UNKNOWN') or row['current_official_rule_confirmed'] is not False or row['navigation_eligible'] is not False:
            raise ValueError('unverified evidence escalation')
    statuses = Counter(r['evidence_status'] for r in gaps['records'])
    return {'claim_count':len(gaps['records']), 'status_counts':{'VERIFIED':0,'QUARANTINE':statuses['QUARANTINE'],'UNKNOWN':statuses['UNKNOWN']},
            'interpretation_UNKNOWN':len(gaps['records']), 'current_official_validity':'BLOCKED',
            'missing_field_counts':dict(sorted(Counter(k for r in gaps['records'] for k in r['missing_original_fields']).items())),
            'navigation_eligible':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('registry');parser.add_argument('reviews');parser.add_argument('sources');parser.add_argument('output')
    parser.add_argument('--checked-at', required=True)
    args=parser.parse_args()
    inputs=[Path(p) for p in (args.registry,args.reviews,args.sources)]
    output=Path(args.output)
    if output.resolve() in {p.resolve() for p in inputs}:
        raise ValueError('output must not overwrite an input')
    data=[p.read_bytes() for p in inputs]
    gaps=build_gaps(json.loads(data[0]),json.loads(data[1]),json.loads(data[2])['sources'],args.checked_at)
    gaps['input_sha256']={p.name:hashlib.sha256(b).hexdigest() for p,b in zip(inputs,data)}
    output.write_text(json.dumps(gaps,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(public_summary(gaps),sort_keys=True))

if __name__=='__main__':
    main()
