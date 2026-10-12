"""Read-only road-class inventory; administrative coverage is never inferred."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sqlite3

REGIONS = ('NORTH', 'HAIFA', 'TEL_AVIV', 'CENTER', 'JERUSALEM', 'SOUTH')


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(graph, regional_matrix):
    """Count all source ways/segments, including excluded/nonmotorway classes.

    A count is a source inventory, not inspected restrictions, physical kilometres,
    legal national membership, or coverage percentage. No regional geometry exists
    in this contract, so regional denominators remain null rather than zero.
    """
    keys = [r['region'] for r in regional_matrix]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate region')
    if not set(REGIONS) <= set(keys):
        raise ValueError('six regional research buckets required')
    graph = Path(graph)
    before = sha256(graph)
    ways, segments, directions = Counter(), Counter(), Counter()
    with sqlite3.connect(graph.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        for raw, count in db.execute('SELECT tags,count(*) FROM ways GROUP BY tags'):
            road_class = json.loads(raw).get('highway') or 'UNKNOWN'
            ways[str(road_class)] += count
        for raw, direction, count in db.execute('SELECT w.tags,s.direction,count(*) FROM segments s JOIN ways w ON w.id=s.way_id GROUP BY w.tags,s.direction'):
            road_class = str(json.loads(raw).get('highway') or 'UNKNOWN')
            segments[road_class] += count
            directions[(road_class, str(direction or 'UNKNOWN'))] += count
        source_segments = db.execute('SELECT count(*) FROM segments').fetchone()[0]
        if sum(segments.values()) != source_segments:
            raise ValueError('orphan segment: class inventory would undercount')
    if sha256(graph) != before:
        raise RuntimeError('graph changed')
    rows = [dict(road_class=k, source_ways=ways[k], source_segments=segments[k],
                 direction_counts={d: n for (c, d), n in sorted(directions.items()) if c == k},
                 independently_verified_restriction_denominator=None,
                 completeness='UNKNOWN', geography='UNRESOLVED_SOURCE_EXTENT')
            for k in sorted(ways)]
    regions = {r['region']: r for r in regional_matrix}
    cross = [dict(region=r, road_class=k, source_way_denominator=None,
                  inspected_restrictions=None, verified_restrictions=None,
                  regional_record_total=regions[r]['records'],
                  class_attribution='UNKNOWN', completeness='UNKNOWN',
                  reason='NO_VALIDATED_REGION_TO_GRAPH_OR_RECORD_TO_CLASS_BINDING')
             for r in REGIONS for k in sorted(ways)]
    return dict(schema_version='stage8.coverage.v1', synthetic=False,
                graph_sha256=before, graph_unchanged=True,
                source_way_count=sum(ways.values()), source_segment_count=source_segments,
                road_classes=rows, region_road_classes=cross,
                legal_boundary_reference=False, navigation_eligible=False,
                independent_completeness_denominator=None,
                method='Each source way once; each stored source segment once, not directed arcs. highway tag kept verbatim. Regional record totals repeat across classes and MUST NOT be summed.')


def write(result, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    (out / 'road-class-coverage.json').write_text(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2) + '\n')
    for key in ('road_classes', 'region_road_classes'):
        with (out / (key + '.csv')).open('w', newline='') as stream:
            rows = result[key]
            if not rows:
                continue
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v, sort_keys=True) if isinstance(v, dict) else v for k, v in row.items()} for row in rows)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--graph', type=Path, required=True)
    p.add_argument('--regional-matrix', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    write(inventory(args.graph, json.loads(args.regional_matrix.read_text())), args.output)
