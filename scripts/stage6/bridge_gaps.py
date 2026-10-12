"""Private evidence-gap queue over accepted Stage 5 records; never reimport XLSX.

Priority is review order, not a statement of danger, road permission or clearance.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

DIMENSIONS = ('minimum_vertical_clearance', 'free_vertical_clearance', 'posted_height_limit', 'pier_height')
REQUIRED = ('OFFICIAL_SOURCE_IDENTITY', 'REUSE_RIGHTS', 'FIELD_UNIT_DICTIONARY',
            'MEASUREMENT_DATE_AND_METHOD', 'CURRENT_OFFICIAL_EVIDENCE',
            'STRUCTURE_IDENTITY_AND_ROAD_ROLE', 'UNDERPASS_GEOMETRY',
            'DIRECTION_AND_LANE', 'SIGN_VS_PHYSICAL_CLEARANCE', 'INDEPENDENT_REVIEW')


def build_gap(record):
    """Accept only still-quarantined source records; no evidence gates auto-close."""
    if record.get('status') != 'QUARANTINE' or record.get('navigation_eligible') is not False:
        raise ValueError('expected quarantined, navigation-ineligible Stage 5 record')
    source = record['source']
    if not isinstance(record.get('record_id'), str) or not record['record_id']:
        raise ValueError('record ID missing')
    if not isinstance(source.get('row'), int) or isinstance(source['row'], bool) or source['row'] < 1:
        raise ValueError('source row invalid')
    if set(record['dimensions']) != set(DIMENSIONS):
        raise ValueError('unexpected dimension fields')
    present = {key: record['dimensions'][key].get('raw') is not None for key in DIMENSIONS}
    clearance = present['minimum_vertical_clearance'] or present['free_vertical_clearance']
    sign = present['posted_height_limit']
    # Paired claims first: establish identity, units and semantics before comparison.
    if clearance and sign:
        priority, group = 1, 'SIGN_AND_CLEARANCE_REQUIRE_RECONCILIATION'
    elif sign:
        priority, group = 2, 'SIGN_WITHOUT_PHYSICAL_CLEARANCE'
    elif clearance:
        priority, group = 3, 'CLEARANCE_WITHOUT_POSTED_LIMIT'
    elif present['pier_height']:
        priority, group = 4, 'PIER_ONLY_NOT_CLEARANCE'
    else:
        priority, group = 5, 'NO_HEIGHT_OBSERVATIONS'
    gaps = list(REQUIRED)
    if not clearance:
        gaps.append('PHYSICAL_CLEARANCE_VALUE_MISSING')
    if not sign:
        gaps.append('POSTED_LIMIT_VALUE_MISSING')
    if any(present[k] and record['dimensions'][k].get('parsed_decimal') is None for k in DIMENSIONS):
        gaps.append('UNPARSED_MEASUREMENT')
    return {
        'record_id': 'bridge-gap:'+record['record_id'], 'source_record_id': record['record_id'],
        'source': {k: source[k] for k in ('sha256', 'sheet', 'member', 'row')},
        'status': 'QUARANTINE', 'navigation_eligible': False, 'geometry': None,
        'interpretation': 'UNKNOWN', 'direction': 'UNKNOWN',
        'priority': priority, 'priority_reason': group, 'priority_is_risk_score': False,
        'dimension_presence': present,
        'evidence_gaps': [{'gate': key, 'status': 'UNKNOWN', 'evidence': []} for key in gaps],
        'external_row_check': {'status': 'NOT_RUN', 'official_objects_checked': 0},
        'no_numeric_comparison_until_units_and_semantics_confirmed': True,
    }


def build_registry(records):
    output = []
    seen = set()
    for record in records:
        gap = build_gap(record)
        if gap['source_record_id'] in seen:
            raise ValueError('duplicate source record ID')
        seen.add(gap['source_record_id'])
        output.append(gap)
    output.sort(key=lambda r: (r['priority'], r['source']['sha256'], r['source']['member'], r['source']['row'], r['record_id']))
    for i, row in enumerate(output, 1):
        row['review_order'] = i
    summary = {
        'records': len(output), 'status_counts': {'QUARANTINE': len(output), 'VERIFIED': 0, 'UNKNOWN': 0},
        'interpretation_counts': {'UNKNOWN': len(output)}, 'externally_checked_rows': 0,
        'official_current_row_matches': 0, 'navigation_eligible': 0,
        'priority_counts': dict(sorted(Counter(r['priority_reason'] for r in output).items())),
        'gap_counts': dict(sorted(Counter(g['gate'] for r in output for g in r['evidence_gaps']).items())),
    }
    return {'records': output, 'summary': summary}


def process_accepted(records_path, manifest_path, summary_path, output_dir):
    paths = [Path(p) for p in (records_path, manifest_path, summary_path)]
    blobs = [p.read_bytes() for p in paths]
    manifest, previous = json.loads(blobs[1]), json.loads(blobs[2])
    rows = [json.loads(line) for line in blobs[0].decode().splitlines() if line.strip()]
    if previous.get('record_count') != len(rows):
        raise ValueError('accepted row count mismatch')
    for row in rows:
        s = row['source']
        if s['sha256'] != manifest['sha256']:
            raise ValueError('source SHA mismatch')
        expected = f"xlsx:{s['sha256']}:{s['member']}:{s['row']}"
        if row['record_id'] != expected:
            raise ValueError('row provenance mismatch')
    result = build_registry(rows)
    provenance = {
        'input_hashes': {p.name: hashlib.sha256(b).hexdigest() for p, b in zip(paths, blobs)},
        'original_xlsx_sha256': manifest['sha256'], 'no_xlsx_reimport': True,
        'source_level_research_does_not_verify_rows': True,
    }
    output_dir = Path(output_dir)
    target_paths = [output_dir/name for name in ('bridge-evidence-gaps.jsonl', 'summary.json', 'manifest.json')]
    if {p.resolve() for p in target_paths} & {p.resolve() for p in paths}:
        raise ValueError('output would overwrite accepted input')
    output_dir.mkdir(parents=True, exist_ok=True)
    output = [
        ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True)+'\n' for r in result['records']),
        json.dumps(result['summary'], sort_keys=True, indent=2)+'\n',
        json.dumps(provenance, sort_keys=True, indent=2)+'\n',
    ]
    for path, text in zip(target_paths, output):
        path.write_text(text, encoding='utf-8')
    if any(p.read_bytes() != b for p, b in zip(paths, blobs)):
        raise RuntimeError('accepted input changed during processing')
    return result['summary']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accepted-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(process_accepted(args.accepted_dir/'records.jsonl', args.accepted_dir/'manifest.json',
                                      args.accepted_dir/'summary.json', args.output_dir), sort_keys=True))


if __name__ == '__main__':
    main()
