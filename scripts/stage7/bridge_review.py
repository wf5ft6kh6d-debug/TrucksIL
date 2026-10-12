"""Continue private accepted bridge gaps, without XLSX import or inferred evidence."""
import argparse
import hashlib
import json
from pathlib import Path
from scripts.stage6.bridge_gaps import build_registry


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def assess(records, gaps):
    expected = build_registry(records)
    by_id = {r['source_record_id']: r for r in expected['records']}
    if len(gaps) != len(by_id) or len({r['source_record_id'] for r in gaps}) != len(gaps):
        raise ValueError('gap count or duplicate mismatch')
    result = []
    for gap in gaps:
        key = gap['source_record_id']
        if key not in by_id or gap != by_id[key]:
            raise ValueError('accepted Stage 6 gap differs from accepted Stage 5 provenance')
        result.append({
            'record_id': 'stage7-review:' + key, 'source_record_id': key,
            'stage6_gap_record_id': gap['record_id'], 'source': gap['source'],
            'evidence_status': 'QUARANTINE', 'interpretation_status': 'UNKNOWN',
            'unknown_reasons': [g['gate'] for g in gap['evidence_gaps']],
            'confirmed': ['HISTORICAL_SOURCE_ROW_LINKAGE', 'STAGE6_GAP_INTEGRITY'],
            'confirmed_scope': 'DOCUMENT_LINEAGE_ONLY_NOT_ROAD_FACT',
            'historical_observation_presence': gap['dimension_presence'],
            'current_evidence': [], 'external_row_check': 'NOT_RUN',
            'geometry': None, 'direction': 'UNKNOWN', 'lane': 'UNKNOWN',
            'unit_status': 'UNKNOWN', 'measurement_date': None,
            'historical_values_kept_in_stage5': True, 'navigation_eligible': False,
            'priority': gap['priority'], 'priority_reason': gap['priority_reason'],
            'review_order': gap['review_order'], 'priority_is_risk_score': False,
        })
    return sorted(result, key=lambda r: r['review_order'])


def process(accepted_dir, stage6_dir, output_dir):
    a, s, out = map(Path, (accepted_dir, stage6_dir, output_dir))
    paths = [a/'records.jsonl', a/'manifest.json', a/'summary.json',
             s/'bridge-evidence-gaps.jsonl', s/'manifest.json', s/'summary.json', s/'source-research.json']
    blobs = [p.read_bytes() for p in paths]
    records = [json.loads(x) for x in blobs[0].decode().splitlines() if x.strip()]
    gaps = [json.loads(x) for x in blobs[3].decode().splitlines() if x.strip()]
    original, old_summary, gap_manifest, gap_summary = [json.loads(blobs[i]) for i in (1,2,4,5)]
    research = json.loads(blobs[6])
    if not isinstance(research, dict) or not isinstance(research.get('records'), list):
        raise ValueError('Stage 6 source research shape invalid')
    if old_summary['record_count'] != len(records) or gap_summary['records'] != len(records):
        raise ValueError('summary count mismatch')
    for p,b in zip(paths[:3],blobs[:3]):
        if gap_manifest['input_hashes'][p.name] != digest(b):
            raise ValueError('Stage 6 accepted input hash mismatch')
    for row in records:
        src=row['source']
        if src['sha256'] != original['sha256'] or row['record_id'] != f"xlsx:{src['sha256']}:{src['member']}:{src['row']}":
            raise ValueError('original row identity mismatch')
    reviews=assess(records,gaps)
    summary={'historical_records':len(reviews),'historical_rows_reimported':0,
             'historical_rows_externally_rechecked':0,'verified_current_matches':0,
             'evidence_status_counts':{'VERIFIED':0,'QUARANTINE':len(reviews),'UNKNOWN':0},
             'interpretation_status_counts':{'UNKNOWN':len(reviews)},
             'priority_counts':gap_summary['priority_counts'], 'navigation_eligible':0,
             'new_objects_counted_in_separate_source_registry':True}
    files={'bridge-evidence-gaps.jsonl':''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in reviews),
           'summary.json':json.dumps(summary,sort_keys=True,indent=2)+'\n'}
    if any((out/n).resolve()==p.resolve() for n in (*files,'manifest.json') for p in paths):
        raise ValueError('output would overwrite input')
    out.mkdir(parents=True,exist_ok=True)
    for name,body in files.items(): (out/name).write_text(body,encoding='utf-8')
    manifest={'input_files':[{'role':('stage5' if i<3 else 'stage6')+':'+p.name,'sha256':digest(b),'bytes':len(b),'availability':'CONTENT_VERIFIED'} for i,(p,b) in enumerate(zip(paths,blobs))],
              'outputs':{n:digest(v.encode()) for n,v in files.items()},'no_xlsx_reimport':True}
    (out/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    if any(p.read_bytes()!=b for p,b in zip(paths,blobs)): raise RuntimeError('input changed')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accepted-dir',required=True)
    parser.add_argument('--stage6-dir',required=True)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    print(json.dumps(process(args.accepted_dir,args.stage6_dir,args.output_dir),sort_keys=True))
