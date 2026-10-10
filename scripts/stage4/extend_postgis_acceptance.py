"""Add derived research-layer checks inside the existing disposable transaction."""
import argparse
import csv
import json
from pathlib import Path
import sqlite3

MARKER = "SELECT 'NATIONAL FULL ROW / SAMPLE PREDICATE CHECKS PASS';"


def write_checks(out, audit):
    auto = sqlite3.connect((audit/'automotive/automotive.sqlite').resolve().as_uri()+'?mode=ro', uri=True)
    summary = json.loads((audit/'automotive/summary.json').read_text())
    out.write("CREATE TABLE automotive_decisions(way_id bigint PRIMARY KEY REFERENCES ways(id),status text NOT NULL CHECK(status IN ('INCLUDED','EXCLUDED','QUARANTINE')),decision jsonb NOT NULL CHECK(decision->>'truck_access'='UNKNOWN' AND decision->>'independently_verified'='false'));\nCOPY automotive_decisions FROM STDIN WITH(FORMAT csv);\n")
    writer = csv.writer(out, lineterminator='\n')
    writer.writerows(auto.execute('SELECT id,status,decision FROM ways ORDER BY id'))
    auto.close()
    out.write("\\.\nCREATE VIEW automotive_segments AS SELECT s.* FROM segments s JOIN automotive_decisions d ON d.way_id=s.way_id WHERE d.status='INCLUDED';\n")
    for status, count in summary['segment_counts'].items():
        if status not in ('INCLUDED','EXCLUDED','QUARANTINE'):
            raise ValueError('Invalid status')
        out.write(f"DO $$ BEGIN IF (SELECT count(*) FROM segments s JOIN automotive_decisions d ON d.way_id=s.way_id WHERE d.status='{status}')<>{int(count)} THEN RAISE EXCEPTION 'derived partition mismatch'; END IF; END $$;\n")
    out.write("DO $$ BEGIN IF (SELECT count(*) FROM automotive_decisions)<>(SELECT count(*) FROM ways) THEN RAISE EXCEPTION 'way partition incomplete'; END IF; END $$;\n")
    for direction, count in summary['automotive_directions'].items():
        if direction not in ('unknown','forward','reverse','both'):
            raise ValueError('Invalid direction')
        out.write(f"DO $$ BEGIN IF (SELECT count(*) FROM automotive_segments WHERE direction='{direction}')<>{int(count)} THEN RAISE EXCEPTION 'derived direction mismatch'; END IF; END $$;\n")
    out.write("CREATE TABLE evidence_queue(type text,id bigint,record jsonb NOT NULL CHECK(record->>'status'='QUARANTINE' AND record->>'navigation_eligible'='false'),PRIMARY KEY(type,id),FOREIGN KEY(type,id) REFERENCES candidates(type,id));\nCOPY evidence_queue FROM STDIN WITH(FORMAT csv);\n")
    n = 0
    with (audit/'truck-evidence/candidates.jsonl').open() as f:
        for line in f:
            record = json.loads(line)
            writer.writerow((record['osm']['type'], record['osm']['id'], line.strip()))
            n += 1
    out.write("\\.\n")
    out.write(f"DO $$ BEGIN IF (SELECT count(*) FROM evidence_queue)<>{n} OR (SELECT count(*) FROM evidence_queue)<>(SELECT count(*) FROM candidates) THEN RAISE EXCEPTION 'evidence incomplete'; END IF;\n")
    out.write("IF EXISTS(SELECT FROM evidence_queue e JOIN candidates c USING(type,id) WHERE (e.record->'raw_tags') IS DISTINCT FROM c.tags OR (e.record->'geometry') IS DISTINCT FROM c.geometry OR (e.record->'osm'->>'version')::integer IS DISTINCT FROM c.version OR e.record->'provenance'->>'sha256' IS DISTINCT FROM c.source_sha) THEN RAISE EXCEPTION 'evidence source payload mismatch'; END IF;\n")
    out.write("BEGIN UPDATE evidence_queue SET record=jsonb_set(record,'{status}','\"VERIFIED\"'); RAISE EXCEPTION 'evidence promotion accepted'; EXCEPTION WHEN check_violation THEN NULL; END; END $$;\nSELECT 'AUTOMOTIVE PARTITIONS AND EVIDENCE FULL ROW CHECKS PASS';\n")


def extend(source, audit, output):
    source, output = Path(source), Path(output)
    if output.exists() or source.resolve()==output.resolve():
        raise ValueError('Refuse overwrite')
    found = 0
    with source.open() as original, output.open('w') as dest:
        for line in original:
            if MARKER in line:
                found += 1
                write_checks(dest, Path(audit))
            dest.write(line)
    if found != 1:
        raise ValueError('Expected exactly one acceptance insertion marker')


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('audit');p.add_argument('output')
    a=p.parse_args();extend(a.source,a.audit,a.output)
