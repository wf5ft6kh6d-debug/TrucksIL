"""Research-only explicit HGV access and node barriers; no implicit national defaults."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

POLICY = 'stage5-explicit-hgv-v1'
HIERARCHY = ('hgv', 'motor_vehicle', 'vehicle', 'access')
RESTRICTED = {'private', 'destination', 'delivery', 'customers', 'permit', 'agricultural', 'forestry'}


def relevant(tags):
    return any(k == 'barrier' or any(k == a or k.startswith(a + ':') for a in HIERARCHY) for k in tags)


def classify_access(tags, direction='forward', is_node=False):
    """Interpret explicit tags only. Direction is relative to the source way order.

    More specific transport mode precedes general modes; within that mode the
    requested direction precedes the unscoped key. Any unsupported modifier or
    conditional remains UNKNOWN, even when a less specific unconditional tag exists.
    Node direction is ambiguous across incident ways, so scoped nodes are UNKNOWN.
    """
    if direction not in ('forward', 'backward'):
        raise ValueError('direction must be forward or backward')
    result = dict(interpretation='UNKNOWN', reason='missing_hgv_applicable_access',
                  selected_key=None, selected_value=None, direction=direction,
                  barrier=tags.get('barrier'), physical_passability='UNKNOWN',
                  evidence_status='QUARANTINE', navigation_eligible=False,
                  policy=POLICY, source_tags=dict(tags))
    modifiers = [k for k in tags if any(k.startswith(a + ':') for a in HIERARCHY)]
    allowed_modifiers = {a + ':' + d for a in HIERARCHY for d in ('forward', 'backward')}
    if any(k not in allowed_modifiers for k in modifiers) or (is_node and modifiers):
        result['reason'] = 'conditional_exception_or_unsupported_scope'
        return result
    # except is meaningful in relation context, not an unconditional access override.
    if 'except' in tags:
        result['reason'] = 'exception_requires_context'
        return result
    for mode in HIERARCHY:
        key = next((k for k in (mode + ':' + direction, mode) if k in tags), None)
        if key is None:
            continue
        value = tags[key]
        result.update(selected_key=key, selected_value=value)
        if value in ('yes', 'permissive') or (value == 'designated' and mode != 'access'):
            result.update(interpretation='TAGGED_ALLOWED', reason='explicit_transport_hierarchy')
        elif value == 'no':
            result.update(interpretation='TAGGED_DENIED', reason='explicit_transport_hierarchy')
        elif value in RESTRICTED:
            result.update(interpretation='RESTRICTED', reason='purpose_or_permission_required')
        else:
            result['reason'] = 'blanket_designated_or_unrecognized_value'
        return result
    if tags.get('barrier') not in (None, 'no'):
        result['reason'] = 'barrier_without_explicit_hgv_access'
    return result


def combine_access(node_decision, way_decision):
    """Node and way are independent constraints: a way grant never clears a gate."""
    n, w = node_decision['interpretation'], way_decision['interpretation']
    if {n, w} == {'TAGGED_ALLOWED', 'TAGGED_DENIED'}:
        interpretation, reason = 'UNKNOWN', 'node_way_conflicting_explicit_access'
    elif 'TAGGED_DENIED' in (n, w):
        interpretation, reason = 'TAGGED_DENIED', 'explicit_denial_on_node_or_way'
    elif 'UNKNOWN' in (n, w):
        interpretation, reason = 'UNKNOWN', 'unresolved_node_or_way'
    elif 'RESTRICTED' in (n, w):
        interpretation, reason = 'RESTRICTED', 'purpose_or_permission_required'
    else:
        interpretation, reason = 'TAGGED_ALLOWED', 'both_explicitly_tagged_allowed'
    return dict(interpretation=interpretation, reason=reason, evidence_status='QUARANTINE',
                navigation_eligible=False, physical_passability='UNKNOWN', policy=POLICY)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def dump(stream, row):
    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n')


def build(pbf, source_sqlite, outdir, manifest):
    import osmium
    pbf, source_sqlite, outdir = Path(pbf), Path(source_sqlite).resolve(), Path(outdir)
    m = json.loads(Path(manifest).read_text())
    if m.get('license') != 'ODbL-1.0' or not m.get('attribution') or not m.get('snapshot_at'):
        raise ValueError('source provenance/license incomplete')
    if sha256(pbf) != m['sha256']:
        raise ValueError('PBF checksum mismatch')
    source_hash = sha256(source_sqlite)
    if outdir.exists():
        raise ValueError('Refuse existing output directory')
    db = sqlite3.connect(source_sqlite.as_uri() + '?mode=ro', uri=True)
    outdir.mkdir(parents=True)
    nodes = {}
    counts, decisions = Counter(), Counter()
    origin = dict(source_id=m['source_id'], source_sha256=m['sha256'], snapshot_at=m['snapshot_at'],
                  license=m['license'], attribution=m['attribution'])
    def row(kind, oid, version, timestamp, tags):
        return dict(object_type=kind, object_id=oid, version=version, timestamp=timestamp,
                    source=origin, tags=tags, evidence_status='QUARANTINE', navigation_eligible=False)
    class Handler(osmium.SimpleHandler):
        def node(self, n):
            counts['pbf_nodes_scanned'] += 1
            if not len(n.tags):
                return
            tags = dict(n.tags)
            if not relevant(tags):
                return
            item = row('node', n.id, n.version, str(n.timestamp), tags)
            item['geometry'] = {'type': 'Point', 'coordinates': [n.location.lon, n.location.lat]} if n.location.valid() else None
            item['decision'] = classify_access(tags, is_node=True)
            nodes[n.id] = item
    Handler().apply_file(str(pbf))
    incidences = Counter()
    with (outdir / 'way-access.jsonl').open('w') as wf, (outdir / 'node-way-access.jsonl').open('w') as nf:
        for oid, version, timestamp, rawtags, raw_nodes in db.execute('SELECT id,version,timestamp,tags,nodes FROM ways ORDER BY id'):
            counts['highway_ways_scanned'] += 1
            tags = json.loads(rawtags)
            attached = [(position, node) for position, node in enumerate(json.loads(raw_nodes)) if node in nodes]
            if not relevant(tags) and not attached:
                continue
            wd = {d: classify_access(tags, d) for d in ('forward', 'backward')}
            if relevant(tags):
                item = row('way', oid, version, timestamp, tags)
                item['decisions'] = wd
                dump(wf, item)
                counts['tagged_way_records'] += 1
                for d in wd.values():
                    decisions['way:' + d['interpretation']] += 1
            for position, node in attached:
                incidences[node] += 1
                item = dict(node_id=node, way_id=oid, way_node_position=position, source=origin,
                            way_version=version, node_version=nodes[node]['version'],
                            evidence_status='QUARANTINE', navigation_eligible=False,
                            decisions={d: combine_access(nodes[node]['decision'], wd[d]) for d in wd},
                            way_decisions=wd)
                dump(nf, item)
                counts['node_way_incidence_records'] += 1
                for d in item['decisions'].values():
                    decisions['incidence:' + d['interpretation']] += 1
    db.close()
    with (outdir / 'barrier-nodes.jsonl').open('w') as stream:
        for node in sorted(nodes):
            item = nodes[node]
            item['source_way_occurrences'] = incidences[node]
            item['localization'] = 'SOURCE_NODE_MEMBERSHIP' if incidences[node] else 'NO_HIGHWAY_MEMBERSHIP'
            dump(stream, item)
            decisions['node:' + item['decision']['interpretation']] += 1
            counts['node_records'] += 1
            counts['barrier_tagged_nodes'] += int('barrier' in item['tags'])
            counts['nodes_without_highway_membership'] += int(not incidences[node])
    if sha256(source_sqlite) != source_hash or sha256(pbf) != m['sha256']:
        raise ValueError('source preservation failure')
    summary = dict(policy=POLICY, source=origin, source_sqlite_sha256=source_hash,
                   counts=dict(sorted(counts.items())), interpretation_counts=dict(sorted(decisions.items())),
                   evidence_status_counts={'VERIFIED': 0, 'QUARANTINE': counts['node_records'] + counts['tagged_way_records'], 'UNKNOWN': 0},
                   status_count_unit='source objects; incidence records excluded; UNKNOWN is interpretation, not evidence status',
                   navigation_eligible=False, source_unchanged=True,
                   outputs={p.name: {'sha256': sha256(p), 'size_bytes': p.stat().st_size} for p in sorted(outdir.glob('*.jsonl'))})
    (outdir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('pbf'); p.add_argument('source_sqlite'); p.add_argument('outdir')
    p.add_argument('--manifest', default='data/stage4/national-source-manifest.json')
    args = p.parse_args()
    print(json.dumps(build(args.pbf, args.source_sqlite, args.outdir, args.manifest), indent=2))
