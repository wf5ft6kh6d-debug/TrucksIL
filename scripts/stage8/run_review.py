"""Deterministic additive annotations; no XLSX import or routing-policy changes."""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.stage8.contract import canonical, sha256, validate_review, validate_source
from scripts.stage8.postgis import generate

def collect(directory, public=True):
    sources={};reviews={};inputs={}
    for path in sorted(Path(directory).glob('sources-*.json')):
        inputs[path.name]=sha256(path)
        for source in json.loads(path.read_text())['sources']:
            validate_source(source)
            sid=source['source_id']
            if sid in sources:raise ValueError('Duplicate source ID: '+sid)
            sources[sid]=source
    for path in sorted(Path(directory).glob('reviews-*.json')):
        inputs[path.name]=sha256(path)
        for row in json.loads(path.read_text())['reviews']:
            validate_review(row,sources,public)
            if row['id'] in reviews:raise ValueError('Duplicate review ID: '+row['id'])
            reviews[row['id']]=row
    appendix=Path(directory)/'integration-appendices.json'
    if appendix.is_file():inputs[appendix.name]=sha256(appendix)
    if not reviews:raise ValueError('No actual review corpus')
    return sources,reviews,inputs

def run(directory, output, public=True):
    sources,reviews,inputs=collect(directory,public)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    rows=[reviews[k] for k in sorted(reviews)]
    def write(name,value):(output/name).write_text(canonical(value)+'\n',encoding='utf-8')
    (output/'reviews.jsonl').write_text(''.join(canonical(row)+'\n' for row in rows),encoding='utf-8')
    write('sources.json',[sources[k] for k in sorted(sources)])
    with (output/'reviews.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,list(rows[0]));writer.writeheader()
        for row in rows:writer.writerow({k:canonical(v) if isinstance(v,list) else v for k,v in row.items()})
    appendix=Path(directory)/'integration-appendices.json'
    if appendix.is_file():
        payload=json.loads(appendix.read_text())
        allowed={'change-ledger.json','owner-questions.json','draft-decisions.json'}
        if set(payload)!=allowed:raise ValueError('Unexpected appendix names')
        for name,value in sorted(payload.items()):write(name,value)
    generate(rows,sources,output/'stage8-postgis.sql',public)
    summary={'schema_version':'stage8.summary.v1','reviews':len(rows),'sources':len(sources),'evidence_status':{s:sum(r['evidence_status']==s for r in rows) for s in ['VERIFIED','QUARANTINE','UNKNOWN']},'dimensions':{key:dict(sorted(Counter(r[key] for r in rows).items())) for key in ['review_kind','interpretation_status','currentness_status','geobinding_status','rights_status']},'navigation_eligible':False,'operational_change':False,'historical_xlsx_rows_imported':0,'public':public,'inputs_sha256':inputs}
    write('summary.json',summary)
    write('manifest.json',{p.name:{'sha256':sha256(p),'bytes':p.stat().st_size} for p in sorted(output.iterdir())})
    if collect(directory,public)[2]!=inputs:raise ValueError('Inputs changed during review')
    return summary

def main():
    p=argparse.ArgumentParser();p.add_argument('input_directory');p.add_argument('output');p.add_argument('--repeat',action='store_true');p.add_argument('--private',action='store_true');args=p.parse_args()
    summary=run(args.input_directory,args.output,not args.private)
    if args.repeat:
        run(args.input_directory,args.output+'-repeat',not args.private)
        left={p.name:p.read_bytes() for p in Path(args.output).iterdir()};right={p.name:p.read_bytes() for p in Path(args.output+'-repeat').iterdir()}
        if left!=right:raise ValueError('Replay mismatch')
        print('STAGE8_EXACT_REPLAY_PASS')
    print(canonical(summary))
if __name__=='__main__':main()
