"""Independent bounded full-walk oracle. Does not reuse production routing logic."""
from collections import defaultdict, deque
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE=ZoneInfo('Asia/Jerusalem')


def fixture_cases():
    return json.loads((Path(__file__).resolve().parents[2]/'tests/fixtures/stage6/routing-cases.json').read_text())


def _active(condition, instant):
    if condition is None: return True
    if condition.get('parse_status')!='SUPPORTED' or instant is None: return None
    local=instant.astimezone(ZONE)
    if local.replace(fold=0).utcoffset()!=local.replace(fold=1).utcoffset(): return None
    minute=local.hour*60+local.minute+local.second/60+local.microsecond/60000000
    start,end=condition['start_minute'],condition['end_minute']
    if start<end: return local.weekday() in condition['days'] and start<=minute<end
    return (local.weekday() in condition['days'] and minute>=start or
            (local.weekday()-1)%7 in condition['days'] and minute<end)


def _run_history(path):
    """Reconstruct every run from complete path; no production suffix state."""
    runs=[]
    previous=None
    for edge in path:
        reverse=previous is not None and previous['from']==edge['to'] and previous['to']==edge['from']
        if not runs or runs[-1][0]!=edge['way_id']:
            runs.append((edge['way_id'],edge['from']))
        previous=edge
    return runs


def _transition(path,edge,rules,instant):
    runs=_run_history(path)
    unknown=False
    previous=path[-1] if path else None
    reversal=previous is not None and previous['from']==edge['to'] and previous['to']==edge['from']
    continuation=bool(runs and runs[-1][0]==edge['way_id'] and not reversal)
    for raw in rules:
        seq=raw.get('sequence',raw.get('chain_way_ids',[]))
        joins=raw.get('connection_nodes',raw.get('connection_node_ids',[]))
        kind=raw.get('kind',{'NO_SEQUENCE':'no','ONLY_SEQUENCE':'only'}.get(raw.get('semantics')))
        exc=raw.get('except',[])
        if isinstance(exc,str):exc=exc.split(';')
        valid=(raw.get('parse_status')=='SUPPORTED' and len(seq)>=2 and len(joins)==len(seq)-1 and kind in ('no','only')
               and all(e in {'hgv','motor_vehicle','vehicle','motorcar','bus','bicycle','taxi','psv','emergency','motorcycle'} for e in exc)
               and not (len(seq)>2 and any(a==b for a,b in zip(seq,seq[1:]))))
        if not valid:
            if not seq or edge['way_id'] in seq or (runs and runs[-1][0] in seq):unknown=True
            continue
        if set(exc)&{'hgv','vehicle','motor_vehicle'}:continue
        violated=False
        for k in range(1,len(seq)):
            if len(runs)<k:continue
            suffix=runs[-k:]
            if [r[0] for r in suffix]!=list(seq[:k]) or [r[1] for r in suffix[1:]]!=list(joins[:k-1]):continue
            at_junction=edge['from']==joins[k-1]
            correct=not continuation and edge['way_id']==seq[k] and at_junction
            if kind=='no':
                violated |= k==len(seq)-1 and correct
            elif k==1:
                violated |= at_junction and not correct
            else:
                violated |= not (continuation or correct) or (at_junction and not correct)
        if violated:
            condition=raw.get('conditional')
            key=raw.get('selected_key')
            if key and key in raw.get('raw',{}).get('tags',{}):condition=None
            active=_active(condition,instant)
            if active is True:return False,unknown
            if active is None:unknown=True
    return True,unknown


def reference_route(edges,start,goal,rules,departure,max_depth=12,max_walks=50000):
    """Enumerate full walks; bounded failure is INCONCLUSIVE, never no-route.

    Definitive no-route requires exhausting all walks without truncation; cyclic
    negative cases generally remain inconclusive, unlike the finite-state router.
    """
    adjacency=defaultdict(list)
    for edge in edges:adjacency[edge['from']].append(edge)
    aware=isinstance(departure,dt.datetime) and departure.tzinfo is not None and departure.utcoffset() is not None
    imaginary=aware and departure.tzinfo==ZONE and departure.astimezone(dt.timezone.utc).astimezone(ZONE).replace(tzinfo=None)!=departure.replace(tzinfo=None)
    instant=departure.astimezone(dt.timezone.utc) if aware and not imaginary else None
    queue=deque([(start,[],instant,instant is None)])
    visited=0;truncated=False;uncertain_path=None
    while queue:
        node,path,time,unknown=queue.popleft();visited+=1
        if visited>max_walks:return dict(status='REFERENCE_INCONCLUSIVE',walks=visited,reason='oracle_walk_budget')
        if node==goal:
            if not unknown:return dict(status='REFERENCE_PATH_FOUND',walks=visited,edge_ids=[x['id'] for x in path])
            uncertain_path=[x['id'] for x in path]
            continue
        if len(path)>=max_depth:
            if adjacency.get(node):truncated=True
            continue
        for edge in adjacency.get(node,[]):
            if edge.get('direction_status')=='BLOCKED' or edge.get('admissibility')=='DENIED':continue
            permitted,uncertain=_transition(path,edge,rules,time)
            if not permitted:continue
            duration=edge.get('duration_seconds')
            valid=isinstance(duration,(int,float)) and not isinstance(duration,bool) and duration>0
            next_time=time+dt.timedelta(seconds=duration) if time is not None and valid else None
            tainted=unknown or uncertain or edge.get('direction_status')!='KNOWN' or edge.get('admissibility')!='KNOWN' or not valid
            queue.append((edge['to'],path+[edge],next_time,tainted))
    if truncated:return dict(status='REFERENCE_INCONCLUSIVE',walks=visited,reason='oracle_depth_budget')
    if uncertain_path is not None:return dict(status='REFERENCE_UNKNOWN',walks=visited,edge_ids=uncertain_path)
    return dict(status='REFERENCE_NO_ROUTE',walks=visited,edge_ids=[])


def validate_cases():
    from scripts.stage6.routing import research_route
    outcomes=[]
    expected_map={'REFERENCE_PATH_FOUND':'RESEARCH_PATH_FOUND','REFERENCE_UNKNOWN':'ADMISSIBILITY_UNDETERMINED','REFERENCE_NO_ROUTE':'NO_ROUTE'}
    for case in fixture_cases():
        stamp=dt.datetime.fromisoformat(case['departure']).replace(tzinfo=ZONE)
        reference=reference_route(case['edges'],case['start'],case['goal'],case['rules'],stamp,max_depth=case.get('oracle_depth',12))
        actual=research_route(case['edges'],case['start'],case['goal'],case['rules'],stamp,limits=case.get('limits'))
        actual={k:v for k,v in actual.items() if k!='runtime_seconds'}
        expected=case['expected']
        oracle_expected=expected_map.get(reference['status'])
        comparison=(actual['status']==expected and (case.get('resource_exhaustion') or oracle_expected==actual['status']))
        outcomes.append(dict(id=case['id'],synthetic=True,navigation_eligible=False,status='PASS' if comparison else 'FAIL',expected=expected,reference=reference,actual=actual))
    return dict(status='PASS' if all(x['status']=='PASS' for x in outcomes) else 'FAIL',
                synthetic=True,navigation_eligible=False,case_count=len(outcomes),cases=outcomes,
                oracle='Independent exhaustive full-walk enumeration; no production transition/state functions reused',
                limitations=['Negative cyclic oracle cases require exhaustion; truncation remains inconclusive.','Synthetic fixtures do not establish real restrictions.'])


if __name__=='__main__':
    print(json.dumps(validate_cases(),ensure_ascii=False,sort_keys=True,indent=2))
