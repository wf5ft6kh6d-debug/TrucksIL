"""Bounded experiments on actual OSM segments; no national navigation promise."""
from collections import Counter, defaultdict
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.stage4.automotive_graph import classify
from scripts.stage5.barriers import classify_access, combine_access, relevant
from scripts.stage5.turns import analyze_turn

MAX_CASES=12
MAX_SEGMENTS=3000
MAX_ALTERNATIVE_WAYS=8
WORKER_MEMORY_BYTES=512*1024*1024
WORKER_TIMEOUT_SECONDS=300
ROUTE_LIMITS={'max_states':20000,'max_expansions':50000,'max_input_edges':6000,
              'max_rules':1000,'max_rule_length':64,'max_memory_bytes':64*1024*1024,
              'max_runtime_seconds':10.0}


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def measurement_decision(raw, value, unit):
    """Research numeric limit only, explicit units, equality unresolved margin."""
    try:
        v=Decimal(str(value))
        if not v.is_finite() or v<=0:raise ValueError
    except (InvalidOperation,ValueError):return 'UNKNOWN','invalid_vehicle_measurement'
    if not isinstance(raw,str):return 'UNKNOWN','missing_measurement_evidence'
    match=re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*'+re.escape(unit)+r'\s*',raw)
    if not match:return 'UNKNOWN','unsupported_or_implicit_units'
    limit=Decimal(match[1])
    if limit<=0:return 'UNKNOWN','invalid_limit'
    if v>limit:return 'DENIED','numeric_limit_exceeded'
    if v==limit:return 'UNKNOWN','equal_limit_no_margin'
    return 'KNOWN','numeric_fit_only_unverified'


def profile_admissibility(tags,profile,direction='forward',node_tags=()):
    """Explicit uncertainty of source access/height/mass; not VERIFIED evidence."""
    access=classify_access(tags,direction=direction)
    for n in node_tags:
        if relevant(n):access=combine_access(classify_access(n,is_node=True),access)
    decisions=[];reasons=[access['reason']]
    mapped={'TAGGED_ALLOWED':'KNOWN','TAGGED_DENIED':'DENIED'}
    decisions.append(mapped.get(access['interpretation'],'UNKNOWN'))
    for key,vehicle_key,unit in [('maxheight','height_m','m'),('maxweight','mass_t','t')]:
        decision,reason=measurement_decision(tags.get(key),profile.get(vehicle_key),unit)
        if any(k.startswith(key+':') for k in tags):
            decision='UNKNOWN';reason='unsupported_scoped_or_conflicting_source'
        decisions.append(decision);reasons.append(key+':'+reason)
    # An explicit obstruction is sufficient to reject a research candidate;
    # mixed positive/negative source access already becomes UNKNOWN upstream.
    status='DENIED' if 'DENIED' in decisions else 'UNKNOWN' if 'UNKNOWN' in decisions else 'KNOWN'
    return dict(admissibility=status,reasons=sorted(set(reasons)),navigation_eligible=False,
                evidence_status='QUARANTINE',source_tags=dict(tags))


def _record_relation(db,row,source):
    rid,tags,members,missing=row
    members=json.loads(members)
    ways={}
    for member in members:
        if member['type'] not in ('w','way'):continue
        result=db.execute('SELECT nodes,tags FROM ways WHERE id=?',(member['id'],)).fetchone()
        if result:ways[member['id']]=dict(nodes=json.loads(result[0]),tags=json.loads(result[1]))
    result=analyze_turn(json.loads(tags),members,ways,source)
    result.update(object_id=rid,source_relation_id=rid)
    if json.loads(missing):result.update(parse_status='UNKNOWN',reasons=result['reasons']+['source_missing_reference'])
    return result


def _select_corridors(db,source):
    rows=list(db.execute('SELECT id,tags,members,missing_refs FROM relations ORDER BY id'))
    from_index=defaultdict(list)
    for row in rows:
        for m in json.loads(row[2]):
            if m.get('role')=='from' and m.get('type') in ('w','way'):from_index[m['id']].append(row)
    cache={};selected=[];counts=Counter();skips=Counter()
    def interpret(row):
        if row[0] not in cache:cache[row[0]]=_record_relation(db,row,source)
        return cache[row[0]]
    for row in rows:
        raw=json.loads(row[1]);members=json.loads(row[2])
        via=any(m.get('role')=='via' and m.get('type') in ('w','way') for m in members)
        bucket='via_way' if via else 'only_node' if raw.get('restriction','').startswith('only_') else 'no_node'
        if counts[bucket]>=4:continue
        rule=interpret(row)
        if rule['parse_status']!='SUPPORTED':skips['unsupported_candidate']+=1;continue
        chain=rule['chain_way_ids'];joins=rule['connection_node_ids'];way_ids=set(chain)
        way_data={}
        for wid in chain:
            rec=db.execute('SELECT tags,nodes FROM ways WHERE id=?',(wid,)).fetchone()
            tags=json.loads(rec[0])
            if classify(tags)['status']!='INCLUDED':break
            way_data[wid]=dict(tags=tags,nodes=json.loads(rec[1]))
        if len(way_data)!=len(chain):skips['chain_not_in_stage4_included']+=1;continue
        alternative_ids=set()
        for node in joins:
            for a,b in [('a','b'),('b','a')]:
                for wid, in db.execute('SELECT DISTINCT way_id FROM segments WHERE '+a+'=? ORDER BY way_id',(node,)):
                    if wid not in way_ids:alternative_ids.add(wid)
        alternatives=[];omitted=0
        for wid in sorted(alternative_ids):
            rec=db.execute('SELECT tags,nodes FROM ways WHERE id=?',(wid,)).fetchone()
            tags=json.loads(rec[0])
            if classify(tags)['status']!='INCLUDED':continue
            if len(alternatives)>=MAX_ALTERNATIVE_WAYS:omitted+=1;continue
            alternatives.append(wid);way_data[wid]=dict(tags=tags,nodes=json.loads(rec[1]))
        segments=[]
        for wid in sorted(way_data):
            segments.extend(db.execute('SELECT id,way_id,seq,a,b,direction,length_m FROM segments WHERE way_id=? ORDER BY seq,id',(wid,)))
            if len(segments)>MAX_SEGMENTS:break
        if len(segments)>MAX_SEGMENTS:skips['corridor_segment_limit']+=1;continue
        arcs=[]
        for sid,wid,seq,a,b,direction,length in segments:
            permitted=[]
            if direction in ('forward','both'):permitted.append((a,b,'forward','KNOWN'))
            if direction in ('reverse','both'):permitted.append((b,a,'backward','KNOWN'))
            if direction=='unknown':permitted=[(a,b,'forward','UNKNOWN'),(b,a,'backward','UNKNOWN')]
            for u,v,relative,certainty in permitted:
                arcs.append(dict(id=f'{sid}:{relative}',source_segment_id=sid,source_seq=seq,
                                 **{'from':u,'to':v},way_id=wid,direction_status=certainty,
                                 duration_seconds=1,admissibility='KNOWN',relative_direction=relative))
        incoming=[e for e in arcs if e['way_id']==chain[0] and e['to']==joins[0] and e['direction_status']=='KNOWN']
        outgoing=[e for e in arcs if e['way_id']==chain[-1] and e['from']==joins[-1] and e['direction_status']=='KNOWN']
        if not incoming or not outgoing:skips['missing_known_entry_exit']+=1;continue
        start=sorted(incoming,key=lambda e:e['id'])[0]['from'];goal=sorted(outgoing,key=lambda e:e['id'])[0]['to']
        if start==goal:skips['coincident_endpoint']+=1;continue
        # Include every relation touching any selected way, including malformed
        # or external from-members; no missing-rule assumption becomes permission.
        corridor_nodes={e[k] for e in arcs for k in ('from','to')}
        relevant_rows={r[0]:r for r in rows if any(
            (m.get('type') in ('w','way') and m['id'] in way_data) or
            (m.get('type') in ('n','node') and m['id'] in corridor_nodes)
            for m in json.loads(r[2])) or not any(m.get('type') in ('w','way','n','node') for m in json.loads(r[2]))}
        rules=[interpret(r) for _,r in sorted(relevant_rows.items())]
        selected.append(dict(id='national-relation-'+str(row[0]),relation_id=row[0],bucket=bucket,
                             rule=rule,rules=rules,way_data=way_data,edges=arcs,start=start,goal=goal,
                             segments=len(segments),omitted_alternative_ways=omitted))
        counts[bucket]+=1
        if len(selected)==MAX_CASES:break
    coverage=dict(node_only_relation_count=sum(not any(m.get('type') in ('w','way') for m in json.loads(r[2])) for r in rows),
                  no_spatial_member_ids=[r[0] for r in rows if not any(m.get('type') in ('w','way','n','node') for m in json.loads(r[2]))],
                  policy='All touching way OR node members included; no-spatial-member rules apply as global UNKNOWN')
    return selected,dict(counts),dict(skips),len(rows),coverage


def _worker(graph,pbf,out):
    import resource
    import osmium
    from scripts.stage6.routing import research_route
    began=time.monotonic()
    out=Path(out)
    graph_hash=sha256(graph);pbf_hash=sha256(pbf)
    manifest=json.loads((Path(__file__).resolve().parents[2]/'data/stage4/national-source-manifest.json').read_text())
    if pbf_hash!=manifest['sha256']:raise ValueError('PBF differs from accepted national source manifest')
    source=dict(source_type='open_mapping',graph_sha256=graph_hash,pbf_sha256=pbf_hash,
                snapshot=manifest['snapshot_at'],status='QUARANTINE')
    db=sqlite3.connect(Path(graph).resolve().as_uri()+'?mode=ro',uri=True)
    db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
    corridors,counts,skips,relation_rows,coverage=_select_corridors(db,source)
    db.close()
    selected_nodes={e[k] for c in corridors for e in c['edges'] for k in ('from','to')}
    node_tags={}
    class Nodes(osmium.SimpleHandler):
        def node(self,node):
            if node.id in selected_nodes:
                tags=dict(node.tags)
                if relevant(tags):node_tags[node.id]=tags
    Nodes().apply_file(str(pbf),locations=False)
    scenarios=[];status_counts=Counter();profile={'height_m':'4.0','mass_t':'18.0'}
    departure=dt.datetime(2026,10,12,7,0,tzinfo=ZoneInfo('Asia/Jerusalem'))
    output_rows=out/'national-scenarios.jsonl'
    output_rows.touch()
    for c in corridors:
        base=c['edges'];rule_data=c['rules']
        baseline=research_route(base,c['start'],c['goal'],[],departure,limits=ROUTE_LIMITS)
        constrained=research_route(base,c['start'],c['goal'],rule_data,departure,limits=ROUTE_LIMITS)
        profile_edges=[];admission_counts=Counter()
        for edge in base:
            admission=profile_admissibility(c['way_data'][edge['way_id']]['tags'],profile,edge['relative_direction'],
                          [node_tags[n] for n in (edge['from'],edge['to']) if n in node_tags])
            admission_counts[admission['admissibility']]+=1
            profile_edges.append(dict(edge,admissibility=admission['admissibility'],reasons=admission['reasons']))
        profiled=research_route(profile_edges,c['start'],c['goal'],rule_data,departure,limits=ROUTE_LIMITS)
        for result in (baseline,constrained,profiled):
            result.pop('runtime_seconds',None);status_counts[result['status']]+=1
        scenario=dict(id=c['id'],synthetic=False,scenario_assumptions_synthetic=True,navigation_eligible=False,
                      source=source,relation_id=c['relation_id'],sampling_bucket=c['bucket'],
                      start_node=c['start'],goal_node=c['goal'],departure=departure.isoformat(),
                      duration_assumption='Exactly 1 second per source segment; not measured travel time',
                      profile_assumption=profile,profile_mass_semantics='Assumed actual current gross mass in tonnes; not permitted/registered maximum mass',source_segments=c['segments'],directed_arcs=len(base),
                      source_way_ids=sorted(c['way_data']),source_relation_ids=sorted(r['object_id'] for r in rule_data),
                      unsupported_relation_ids=sorted(r['object_id'] for r in rule_data if r['parse_status']!='SUPPORTED'),
                      omitted_alternative_ways=c['omitted_alternative_ways'],profile_edge_decisions=dict(admission_counts),
                      baseline=baseline,turn_constrained=constrained,profile_constrained=profiled,
                      scope='Bounded source-segment corridor only; NO_ROUTE is not a national no-route proof')
        scenarios.append(scenario)
        with output_rows.open('a') as stream:
            stream.write(json.dumps(scenario,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
            stream.flush()
    preserved=sha256(graph)==graph_hash and sha256(pbf)==pbf_hash
    if not preserved:raise ValueError('Original source changed')
    summary=dict(status='PASS' if preserved and len(scenarios)>0 and 'INCOMPLETE' not in status_counts else 'INCOMPLETE',
                 navigation_eligible=False,synthetic=False,verified_restrictions=0,
                 actual_corridors=len(scenarios),sampling_buckets=counts,candidate_skips=skips,
                 scanned_relation_rows=relation_rows,relation_scope_inventory=coverage,source=source,source_preserved=preserved,
                 actual_unique_segments=len({e['source_segment_id'] for c in corridors for e in c['edges']}),
                 selected_source_nodes=len(selected_nodes),tagged_node_records=len(node_tags),
                 route_status_counts=dict(status_counts),scenarios_sha256=sha256(out/'national-scenarios.jsonl'),
                 budgets=dict(max_corridors=MAX_CASES,max_segments_per_corridor=MAX_SEGMENTS,max_alternative_ways=MAX_ALTERNATIVE_WAYS,
                              worker_address_space_bytes=WORKER_MEMORY_BYTES,effective_rlimit_as=list(resource.getrlimit(resource.RLIMIT_AS)),worker_timeout_seconds=WORKER_TIMEOUT_SECONDS,route=ROUTE_LIMITS),
                 limitations=['Not national coverage or routing safety validation.',
                              'Only 12 deterministic relation-centered bounded corridors, not all OD pairs.',
                              'Full referenced ways retained; at most 8 adjacent alternate ways per corridor.',
                              'Routes outside selected corridor not searched; no snapping.',
                              'All OSM evidence remains QUARANTINE; missing access/height/mass is UNKNOWN.',
                              'Explicit-unit m/t numeric subset only; scoped and missing data not inferred.',
                              'Travel durations and profile are synthetic assumptions applied to real source geometry.',
                              'Router memory is conservative retained-object estimate; OS RLIMIT_AS caps whole worker address space.'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print('STAGE6_PERFORMANCE '+json.dumps(dict(elapsed_seconds=round(time.monotonic()-began,6),
           peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)),file=sys.stderr)
    return summary


def run(graph,pbf,out):
    """Hard cap includes extraction and searching; incomplete is never PASS."""
    import resource
    graph,pbf,out=Path(graph).resolve(),Path(pbf).resolve(),Path(out).resolve()
    if out.exists():raise ValueError('Refuse existing national output directory')
    if graph==pbf or not graph.is_file() or not pbf.is_file():raise ValueError('Missing or ambiguous source files')
    out.mkdir(parents=True)
    def cap():
        resource.setrlimit(resource.RLIMIT_AS,(WORKER_MEMORY_BYTES,WORKER_MEMORY_BYTES))
    command=[sys.executable,str(Path(__file__).resolve()),'--worker',str(graph),str(pbf),str(out)]
    try:
        result=subprocess.run(command,preexec_fn=cap,timeout=WORKER_TIMEOUT_SECONDS,capture_output=True,text=True)
        if result.stderr:print(result.stderr,file=sys.stderr,end='')
        if result.returncode==0:return json.loads((out/'summary.json').read_text())
        reason='worker_nonzero_exit';details=result.stderr[-1500:]
    except subprocess.TimeoutExpired:
        reason='worker_wall_time_limit';details='Subprocess killed after fixed extraction+search wall-time budget.'
    rows_path=out/'national-scenarios.jsonl'
    completed=[]
    if rows_path.exists():
        for line in rows_path.read_text().splitlines():
            try: completed.append(json.loads(line))
            except json.JSONDecodeError: break
        rows_path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n' for r in completed))
    summary=dict(status='INCOMPLETE',navigation_eligible=False,synthetic=False,verified_restrictions=0,
                 actual_corridors=len(completed),completed_corridor_ids=[r['id'] for r in completed],
                 reason=reason,worker_timeout_seconds=WORKER_TIMEOUT_SECONDS,
                 worker_address_space_bytes=WORKER_MEMORY_BYTES,
                 details=details)
    (out/'summary.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
    (out/'national-scenarios.jsonl').touch(exist_ok=True)
    return summary


if __name__=='__main__':
    if len(sys.argv)!=5 or sys.argv[1]!='--worker':raise SystemExit('Use run(graph,pbf,out) to enforce resource isolation')
    _worker(*sys.argv[2:])
