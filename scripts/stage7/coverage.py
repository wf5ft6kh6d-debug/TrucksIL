"""Conservative research coverage. Road references are candidates, never bindings.

No input is mutated. SQLite is opened read-only. This module makes no legal
boundary, connectivity, restriction-verification or navigation decisions.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sqlite3

REGIONS = ('NATIONAL', 'NORTH', 'HAIFA', 'TEL_AVIV', 'CENTER', 'JERUSALEM', 'SOUTH', 'UNKNOWN')
CANDIDATE_LIMIT = 50


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def region(value):
    return value if value in REGIONS else 'UNKNOWN'


def build_coverage(sources, records, graph_path=None, search_attempts=()):
    """Return matrix, geolocation and graph_observation, with explicit gaps.

    An OSM ref alone does not identify a carriageway or the limits of a rule.
    Stage7 input has no audited source-to-OSM-ID relation, so no exact binding
    is produced, even if just one OSM way has a matching road reference.
    """
    if len({s['source_id'] for s in sources}) != len(sources):
        raise ValueError('duplicate source ID')
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('duplicate record ID')
    if any(r.get('synthetic') is not False for r in records):
        raise ValueError('synthetic fixtures must not enter real coverage')
    source_ids = {s['source_id'] for s in sources}
    if any(not set(r['sources']) <= source_ids for r in records):
        raise ValueError('record references missing source')
    requested = {ref for r in records if r['scope'] == 'LOCAL' for ref in r['location']['road_refs']}
    candidates = {ref: [] for ref in requested}
    counts = Counter()
    observation = {'availability': 'NOT_SUPPLIED', 'content_checked': False,
                   'sha256': None, 'size_bytes': None, 'immutable_verified': None,
                   'legal_boundary_reference': False, 'independent_completeness_reference': False}
    if graph_path is not None:
        path = Path(graph_path)
        if not path.is_file():
            observation['availability'] = 'UNAVAILABLE_AT_REQUESTED_PATH'
        else:
            before = sha256(path)
            observation.update(availability='AVAILABLE', sha256=before, size_bytes=path.stat().st_size)
            with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as con:
                con.execute('PRAGMA query_only=ON')
                observation['way_count'] = con.execute('SELECT count(*) FROM ways').fetchone()[0]
                observation['segment_count'] = con.execute('SELECT count(*) FROM segments').fetchone()[0]
                # Exact token matching, no substring/geometric intersection/snapping.
                if requested:
                    for way_id, tags_json in con.execute('SELECT id,tags FROM ways ORDER BY id'):
                        tags = json.loads(tags_json)
                        refs = {v.strip() for v in str(tags.get('ref', '')).split(';')}
                        for ref in refs & requested:
                            counts[ref] += 1
                            if len(candidates[ref]) < CANDIDATE_LIMIT:
                                candidates[ref].append(way_id)
                observation['content_checked'] = True
            observation['immutable_verified'] = before == sha256(path)
            if not observation['immutable_verified']:
                raise RuntimeError('source graph changed during read')
    bindings = []
    for r in sorted(records, key=lambda x: x['id']):
        refs = sorted(set(r['location']['road_refs'])) if r['scope'] == 'LOCAL' else []
        available = observation['content_checked']
        ids = sorted({i for ref in refs for i in candidates.get(ref, [])})[:CANDIDATE_LIMIT]
        if r['scope'] == 'GENERAL_VEHICLE_NORM':
            status, reason = 'NOT_APPLICABLE', 'GENERAL_NORM_IS_NOT_A_LOCAL_ROAD_RESTRICTION'
        elif not available:
            status, reason = 'UNKNOWN', 'GRAPH_UNAVAILABLE_FOR_THIS_RUN'
        elif not refs:
            status, reason = 'UNKNOWN', 'NO_MACHINE_ROAD_IDENTIFIER_IN_SOURCE'
        elif not ids:
            status, reason = 'UNKNOWN', 'NO_EXACT_ROAD_REF_CANDIDATE_NOT_PROOF_OF_NO_ROAD'
        else:
            status, reason = 'AMBIGUOUS', 'ROAD_REF_DOES_NOT_PROVE_STRUCTURE_SEGMENT_DIRECTION_OR_LANE'
        bindings.append({'record_id': r['id'], 'binding_status': status, 'reason': reason,
                         'candidate_way_ids': ids, 'candidate_counts_by_ref': {ref: counts[ref] for ref in refs} if available else None,
                         'candidate_list_limit': CANDIDATE_LIMIT, 'candidate_list_may_be_truncated': any(counts[ref] > CANDIDATE_LIMIT for ref in refs) or len({i for ref in refs for i in candidates.get(ref, [])}) > CANDIDATE_LIMIT,
                         'bound_geometry': None, 'direction_binding': 'UNKNOWN',
                         'jurisdiction_status': 'UNKNOWN', 'navigation_eligible': False})
    by_id = {b['record_id']: b for b in bindings}
    rows = []
    for key in REGIONS:
        selected_sources = [s for s in sources if key in {region(v) for v in s.get('regions', ['UNKNOWN'])}]
        selected_records = [r for r in records if region(r['location'].get('region')) == key]
        rows.append({'region': key, 'source_registry_entries': len(selected_sources),
                     'search_attempts': sum(region(a.get('region')) == key for a in search_attempts),
                     'query_passes_executed': sorted({a['query_pass'] for a in search_attempts if region(a.get('region')) == key and a.get('query_pass') in (1, 2)}),
                     'valid_query_attempts': sum(region(a.get('region')) == key and a.get('query_pass') in (1, 2) for a in search_attempts),
                     'invalid_query_attempts': sum(region(a.get('region')) == key and a.get('query_pass') == 0 for a in search_attempts),
                     'source_status_counts': dict(sorted(Counter(s['source_status'] for s in selected_sources).items())),
                     'records': len(selected_records), 'local_restrictions': sum(r['scope'] == 'LOCAL' for r in selected_records),
                     'general_vehicle_norms': sum(r['scope'] == 'GENERAL_VEHICLE_NORM' for r in selected_records),
                     'verified_records': sum(r['evidence_status'] == 'VERIFIED' for r in selected_records),
                     'ambiguous_bindings': sum(by_id[r['id']]['binding_status'] == 'AMBIGUOUS' for r in selected_records),
                     'unknown_bindings': sum(by_id[r['id']]['binding_status'] == 'UNKNOWN' for r in selected_records),
                     'exact_bindings': 0, 'completeness': 'UNKNOWN',
                     'gap_reasons': ['NO_INDEPENDENT_COMPLETE_RESTRICTION_INVENTORY', 'SEARCH_ANCHORS_DO_NOT_COVER_ALL_MUNICIPALITIES', 'NO_VALIDATED_LEGAL_BOUNDARY_OR_ALL_ROAD_DIRECTION_MAPPING']})
    return {'matrix': rows, 'geolocation': bindings, 'graph_observation': observation}


def write_outputs(result, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    for key in ('matrix', 'graph_observation'):
        (output / (key + '.json')).write_text(json.dumps(result[key], ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    (output / 'geolocation.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in result['geolocation']))
    with (output / 'matrix.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(result['matrix'][0]))
        writer.writeheader()
        for row in result['matrix']:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def main():
    p = argparse.ArgumentParser(); p.add_argument('--sources', type=Path, required=True); p.add_argument('--records', type=Path, required=True); p.add_argument('--graph', type=Path); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    def read(path, key):
        if path.suffix == '.jsonl': return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        data = json.loads(path.read_text()); return data[key] if isinstance(data, dict) else data
    source_data = json.loads(a.sources.read_text()) if a.sources.suffix != '.jsonl' else {}
    attempts = source_data.get('search_attempts', []) if isinstance(source_data, dict) else []
    write_outputs(build_coverage(read(a.sources, 'sources'), read(a.records, 'records'), a.graph, attempts), a.output)


if __name__ == '__main__':
    main()
