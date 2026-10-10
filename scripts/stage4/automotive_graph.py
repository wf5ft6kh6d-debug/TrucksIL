"""Conservative derived automotive research layer; never a travel authorization."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sqlite3
import time

POLICY_VERSION = 'automotive-research-v1'
ROAD_CLASSES = frozenset(('motorway motorway_link trunk trunk_link primary primary_link secondary secondary_link tertiary tertiary_link unclassified residential living_street service').split())
NON_MOTOR_CLASSES = frozenset(('footway pedestrian cycleway steps bridleway corridor platform').split())
ACCESS_KEYS = ('motorcar', 'motor_vehicle', 'vehicle', 'access')
ALLOW = frozenset(('yes', 'designated', 'permissive'))
DENY = frozenset(('no', 'private'))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def classify(tags):
    """Classify morphology separately from tagged access and HGV applicability.

    motorcar precedence describes passenger-car scope only; never transfers to HGV.
    Missing access remains unknown even on a road-class candidate. Conditional,
    directional, reversible or unrecognized values require separate review.
    """
    key = next((k for k in ACCESS_KEYS if k in tags), None)
    raw = tags.get(key) if key else None
    access = 'UNKNOWN' if key is None or (key == 'access' and raw == 'designated') else ('TAGGED_ALLOWED' if raw in ALLOW else 'TAGGED_DENIED' if raw in DENY else 'UNKNOWN')
    hgv = {k: v for k, v in tags.items() if k == 'hgv' or k.startswith('hgv:')}
    result = dict(status='QUARANTINE', reason='unclassified_highway', access_status=access,
                  access_key=key, access_value=raw, hgv_tags=hgv,
                  truck_access='UNKNOWN', independently_verified=False)
    def done(status, reason):
        result.update(status=status, reason=reason)
        return result
    if tags.get('area') == 'yes':
        return done('EXCLUDED', 'area_geometry_not_centerline')
    if tags.get('area') not in (None, 'no'):
        return done('QUARANTINE', 'unrecognized_area_value')
    highway = tags.get('highway')
    if highway in ('construction', 'proposed', 'abandoned', 'razed'):
        return done('EXCLUDED', 'not_current_road_class')
    if any(k.startswith(('construction:', 'proposed:', 'abandoned:', 'disused:', 'demolished:')) for k in tags):
        return done('QUARANTINE', 'lifecycle_tags_need_review')
    # An explicit vehicle permission on a pedestrian class is conflicting evidence,
    # not enough to convert that geometry into a drivable centreline.
    if highway in NON_MOTOR_CLASSES:
        override = any(tags.get(k) in ALLOW or any(t.startswith(k + ':') for t in tags) for k in ACCESS_KEYS[:-1])
        return done('QUARANTINE' if override else 'EXCLUDED', 'non_motor_class_with_vehicle_evidence' if override else 'non_motor_class')
    if highway not in ROAD_CLASSES:
        return result
    if any(k.startswith(a + ':') for k in tags for a in ACCESS_KEYS):
        return done('QUARANTINE', 'conditional_or_scoped_access')
    if key == 'access' and raw == 'designated':
        return done('QUARANTINE', 'blanket_designated_has_no_transport_mode')
    if raw in DENY:
        return done('EXCLUDED', 'explicit_car_access_denied')
    if key is not None and raw not in ALLOW:
        return done('QUARANTINE', 'restricted_or_unrecognized_car_access')
    if any(k.startswith('oneway:') for k in tags) or tags.get('oneway') not in (None, 'yes', '1', 'true', '-1', 'no', '0', 'false'):
        return done('QUARANTINE', 'scoped_or_unrecognized_direction')
    return done('INCLUDED', 'road_class_candidate_access_unknown' if key is None else 'road_class_tagged_car_access')


def build(source, output, manifest):
    start = time.monotonic()
    source = Path(source).resolve()
    out = Path(output)
    if out.exists():
        raise ValueError('Refuse existing output directory')
    m = json.loads(Path(manifest).read_text())
    if m.get('license') != 'ODbL-1.0' or not m.get('attribution'):
        raise ValueError('Unapproved or missing source licence/attribution')
    source_hash = sha256(source)
    out.mkdir(parents=True)
    db = sqlite3.connect(out / 'automotive.sqlite', uri=True)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('ATTACH DATABASE ? AS original', (source.as_uri() + '?mode=ro',))
    db.executescript('''
      CREATE TABLE ways(id INTEGER PRIMARY KEY,version INTEGER,timestamp TEXT,tags TEXT,nodes TEXT,
        status TEXT NOT NULL CHECK(status IN ('INCLUDED','EXCLUDED','QUARANTINE')),
        reason TEXT NOT NULL,decision TEXT NOT NULL);
      CREATE TABLE nodes(id INTEGER PRIMARY KEY,lon REAL,lat REAL);
      CREATE TABLE segments(id INTEGER PRIMARY KEY,way_id INTEGER REFERENCES ways(id),seq INTEGER,
        a INTEGER REFERENCES nodes(id),b INTEGER REFERENCES nodes(id),direction TEXT,geom TEXT,length_m REAL,tile TEXT);
    ''')
    classes = collections.defaultdict(collections.Counter)
    decisions = collections.Counter()
    reasons = collections.Counter()
    batch = []
    for row in db.execute('SELECT id,version,timestamp,tags,nodes FROM original.ways ORDER BY id'):
        tags = json.loads(row[3]); decision = classify(tags)
        classes[tags.get('highway', 'MISSING')][decision['status']] += 1
        decisions[decision['status']] += 1; reasons[decision['reason']] += 1
        batch.append((*row, decision['status'], decision['reason'], json.dumps(decision, sort_keys=True)))
        if len(batch) == 10000:
            db.executemany('INSERT INTO ways VALUES(?,?,?,?,?,?,?,?)', batch); batch = []
    db.executemany('INSERT INTO ways VALUES(?,?,?,?,?,?,?,?)', batch)
    db.execute('INSERT INTO nodes SELECT * FROM original.nodes')
    db.execute('INSERT INTO segments SELECT * FROM original.segments')
    db.executescript('''
      CREATE INDEX ways_status ON ways(status);
      CREATE INDEX segments_way ON segments(way_id);
      CREATE INDEX segments_a ON segments(a);
      CREATE INDEX segments_b ON segments(b);
      CREATE VIEW automotive_segments AS SELECT s.* FROM segments s JOIN ways w ON w.id=s.way_id WHERE w.status='INCLUDED';
      CREATE VIEW quarantine_segments AS SELECT s.* FROM segments s JOIN ways w ON w.id=s.way_id WHERE w.status='QUARANTINE';
      CREATE VIEW excluded_segments AS SELECT s.* FROM segments s JOIN ways w ON w.id=s.way_id WHERE w.status='EXCLUDED';
      CREATE TABLE automotive_node_ids(id INTEGER PRIMARY KEY REFERENCES nodes(id));
      INSERT OR IGNORE INTO automotive_node_ids SELECT a FROM automotive_segments;
      INSERT OR IGNORE INTO automotive_node_ids SELECT b FROM automotive_segments;
      CREATE VIEW automotive_nodes AS SELECT n.* FROM nodes n JOIN automotive_node_ids a ON a.id=n.id;
      CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
    ''')
    for k,v in {'policy': POLICY_VERSION, 'source_sqlite_sha256': source_hash, 'source_pbf_sha256': m['sha256'], 'snapshot_at':m['snapshot_at'], 'license':m['license'], 'attribution':m['attribution'], 'navigation_approved':False}.items():
        db.execute('INSERT INTO metadata VALUES(?,?)', (k, json.dumps(v)))
    db.commit()
    segments = dict(db.execute('SELECT w.status,count(*) FROM segments s JOIN ways w ON s.way_id=w.id GROUP BY w.status'))
    directions = dict(db.execute('SELECT direction,count(*) FROM automotive_segments GROUP BY direction'))
    fk_errors = db.execute('PRAGMA foreign_key_check').fetchall()
    integrity = db.execute('PRAGMA quick_check').fetchone()[0]
    # Full-row comparison, not a sampled check. Original segment/node/way data is unchanged.
    mismatches = {}
    for table, cols in [('segments','*'),('nodes','*'),('ways','id,version,timestamp,tags,nodes')]:
        mismatches[table] = db.execute(f'SELECT count(*) FROM (SELECT {cols} FROM {table} EXCEPT SELECT * FROM original.{table})').fetchone()[0] + db.execute(f'SELECT count(*) FROM (SELECT * FROM original.{table} EXCEPT SELECT {cols} FROM {table})').fetchone()[0]
    nodes = db.execute('SELECT count(*) FROM automotive_node_ids').fetchone()[0]
    db.close()
    if sha256(source) != source_hash:
        raise ValueError('Original graph changed during processing')
    if fk_errors or integrity != 'ok' or any(mismatches.values()):
        raise ValueError('Derived source preservation/integrity failure')
    summary = dict(policy=POLICY_VERSION,source_sqlite_sha256=source_hash,source_pbf_sha256=m['sha256'],snapshot_at=m['snapshot_at'],license=m['license'],attribution=m['attribution'],way_counts=dict(decisions),segment_counts=segments,automotive_nodes=nodes,automotive_directions=directions,highway_class_decisions={k:dict(v) for k,v in sorted(classes.items())},reason_way_counts=dict(reasons),full_row_source_comparison_mismatches=mismatches,foreign_key_errors=len(fk_errors),sqlite_quick_check=integrity,verified_restrictions=0,navigation_approved=False,source_graph_unchanged=True,processing_seconds=time.monotonic()-start,output_sqlite_sha256=sha256(out/'automotive.sqlite'))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('output');p.add_argument('--manifest',default='data/stage4/national-source-manifest.json');a=p.parse_args();build(a.source,a.output,a.manifest)
