"""Independent stage5 evidence-envelope checks. Never imports producer code.

This validates research representation, not legal currency or route safety.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit_file(path, expected_source_hashes=None):
    """Validate every line; optional hashes bind records to independently hashed inputs."""
    sources = Counter()
    statuses = Counter()
    kinds = Counter()
    seen = set()
    with open(path, encoding='utf-8') as stream:
        for lineno, line in enumerate(stream, 1):
            require(bool(line.strip()), f'line {lineno}: empty record')
            row = json.loads(line)
            prefix = f'line {lineno}'
            require(row.get('schema_version') == 'stage5.research.v1', prefix + ': schema_version')
            identity = row.get('record_id')
            require(isinstance(identity, str) and bool(identity.strip()), prefix + ': record_id')
            require(identity not in seen, prefix + ': duplicate record_id')
            seen.add(identity)
            require(row.get('navigation_eligible') is False, prefix + ': navigation must be false')
            require(type(row.get('synthetic')) is bool, prefix + ': synthetic must be explicit')
            require(row.get('status') in {'UNKNOWN', 'QUARANTINE'}, prefix + ': unverified status escalation')
            require(isinstance(row.get('kind'), str) and bool(row['kind']), prefix + ': kind')
            require(isinstance(row.get('raw'), dict), prefix + ': raw source payload absent')
            require(isinstance(row.get('interpretation'), dict), prefix + ': interpretation')
            reasons = row.get('reasons')
            require(isinstance(reasons, list) and bool(reasons) and all(isinstance(x, str) and x.strip() for x in reasons), prefix + ': explicit reasons required')
            source = row.get('source')
            require(isinstance(source, dict), prefix + ': source absent')
            for key in ('source_id', 'source_type', 'locator'):
                require(isinstance(source.get(key), str) and bool(source[key].strip()), prefix + ': source.' + key)
            require('retrieved_at' in source and 'sha256' in source, prefix + ': source metadata absent')
            sha = source['sha256']
            require(sha is None or isinstance(sha, str) and bool(re.fullmatch('[0-9a-f]{64}', sha)), prefix + ': invalid sha256')
            if expected_source_hashes and source['source_id'] in expected_source_hashes:
                require(sha == expected_source_hashes[source['source_id']], prefix + ': source digest mismatch')
            if row['synthetic']:
                require(source['source_type'].lower() == 'synthetic', prefix + ': synthetic provenance mislabeled')
            else:
                require(source['source_type'].lower() != 'synthetic', prefix + ': real provenance mislabeled')
            require('geometry' in row, prefix + ': geometry must be explicit')
            require(row['geometry'] is None or isinstance(row['geometry'], dict), prefix + ': geometry')
            sources[source['source_id']] += 1
            statuses[row['status']] += 1
            kinds[row['kind']] += 1
    require(bool(seen), 'empty research output')
    return {'technical_envelope_status': 'PASS', 'official_validity': 'BLOCKED', 'navigation_eligible': False,
            'records_checked': len(seen), 'sources': dict(sorted(sources.items())),
            'statuses': {'VERIFIED': 0, **dict(sorted(statuses.items()))}, 'kinds': dict(sorted(kinds.items())),
            'research_sha256': digest(path),
            'scope': 'Every envelope, identity uniqueness, uncertainty, explicit provenance; semantic source reconciliation reported separately.'}


def audit_barrier_sources(pbf, graph, directory):
    """Re-read PBF nodes and SQLite ways; independently reconcile every extracted row."""
    import osmium
    import sqlite3
    directory = Path(directory)
    def rows(name):
        with (directory / name).open() as stream:
            return [json.loads(line) for line in stream]
    actual_nodes = rows('barrier-nodes.jsonl')
    node_map = {r['object_id']: r for r in actual_nodes}
    require(len(node_map) == len(actual_nodes), 'duplicate barrier node')
    modes = {'access', 'vehicle', 'motor_vehicle', 'hgv'}
    def relevant(tags):
        return 'barrier' in tags or any(k.split(':', 1)[0] in modes for k in tags)
    seen = set()
    class Reader(osmium.SimpleHandler):
        def node(self, node):
            tags = dict(node.tags)
            if not relevant(tags):
                return
            require(node.id in node_map, f'missing source node {node.id}')
            row = node_map[node.id]
            require(row['tags'] == tags and row['version'] == node.version and row['timestamp'] == str(node.timestamp), f'node provenance {node.id}')
            geom = {'type': 'Point', 'coordinates': [node.location.lon, node.location.lat]} if node.location.valid() else None
            require(row['geometry'] == geom, f'node coordinates {node.id}')
            require(row['navigation_eligible'] is False and row['evidence_status'] == 'QUARANTINE', 'node evidence escalation')
            seen.add(node.id)
    Reader().apply_file(str(pbf))
    require(seen == set(node_map), 'extra source nodes')
    way_rows = rows('way-access.jsonl')
    ways = {r['object_id']: r for r in way_rows}
    require(len(ways) == len(way_rows), 'duplicate way')
    inc_rows = rows('node-way-access.jsonl')
    inc = {(r['way_id'], r['way_node_position'], r['node_id']): r for r in inc_rows}
    require(len(inc) == len(inc_rows), 'duplicate incidence')
    expected_inc = set()
    expected_ways = set()
    db = sqlite3.connect(Path(graph).resolve().as_uri() + '?mode=ro', uri=True)
    occurrences = Counter()
    for oid, version, timestamp, raw_tags, raw_nodes in db.execute('SELECT id,version,timestamp,tags,nodes FROM ways'):
        tags = json.loads(raw_tags)
        if relevant(tags):
            expected_ways.add(oid)
            require(oid in ways, f'missing way {oid}')
            row = ways[oid]
            require(row['tags'] == tags and row['version'] == version and row['timestamp'] == timestamp, f'way provenance {oid}')
        for position, node in enumerate(json.loads(raw_nodes)):
            if node in node_map:
                key = (oid, position, node)
                expected_inc.add(key)
                occurrences[node] += 1
                require(key in inc, f'missing incidence {key}')
                require(inc[key]['way_version'] == version and inc[key]['node_version'] == node_map[node]['version'], 'incidence version mismatch')
    db.close()
    require(expected_ways == set(ways), 'unexpected access ways')
    require(expected_inc == set(inc), 'unexpected node-way incidence')
    for oid, row in node_map.items():
        require(row['source_way_occurrences'] == occurrences[oid], 'node occurrence mismatch')
    return {'status': 'PASS', 'scope': 'full PBF-node provenance, all SQLite-way provenance and exact node membership',
            'nodes_checked': len(node_map), 'ways_checked': len(ways), 'incidences_checked': len(inc)}


def audit_temporal_sources(graph, temporal_records, turn_records):
    """Compare full source inventories; independently verify each supported directed chain."""
    import sqlite3
    db = sqlite3.connect(Path(graph).resolve().as_uri() + '?mode=ro', uri=True)
    expected = {}
    for table, fixed_type in [('ways', 'way'), ('relations', 'relation'), ('candidates', None)]:
        sql = 'SELECT id,tags' + (',type' if fixed_type is None else '') + ' FROM ' + table
        for row in db.execute(sql):
            kind = fixed_type or {'n':'node','w':'way','r':'relation'}.get(row[2], row[2])
            for key, value in json.loads(row[1]).items():
                if ':conditional' in key:
                    identity = (kind, row[0], key)
                    require(identity not in expected or expected[identity] == value, 'conflicting source condition')
                    expected[identity] = value
    found = {}
    for row in temporal_records:
        identity = (row['object_type'], row['object_id'], row['tag_key'])
        require(identity not in found, 'duplicate conditional')
        found[identity] = row['raw']
        require(row['status'] == 'QUARANTINE' and row['navigation_eligible'] is False, 'conditional evidence escalation')
        if row['parse_status'] == 'SUPPORTED':
            require(row['timezone'] == 'Asia/Jerusalem', 'timezone mismatch')
            require(0 <= row['start_minute'] < 1440 and 0 <= row['end_minute'] <= 1440, 'invalid minute bounds')
    require(expected == found, 'conditional inventory/source mismatch')
    observed_turns = set()
    supported = 0
    for row in turn_records:
        identity = row['object_id']
        require(identity not in observed_turns, 'duplicate turn')
        observed_turns.add(identity)
        source = db.execute('SELECT tags,members,missing_refs FROM relations WHERE id=?', (identity,)).fetchone()
        require(source is not None, 'unknown turn source')
        require(row['raw'] == {'tags':json.loads(source[0]), 'members':json.loads(source[1])}, 'turn raw source mismatch')
        require(row['missing_refs'] == json.loads(source[2]), 'missing reference mismatch')
        require(row['status'] == 'QUARANTINE' and row['navigation_eligible'] is False, 'turn evidence escalation')
        if row['parse_status'] != 'SUPPORTED':
            continue
        supported += 1
        require(not row['missing_refs'] and not row['reasons'], 'supported turn has errors')
        chain = row['chain_way_ids']; joins = row['connection_node_ids']
        require(len(joins) == len(chain)-1, 'chain length mismatch')
        way_nodes = []
        for i, wid in enumerate(chain):
            w = db.execute('SELECT nodes,tags FROM ways WHERE id=?', (wid,)).fetchone()
            require(w is not None, 'missing chain way')
            nodes, tags = json.loads(w[0]), json.loads(w[1])
            require(not any(k.startswith('oneway:') for k in tags), 'supported modified direction')
            require(tags.get('oneway') in {'yes','1','true','-1','no','0','false'}, 'implicit supported direction')
            arcs = set()
            for a,b in zip(nodes, nodes[1:]):
                if tags['oneway'] != '-1': arcs.add((a,b))
                if tags['oneway'] in {'-1','no','0','false'}: arcs.add((b,a))
            if i == 0:
                require(any(b == joins[0] for a,b in arcs), 'from cannot reach via')
            elif i == len(chain)-1:
                require(any(a == joins[-1] for a,b in arcs), 'to cannot leave via')
            else:
                current = {joins[i-1]}; reached = set(current)
                while current:
                    current = {b for a,b in arcs if a in current} - reached
                    reached.update(current)
                require(joins[i] in reached and joins[i] != joins[i-1], 'via cannot traverse chain')
            way_nodes.append(set(nodes))
        for i, join in enumerate(joins):
            require(join in way_nodes[i] & way_nodes[i+1], 'nonshared join')
    expected_turns = {row[0] for row in db.execute('SELECT id FROM relations')}
    db.close()
    require(observed_turns == expected_turns, 'turn inventory mismatch')
    return {'status':'PASS', 'conditional_records_checked':len(found), 'turn_records_checked':len(observed_turns),
            'supported_chains_independently_traversed':supported, 'scope':'full original payload and inventory; supported direction chains independently traversed'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('research')
    parser.add_argument('--source-hashes', help='JSON mapping source_id to independently computed SHA-256')
    parser.add_argument('--output')
    args = parser.parse_args()
    hashes = json.loads(Path(args.source_hashes).read_text()) if args.source_hashes else None
    result = audit_file(args.research, hashes)
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        Path(args.output).write_text(text, encoding='utf-8')
    else:
        print(text, end='')

if __name__ == '__main__':
    main()
