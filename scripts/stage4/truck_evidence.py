"""Lossless research evidence queue; no navigation permissions or verification inferred."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from jsonschema import Draft202012Validator

DIMENSIONS = {'maxheight', 'maxwidth', 'maxlength'}
MASSES = {'maxweight', 'maxaxleload'}
GATES = ['competent_independent_source', 'document_identity_and_validity',
         'exact_geometry_and_direction', 'vehicle_applicability',
         'units_and_value', 'reuse_rights', 'independent_reviewer']


def parse_measurement(key, raw):
    """Only explicit, positive SI unit values; bare OSM defaults intentionally unresolved."""
    base = key.split(':')[0]
    result = {'raw': raw, 'value': None, 'unit': None, 'status': 'UNKNOWN'}
    match = re.fullmatch(r'\s*([0-9]+(?:\.[0-9]+)?)\s*(m|t|kg)\s*', raw)
    if not match:
        return result
    value, unit = float(match[1]), match[2]
    if not math.isfinite(value) or value <= 0 or unit not in ({'m'} if base in DIMENSIONS else {'t', 'kg'} if base in MASSES else set()):
        return result
    result.update(value=value, unit=unit, status='PARSED_EXPLICIT_UNIT')
    return result


def build_record(row, manifest):
    typ, oid, version, timestamp, tags_raw, categories_raw, geometry_raw, status = row
    if status != 'QUARANTINE':
        raise ValueError('source candidate must remain QUARANTINE')
    tags, categories, geometry = map(json.loads, (tags_raw, categories_raw, geometry_raw))
    context_only = set(categories) <= {'bridge_context', 'tunnel_context'}
    measurements = {k: parse_measurement(k, v) for k, v in tags.items()
                    if k.split(':')[0] in DIMENSIONS | MASSES}
    # Preserve qualifiers. Parsing a number does not determine directional/time applicability.
    direction_tags = {k:v for k,v in tags.items() if k in ('oneway','direction') or
                      any(x in k.split(':') for x in ('forward','backward','direction'))}
    temporal_tags = {k:v for k,v in tags.items() if 'conditional' in k.split(':') or
                     k in ('opening_hours','start_date','end_date')}
    record = {
        'schema_version': 1, 'candidate_id': f'{typ}/{oid}',
        'osm': {'type': typ, 'id': oid, 'version': version, 'timestamp': timestamp,
                'url': f'https://www.openstreetmap.org/{typ}/{oid}'},
        'raw_tags': tags, 'categories': categories, 'geometry': geometry,
        'source_payload': {'tags_json': tags_raw, 'categories_json': categories_raw,
                           'geometry_json': geometry_raw},
        'provenance': {k: manifest[k] for k in ('source_id','url','sha256','snapshot_at','retrieved_at','license','license_url','attribution')},
        'status': 'QUARANTINE', 'navigation_eligible': False,
        'quarantine_reason': ['no_independent_source_evidence'] + (['infrastructure_context_is_not_a_truck_restriction'] if context_only else []),
        'required_additional_evidence': list(GATES),
        'context_only': context_only, 'measurements': measurements,
        'direction': {'status':'UNKNOWN', 'raw_tags': direction_tags},
        'temporal_applicability': {'status':'UNKNOWN', 'raw_tags': temporal_tags},
        'truck_applicability': 'UNKNOWN',
        'independent_evidence': [],
        'acceptance': {'automatic_promotion':False, 'required_gates':GATES,
                       'gate_status': {g:'UNKNOWN' for g in GATES}},
    }
    return record


def run(database, manifest_path, schema_path, output):
    manifest = json.loads(Path(manifest_path).read_text())
    if manifest.get('license') != 'ODbL-1.0' or not manifest.get('attribution'):
        raise ValueError('confirmed source licence and attribution required')
    if not re.fullmatch('[0-9a-f]{64}', manifest.get('sha256','')):
        raise ValueError('invalid source hash')
    schema = json.loads(Path(schema_path).read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    folder = Path(output); folder.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro', uri=True)
    rows = db.execute('SELECT type,id,version,timestamp,tags,categories,geometry,status FROM candidates ORDER BY type,id')
    counts, categories, parse_status = Counter(), Counter(), Counter()
    target = folder/'candidates.jsonl'
    digest = hashlib.sha256()
    with target.open('wb') as dest:
        for row in rows:
            rec = build_record(row, manifest)
            validator.validate(rec)
            counts['candidates'] += 1
            counts[row[0]] += 1
            counts['context_only'] += rec['context_only']
            categories.update(rec['categories'])
            parse_status.update(x['status'] for x in rec['measurements'].values())
            for field, original in [('raw_tags',row[4]),('categories',row[5]),('geometry',row[6])]:
                if rec[field] != json.loads(original):
                    raise ValueError('lossy source projection')
            line = (json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(',',':'))+'\n').encode()
            digest.update(line); dest.write(line)
    db.close()
    summary = {'source_sha256':manifest['sha256'], 'source_snapshot_at':manifest['snapshot_at'],
               'counts':dict(counts), 'categories':dict(categories),
               'measurement_parse_status':dict(parse_status),
               'verified_restrictions':0, 'navigation_eligible':0,
               'all_candidates_quarantined':True, 'independent_schema_engine':'jsonschema Draft202012Validator',
               'schema_validated_records':counts['candidates'], 'source_payload_preserved':True,
               'output_sha256':digest.hexdigest(), 'output_bytes':target.stat().st_size,
               'limitations':['OSM tags are not independent evidence',
                             'No automatic interpretation of implicit units, directions or conditions',
                             'Bridge/tunnel context alone is not a truck restriction',
                             'Relation geometries remain original unassembled member references']}
    (folder/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary, ensure_ascii=False))
    return summary

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', required=True)
    p.add_argument('--manifest', default='data/stage4/national-source-manifest.json')
    p.add_argument('--schema', default='data/stage4/truck-evidence.schema.json')
    p.add_argument('--output', required=True)
    a = p.parse_args(); run(a.database, a.manifest, a.schema, a.output)
