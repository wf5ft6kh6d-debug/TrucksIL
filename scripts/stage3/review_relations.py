"""Reproduce four-object review and topology evidence; does not write navigation data."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from osm_pilot import load_snapshot,normalize
from pilot_graph_audit import supplement
from relation_review import IDS,review_relation,topology_diagnostics,load_current
p,m=load_snapshot('data/stage3/osm-haifa-20261010');o,_=supplement('data/stage3/osm-members-20261010',p,m)
g=normalize(p,m);r={'relations':[review_relation(o['relation',i],o,m['bbox_wgs84']) for i in IDS],'topology':topology_diagnostics(p,m,g)}
folder=Path('data/stage3/osm-review-20261010')
if folder.exists():
 current,cm=load_current(folder)
 def semantic(e):return {k:v for k,v in e.items() if k not in ('user','uid')}
 r['current_comparison']={'snapshot_at':cm['source_snapshot_at'],'sha256':cm['sha256'],'changed_objects':[{'type':t,'id':i} for (t,i),e in sorted(current.items()) if (t,i) not in o or semantic(e)!=semantic(o[t,i])],'objects_compared':len(current)}
else:r['current_comparison']={'status':'blocked_not_acquired'}
projection={'relations':[{k:x[k] for k in ('id','finding','role_counts')} for x in r['relations']], 'topology':r['topology']['summary'],'current_comparison':r['current_comparison']}
expected=Path('data/stage3/osm-review-20261010/expected-review.json')
if '--write-expected' in sys.argv:expected.write_text(json.dumps(projection,indent=2)+'\n')
else:assert projection==json.loads(expected.read_text()),'Review changed'
Path(sys.argv[1]).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'relations':[{k:x[k] for k in ('id','finding','role_counts')} for x in r['relations']],'topology':r['topology']['summary'],'current_comparison':r['current_comparison']},ensure_ascii=False))
