"""Offline diagnostics; supplementary objects never enter normalized graph or SQL."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from osm_pilot import load_snapshot,normalize
from pilot_graph_audit import supplement,audit
from build_pilot import sql_plan


def main():
    p,m=load_snapshot('data/stage3/osm-haifa-20261010');g=normalize(p,m)
    e,_=supplement('data/stage3/osm-members-20261010',p,m);r=audit(p,m,g,e)
    golden={k:r[k] for k in ('summary','missing_reference_report','conflicts')}
    golden['turn_classification']=[{'id':t['id'],'reason':t['reason']} for t in r['turns']]
    expected=Path('data/stage3/osm-members-20261010/expected-audit.json')
    if '--write-expected' in sys.argv:
        expected.write_text(json.dumps(golden,ensure_ascii=False,indent=2)+'\n')
    else:
        assert golden==json.loads(expected.read_text()),'Graph audit changed'
        out=Path(sys.argv[1]);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
        # Independent SQL aggregate of the original frozen graph, within its guarded transaction.
        s=r['summary']
        check=f"""DO $$ BEGIN
 IF (SELECT count(*) FROM (SELECT n FROM
    (SELECT from_node AS n FROM road_segments UNION ALL SELECT to_node FROM road_segments) edges
    GROUP BY n HAVING count(*)=1) leaves)<>{s['degree_one_nodes']} THEN
  RAISE EXCEPTION 'Graph degree mismatch'; END IF;
 IF (SELECT sum(CASE direction WHEN 'both' THEN 2 WHEN 'unknown' THEN 0 ELSE 1 END)
    FROM road_segments)<>{s['explicit_direction_arcs']} THEN RAISE EXCEPTION 'Graph arc mismatch'; END IF;
 IF (SELECT count(*) FROM road_segments WHERE direction='unknown')<>{s['direction_counts'].get('unknown',0)} THEN
  RAISE EXCEPTION 'Unknown directions changed'; END IF;
END $$;
\\echo 'Independent SQL degree/direction checks PASS'
"""
        sql=sql_plan(g,m)
        assert sql.count('ROLLBACK;')==1
        out.with_suffix('.sql').write_text(sql.replace('ROLLBACK;',check+'ROLLBACK;'))
    print(json.dumps(r['summary'],ensure_ascii=False))

if __name__=='__main__':main()
