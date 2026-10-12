"""Reproducible national research layers; private XLSX and user text never enter public CI."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.stage5.contract import canonical, make_record, sha256
from scripts.stage5.postgis import generate

ROOT=Path(__file__).resolve().parents[2]

# This is the complete producer contract, not a directory scan. Workspace sync
# sidecars are not pipeline outputs; missing declared artifacts remain fatal.
REQUIRED_ARTIFACTS = (
    'barriers/barrier-nodes.jsonl',
    'barriers/node-way-access.jsonl',
    'barriers/summary.json',
    'barriers/way-access.jsonl',
    'connectivity.json',
    'independent.json',
    'research.jsonl',
    'stage5-postgis.sql',
    'synthetic-scenarios.jsonl',
)

def artifact_manifest(directory):
    root=Path(directory)
    result={}
    for name in REQUIRED_ARTIFACTS:
        path=root/name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or nonregular required artifact: '+name)
        result[name]={'sha256':sha256(path),'size_bytes':path.stat().st_size}
    return result

def lines(path):
    with open(path,encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)

def decision(value):
    return value if value in ('TAGGED_DENIED','TAGGED_ALLOWED') else 'UNKNOWN'

def wrap(native, kind, identity, source, geometry=None, synthetic=False):
    reasons=native.get('reasons') or [native.get('reason') or 'unverified_source_research_interpretation_only']
    return make_record(kind,identity,source,native,native,reasons,
                       geometry=geometry,synthetic=synthetic)

def build(graph,pbf,out,manifest):
    from scripts.stage5 import barriers,scenarios,temporal,turns
    out=Path(out)
    if out.exists():
        raise ValueError('Refuse existing output directory; choose new path')
    out.mkdir(parents=True)
    graph=Path(graph).resolve(); pbf=Path(pbf).resolve()
    hashes={'graph':sha256(graph),'pbf':sha256(pbf)}
    m=json.loads(Path(manifest).read_text())
    if hashes['pbf']!=m['sha256']:
        raise ValueError('PBF manifest mismatch')
    source={'source_id':m['source_id'],'source_type':'open_mapping',
            'locator':m.get('download_url') or m.get('url') or 'israel-and-palestine-261008.osm.pbf',
            'retrieved_at':m.get('retrieved_at'),'sha256':hashes['pbf']}
    barrier_summary=barriers.build(pbf,graph,out/'barriers',manifest)
    counts=Counter();statuses=Counter();interpretations=Counter();sources=Counter()
    node_rules=[];way_rules=[];temporal_records=[]
    with (out/'research.jsonl').open('w',encoding='utf-8') as dest:
        def emit(row):
            dest.write(canonical(row)+'\n');counts[row['kind']]+=1
            statuses[row['status']]+=1;sources[row['source']['source_id']]+=1
            interpretations[str(row['interpretation'].get('parse_status','NOT_APPLICABLE'))]+=1
        for native in lines(out/'barriers/barrier-nodes.jsonl'):
            emit(wrap(native,'barrier',f"node:{native['object_id']}",source,native.get('geometry')))
            node_rules.append({'id':native['object_id'],'decision':decision(native['decision']['interpretation']),'direction':'both'})
        for native in lines(out/'barriers/way-access.jsonl'):
            emit(wrap(native,'transport_rule',f"way:{native['object_id']}",source))
            for direction,result in native['decisions'].items():
                way_rules.append({'id':native['object_id'],'decision':decision(result['interpretation']),'direction':direction})
        for native in lines(out/'barriers/node-way-access.jsonl'):
            emit(wrap(native,'transport_rule',f"incidence:{native['node_id']}:{native['way_id']}:{native['way_node_position']}",source))
        db=sqlite3.connect(graph.as_uri()+'?mode=ro',uri=True)
        try:
            for native in temporal.iter_temporal_records(db,source):
                temporal_records.append(native)
                identity=f"conditional:{native['object_type']}:{native['object_id']}:{native['tag_key']}"
                emit(wrap(native,'conditional',identity,source))
            for native in turns.iter_turn_records(db,source):
                emit(wrap(native,'turn',f"turn:{native['object_id']}",source))
        finally:
            db.close()
    synthetic_source={'source_id':'synthetic-stage5-scenarios','source_type':'synthetic',
                      'locator':'scripts/stage5/scenarios.py','retrieved_at':None,'sha256':None}
    with (out/'synthetic-scenarios.jsonl').open('w',encoding='utf-8') as dest:
        for native in scenarios.synthetic_scenarios()+scenarios.temporal_turn_scenarios():
            dest.write(canonical(wrap(native,'scenario','synthetic:'+native['id'],synthetic_source,synthetic=True))+'\n')
    connectivity=scenarios.analyze_connectivity(graph,out/'connectivity.json',node_rules=node_rules,way_rules=way_rules,temporal_records=temporal_records)
    from scripts.stage5.independent_audit import audit_file, audit_barrier_sources, audit_temporal_sources
    independent = {'envelope':audit_file(out/'research.jsonl',{source['source_id']:hashes['pbf']}),
                   'synthetic_envelope':audit_file(out/'synthetic-scenarios.jsonl'),
                   'source_reconciliation':audit_barrier_sources(pbf,graph,out/'barriers'),
                   'temporal_source_reconciliation':audit_temporal_sources(graph,
                     (r['raw'] for r in lines(out/'research.jsonl') if r['kind']=='conditional'),
                     (r['raw'] for r in lines(out/'research.jsonl') if r['kind']=='turn'))}
    (out/'independent.json').write_text(json.dumps(independent,sort_keys=True,indent=2)+'\n')
    imported=generate(out/'research.jsonl',out/'stage5-postgis.sql')
    if sha256(graph)!=hashes['graph'] or sha256(pbf)!=hashes['pbf']:
        raise ValueError('Source changed')
    summary={'schema_version':'stage5.summary.v1','navigation_eligible':False,
             'input_sha256':hashes,'source_preserved':True,'record_count':imported,
             'kind_counts':dict(sorted(counts.items())),
             'evidence_status_counts':{'VERIFIED':0,'QUARANTINE':statuses['QUARANTINE'],'UNKNOWN':statuses['UNKNOWN']},
             'source_counts':dict(sorted(sources.items())),
             'parse_status_counts':dict(sorted(interpretations.items())),
             'count_unit':'Research records, including node-way incidences and one record per conditional tag; not unique restrictions',
             'synthetic_records_separate':True,
             'blocked':{'private_bridge_workbook':'Not published or read by public CI; private normalization reviewed separately',
                        'user_time_restriction_text':'Exact original not supplied to this pipeline; no reconstruction',
                        'official_current_verification':'No evidence promotion; VERIFIED remains zero',
                        'national_turn_routing':'Via-way rules require history-expanded graph; actual small synthetic history-state scenarios only, no national turn routing'},
             'outputs':artifact_manifest(out)}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    return summary

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('graph');parser.add_argument('pbf');parser.add_argument('output')
    parser.add_argument('--manifest',default=str(ROOT/'data/stage4/national-source-manifest.json'))
    parser.add_argument('--repeat',action='store_true')
    args=parser.parse_args()
    result=build(args.graph,args.pbf,args.output,args.manifest)
    if args.repeat:
        repeated=build(args.graph,args.pbf,args.output+'-repeat',args.manifest)
        if result!=repeated:
            raise ValueError('Exact replay summary or artifact hash mismatch')
        print('STAGE5_EXACT_REPLAY_PASS',flush=True)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))

if __name__=='__main__':main()
