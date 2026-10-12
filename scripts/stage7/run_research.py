"""Offline deterministic public evidence integration; never imports private XLSX."""
import argparse
import csv
import hashlib
import json
import sys
import urllib.parse
from collections import Counter
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.stage7.contract import canonical, sha256, validate_record, validate_source
from scripts.stage7.postgis import generate

def collect(directory, review_path=None):
    directory=Path(directory);sources={};records={};blockers=[];inputs={}
    for path in sorted(directory.glob('sources-*.json')):
        inputs[path.name]=sha256(path)
        for source in json.loads(path.read_text())['sources']:
            validate_source(source)
            key=source['source_id']
            if key in sources:raise ValueError('Duplicate source identity: '+key)
            sources[key]=source
    reviews={}
    if review_path:
        review_path=Path(review_path);inputs['individual-review:'+review_path.name]=sha256(review_path)
        reviews=json.loads(review_path.read_text())
    for path in sorted(directory.glob('records-*.json')):
        inputs[path.name]=sha256(path);payload=json.loads(path.read_text())
        blockers.extend(payload.get('blockers',[]))
        for row in payload['records']:
            validate_record(row,sources)
            key=row['id']
            if key in records:raise ValueError('Duplicate record identity: '+key)
            if row['evidence_status']=='VERIFIED':
                review=reviews.get(key,{})
                digest=hashlib.sha256(canonical(row).encode()).hexdigest()
                if review.get('record_sha256')!=digest or review.get('decision')!='PASS' or not all(review.get(k) for k in ('reviewer','reviewed_at','criteria')):
                    raise ValueError('VERIFIED lacks independent individual exact-record audit: '+key)
            records[key]=row
    if not records:raise ValueError('No actual evidence records; do not substitute synthetic data')
    return sources,records,blockers,inputs

def run(directory, output, review_path=None, graph_path=None):
    sources,records,blockers,inputs=collect(directory,review_path)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    ordered=[records[k] for k in sorted(records)]
    def write(name,value):
        (output/name).write_text(canonical(value)+'\n',encoding='utf-8')
    (output/'records.jsonl').write_text(''.join(canonical(r)+'\n' for r in ordered),encoding='utf-8')
    write('sources.json',[sources[k] for k in sorted(sources)])
    write('blockers.json',blockers)
    with (output/'records.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['id','restriction_type','scope','evidence_status','interpretation_status','navigation_eligible','location','vehicle_conditions','value','validity','sources','unknown_reasons','geometry','explanation']
        writer=csv.DictWriter(f,fields);writer.writeheader()
        for r in ordered:writer.writerow({k:canonical(r[k]) if isinstance(r[k],(dict,list)) or r[k] is None else r[k] for k in fields})
    generate(ordered,sources,output/'stage7-postgis.sql')
    from scripts.stage7.coverage import build_coverage,write_outputs
    attempts=[]
    for path in sorted(Path(directory).glob('sources-*.json')):
        attempts.extend(json.loads(path.read_text()).get('search_attempts',[]))
    write_outputs(build_coverage(list(sources.values()),ordered,graph_path,attempts),output)
    summary={'schema_version':'stage7.acceptance.v1','records':len(records),'sources':len(sources),'unique_source_urls':len({s['url'] for s in sources.values()}),'unique_decoded_source_urls':len({urllib.parse.unquote(s['url']) for s in sources.values()}),'record_scopes':dict(sorted(Counter(r['scope'] for r in ordered).items())),'evidence_status':{k:sum(r['evidence_status']==k for r in ordered) for k in ('VERIFIED','QUARANTINE','UNKNOWN')},'interpretation_status':dict(sorted(Counter(r['interpretation_status'] for r in ordered).items())),'navigation_eligible':False,'completeness':'UNKNOWN','source_inputs_sha256':inputs,'private_historical_rows_imported':0,'runtime_warning_block_changes':False}
    write('summary.json',summary)
    manifest={p.name:{'sha256':sha256(p),'bytes':p.stat().st_size} for p in sorted(output.iterdir())}
    write('manifest.json',manifest)
    # Check sources after processing; no transformation may write into input registry.
    _,_,_,after=collect(directory,review_path)
    if after!=inputs:raise ValueError('Input changed during integration')
    return summary

def main():
    p=argparse.ArgumentParser();p.add_argument('input_directory');p.add_argument('output');p.add_argument('--repeat',action='store_true');p.add_argument('--reviews');p.add_argument('--graph');args=p.parse_args()
    summary=run(args.input_directory,args.output,args.reviews,args.graph)
    if args.repeat:
        second=str(args.output)+'-repeat';other=run(args.input_directory,second,args.reviews,args.graph)
        first_files={x.name:x.read_bytes() for x in Path(args.output).iterdir()}
        second_files={x.name:x.read_bytes() for x in Path(second).iterdir()}
        if summary!=other or first_files!=second_files:raise ValueError('Exact replay mismatch')
        print('STAGE7_EXACT_REPLAY_PASS')
    print(canonical(summary))
if __name__=='__main__':main()
