"""Stage 6 public research acceptance. No private-document input is accepted."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.stage6.contract import canonical,make_record,sha256,validate_record
from scripts.stage6.postgis import generate

ROOT=Path(__file__).resolve().parents[2]
REQUIRED_ARTIFACTS=(
    'national/national-scenarios.jsonl','national/summary.json',
    'research.jsonl','synthetic-scenarios.jsonl','validation.json',
    'stage6-postgis.sql','stage6-synthetic-postgis.sql',
)

def artifact_manifest(directory):
    root=Path(directory)
    manifest={}
    for name in REQUIRED_ARTIFACTS:
        path=root/name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or nonregular required artifact: '+name)
        manifest[name]={'sha256':sha256(path),'size_bytes':path.stat().st_size}
    return manifest

def rows(path):
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)

def wrap(native,identity,source,synthetic=False):
    reasons=native.get('reasons')
    if not isinstance(reasons,list) or not reasons:
        reasons=['research_interpretation_not_current_official_restriction']
    return make_record('route_scenario',identity,source,native,native,reasons,
                       synthetic=synthetic,geometry=native.get('geometry'))

def envelope_file(native_rows,target,source,synthetic):
    seen=set();counts=Counter()
    with Path(target).open('x',encoding='utf-8') as out:
        for position,native in enumerate(native_rows):
            if native.get('navigation_eligible',False) is not False:
                raise ValueError('Producer escalated navigation eligibility')
            identity=('synthetic:' if synthetic else 'national:')+str(native.get('id',position))
            if identity in seen:
                raise ValueError('Duplicate producer record ID')
            seen.add(identity)
            record=wrap(native,identity,source,synthetic=synthetic)
            validate_record(record)
            out.write(canonical(record)+'\n')
            counts[record['status']]+=1
    if not seen:
        raise ValueError('Empty scenario corpus')
    return {'count':len(seen),'statuses':{'VERIFIED':0,'QUARANTINE':counts['QUARANTINE'],'UNKNOWN':counts['UNKNOWN']}}

def build(graph,pbf,out,manifest):
    from scripts.stage6 import national,validation
    graph=Path(graph).resolve();pbf=Path(pbf).resolve();out=Path(out)
    if out.exists() or out.is_symlink():
        raise ValueError('Refuse existing output directory')
    hashes={'graph':sha256(graph),'pbf':sha256(pbf)}
    source_manifest=json.loads(Path(manifest).read_text())
    if hashes['pbf']!=source_manifest['sha256']:
        raise ValueError('Pinned source PBF mismatch')
    out.mkdir(parents=True)
    national_summary=national.run(graph,pbf,out/'national')
    source=dict(source_id=source_manifest['source_id'],source_type='open_mapping',
                locator=source_manifest['url'],retrieved_at=source_manifest['retrieved_at'],sha256=hashes['pbf'])
    real=envelope_file(rows(out/'national/national-scenarios.jsonl'),out/'research.jsonl',source,False)
    validation_result=validation.validate_cases()
    if validation_result.get('status')!='PASS':
        raise ValueError('Independent scenario comparison failed')
    (out/'validation.json').write_text(json.dumps(validation_result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    synthetic_source=dict(source_id='stage6-synthetic-cases',source_type='synthetic',
                          locator='scripts/stage6/validation.py',retrieved_at=None,sha256=None)
    synthetic=envelope_file(validation_result['cases'],out/'synthetic-scenarios.jsonl',synthetic_source,True)
    generate(out/'research.jsonl',out/'stage6-postgis.sql')
    generate(out/'synthetic-scenarios.jsonl',out/'stage6-synthetic-postgis.sql')
    if hashes!={'graph':sha256(graph),'pbf':sha256(pbf)}:
        raise ValueError('Original inputs changed')
    summary={'schema_version':'stage6.summary.v1','input_sha256':hashes,
             'navigation_eligible':False,'source_preserved':True,
             'real_research_records':real,'synthetic_records':synthetic,
             'private_sources_in_public_ci':False,
             'national_scope':national_summary,
             'outputs':artifact_manifest(out)}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    if national_summary.get('status')!='PASS':
        raise ValueError('National bounded experiment INCOMPLETE; diagnostic artifacts preserved')
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
            raise ValueError('Stage6 exact replay mismatch')
        print('STAGE6_EXACT_REPLAY_PASS',flush=True)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))

if __name__=='__main__':main()
