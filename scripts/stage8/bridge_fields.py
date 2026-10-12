"""Private field-preserving appendix; consumes accepted JSON, never XLSX."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from scripts.stage7.bridge_review import assess


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def append_fields(records, stage6, stage7):
    expected = assess(records, stage6)
    if stage7 != expected:
        raise ValueError('Stage 7 continuation differs from accepted lineage')
    by_id = {r['record_id']: r for r in records}
    result = []
    for gap in stage7:
        r = by_id[gap['source_record_id']]
        result.append({
            'record_id': 'stage8-fields:' + r['record_id'],
            'source_record_id': r['record_id'], 'stage7_record_id': gap['record_id'],
            'historical_record': copy.deepcopy(r),
            'known_field_scope': 'HISTORICAL_OBSERVATIONS_NOT_CURRENT_ROAD_FACTS',
            'current_evidence': copy.deepcopy(gap['current_evidence']),
            'geometry': copy.deepcopy(r.get('geometry')),
            'direction': r.get('direction', 'UNKNOWN'),
            'lane': r.get('lane', 'UNKNOWN'),
            'measurement_date': r.get('measurement_date'),
            'projection_origins': {key: ('ACCEPTED_TOP_LEVEL' if key in r else
                'NO_TOP_LEVEL_FIELD_NO_DERIVATION_ATTEMPTED')
                for key in ('geometry', 'direction', 'lane', 'measurement_date')},
            'evidence_status': 'QUARANTINE', 'interpretation_status': 'UNKNOWN',
            'currentness_status': 'UNKNOWN', 'rights_status': 'PRIVATE',
            'navigation_eligible': False, 'operational_change': False,
            'external_row_check': 'NOT_RUN',
            'unknown_reasons': copy.deepcopy(gap['unknown_reasons']),
            'priority': gap['priority'], 'priority_reason': gap['priority_reason'],
            'next_step': 'REQUEST_EXISTING_DICTIONARY_CROSSWALK_DATED_SIGN_OR_SURVEY_RECORD',
            'measurement_needed': 'UNKNOWN_DOCUMENT_REVIEW_FIRST',
            'mass_threshold_for_unknown_height': None,
        })
    return result


def process(accepted_dir, stage6_dir, stage7_dir, output_dir):
    a, b, c, out = map(Path, (accepted_dir, stage6_dir, stage7_dir, output_dir))
    paths = [a/'records.jsonl', a/'manifest.json', a/'summary.json',
             b/'bridge-evidence-gaps.jsonl', b/'manifest.json', b/'summary.json', b/'source-research.json',
             c/'bridge-evidence-gaps.jsonl', c/'manifest.json', c/'summary.json', c/'source-research.json']
    if any(out.resolve() == p.parent.resolve() for p in paths):
        raise ValueError('private output must not overwrite prior stage')
    blobs = [p.read_bytes() for p in paths]
    parsed = [([json.loads(line) for line in blob.decode().splitlines() if line.strip()]
               if p.suffix == '.jsonl' else json.loads(blob)) for p, blob in zip(paths, blobs)]
    rows, original, summary, gaps6, manifest6, summary6, _, gaps7, manifest7, summary7, _ = parsed
    for i, p in enumerate(paths[:3]):
        if manifest6['input_hashes'][p.name] != sha(blobs[i]):
            raise ValueError('Stage 6 input hash mismatch')
    saved = {item['role']: item for item in manifest7['input_files']}
    for i, p in enumerate(paths[:7]):
        entry = saved[('stage5' if i < 3 else 'stage6') + ':' + p.name]
        if entry['sha256'] != sha(blobs[i]) or entry['bytes'] != len(blobs[i]):
            raise ValueError('Stage 7 input integrity mismatch')
    for i in (7, 9):
        if manifest7['outputs'][paths[i].name] != sha(blobs[i]):
            raise ValueError('Stage 7 output integrity mismatch')
    if any(n != len(rows) for n in (summary['record_count'], summary6['records'], summary7['historical_records'])):
        raise ValueError('historical count mismatch')
    for r in rows:
        s = r['source']
        if s['sha256'] != original['sha256'] or r['record_id'] != f"xlsx:{s['sha256']}:{s['member']}:{s['row']}":
            raise ValueError('original row ID mismatch')
    result = append_fields(rows, gaps6, gaps7)
    summary_out = {'historical_records': len(result), 'historical_rows_reimported': 0,
                   'historical_rows_externally_rechecked': 0, 'new_objects': 0,
                   'evidence_status_counts': {'VERIFIED': 0, 'QUARANTINE': len(result), 'UNKNOWN': 0},
                   'interpretation_status_counts': {'UNKNOWN': len(result)},
                   'historical_fields_preserved_exactly': all(x['historical_record'] == r for x, r in
                       ((x, next(r for r in rows if r['record_id'] == x['source_record_id'])) for x in result)),
                   'navigation_eligible': 0, 'priority_counts': summary6['priority_counts']}
    files = {'bridge-known-fields.jsonl': ''.join(json.dumps(r, sort_keys=True, ensure_ascii=False) + '\n' for r in result),
             'summary.json': json.dumps(summary_out, sort_keys=True, indent=2) + '\n'}
    out.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (out/name).write_text(body, encoding='utf-8')
    manifest = {'inputs': [{'role': ('stage5' if i < 3 else 'stage6' if i < 7 else 'stage7') + ':' + p.name,
                           'sha256': sha(blob), 'bytes': len(blob), 'availability': 'READ_AND_VERIFIED'}
                          for i, (p, blob) in enumerate(zip(paths, blobs))],
                'outputs': {name: sha(body.encode()) for name, body in files.items()},
                'no_xlsx_reimport': True, 'private_only': True}
    (out/'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    if any(p.read_bytes() != blob for p, blob in zip(paths, blobs)):
        raise RuntimeError('input changed')
    return summary_out


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('accepted-dir', 'stage6-dir', 'stage7-dir', 'output-dir'):
        p.add_argument('--' + name, required=True)
    args = p.parse_args()
    print(json.dumps(process(args.accepted_dir, args.stage6_dir, args.stage7_dir, args.output_dir), sort_keys=True))
