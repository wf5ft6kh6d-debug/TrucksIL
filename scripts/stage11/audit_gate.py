"""Fail-closed validation of research graph audit evidence. No routing activation."""
import csv, hashlib, json
from pathlib import Path
EXPECTED_ARCHIVE='958859a8292c77744013a7a028ae1acf4c1366f1b621f8bb1ddfdbe262f0669a'
EXPECTED_DB='fd4d29f0424f9d24b861c00b8ae0f954afb90c2d8af87cc9ff8f575a6aa1440a'
EXPECTED_DB_BYTES=1097547776
GRAPH_SUCCESS='PASS_INDEPENDENT_EXACT_SNAPSHOT_SQL_2431_DISTANCE_RECALCULATION_NOT_RUN'

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def validate_graph_audit(root, source_root):
    """Fail closed; prior PASS text alone is not evidence for current inputs."""
    def result(status,reason):return {'status':status,'reason':reason,'report':'audit/graph-checks.json'}
    report_path=root/'audit/graph-checks.json'
    if not report_path.is_file():return result('BLOCKED','AUDIT_REPORT_UNAVAILABLE')
    try:
        report=json.loads(report_path.read_text(encoding='utf-8'))
        if not isinstance(report,dict):return result('FAIL','MALFORMED_AUDIT_REPORT')
        if report.get('status')!='PASS_EXACT_ID_SQL_SCOPE':return result('FAIL','AUDIT_NOT_SUCCESSFUL')
        if type(report.get('schema_version')) is not int or report['schema_version']!=1:return result('BLOCKED','AUDIT_INPUT_CONTRACT_MISSING_OR_UNSUPPORTED')
        if report.get('failures')!=[]:return result('FAIL','AUDIT_FAILURES_PRESENT_OR_MISSING')
        if report.get('method')!='INDEPENDENT_FRESH_TEMP_EXTRACTION_IMMUTABLE_SQL':return result('FAIL','UNSUPPORTED_AUDIT_METHOD')
        if report.get('sqlite_integrity_check')!='PASS':return result('FAIL','SQLITE_INTEGRITY_NOT_PASSED')
        if report.get('reference_check')!='PASS_2431_EXACT_REFERENCES':return result('FAIL','REFERENCE_CHECK_NOT_PASSED')
        if report.get('distance_recalculation')!='NOT_RUN_NO_NEW_GEOMETRY_ALGORITHM':return result('FAIL','UNSUPPORTED_DISTANCE_SCOPE')
        for key in ('records_checked','csv_records_checked'):
            if type(report.get(key)) is not int or report[key]!=2431:return result('FAIL','INVALID_AUDIT_COUNT:'+key)
        if type(report.get('db_bytes')) is not int or report['db_bytes']!=EXPECTED_DB_BYTES:return result('FAIL','INVALID_DB_SIZE')
        if report.get('db_sha256_before')!=EXPECTED_DB or report.get('db_sha256_after')!=EXPECTED_DB:return result('FAIL','INVALID_DB_DIGEST')
        inputs=report.get('inputs')
        paths={'graph_archive':source_root/'recovery/graph-archive/TrucksIL-national-research-261008.zip',
               'graph_candidates':source_root/'recovery/stage10/stage10-private/geometry/graph-candidates.jsonl',
               'passage_review':root/'geometry/passage-binding-review.csv',
               'audit_checker':root/'audit/check_graph.py'}
        if not isinstance(inputs,dict) or set(inputs)!=set(paths):return result('BLOCKED','AUDIT_INPUT_BINDINGS_MISSING')
        for name,path in paths.items():
            meta=inputs[name]
            if not isinstance(meta,dict) or type(meta.get('bytes')) is not int or meta['bytes']<0:return result('FAIL','INVALID_INPUT_METADATA:'+name)
            sha=meta.get('sha256')
            if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):return result('FAIL','INVALID_INPUT_DIGEST:'+name)
            if not path.is_file():return result('BLOCKED','AUDIT_INPUT_UNAVAILABLE:'+name)
            if path.stat().st_size!=meta['bytes'] or digest(path)!=sha:return result('BLOCKED','STALE_AUDIT_INPUT:'+name)
        if inputs['graph_archive']['sha256']!=EXPECTED_ARCHIVE or report.get('archive_sha256')!=EXPECTED_ARCHIVE:return result('FAIL','UNEXPECTED_GRAPH_ARCHIVE')
        with paths['passage_review'].open(encoding='utf-8-sig',newline='') as f:
            csv_count=sum(1 for _ in csv.DictReader(f))
        with paths['graph_candidates'].open(encoding='utf-8') as f:
            source_records=[json.loads(line) for line in f if line.strip()]
        if csv_count!=2431 or len(source_records)!=2431:return result('FAIL','CURRENT_INPUT_COUNT_MISMATCH')
        return result('PASS','CURRENT_INPUT_HASHES_AND_AUDIT_SCOPE_VALIDATED')
    except (ValueError,TypeError,KeyError,UnicodeError,OSError,csv.Error) as e:
        return result('FAIL','INVALID_OR_UNREADABLE_AUDIT:'+type(e).__name__)

def technical_acceptance(checks):
    """Integration scope only; VERIFIED is deliberately not an acceptance input."""
    required={'tables','graph','temporal'}
    if not isinstance(checks,dict) or set(checks)!=required:
        return {'status':'FAIL','exit_code':1,'reasons':['REQUIRED_CHECKS_MISSING_OR_UNEXPECTED'],'checks':checks}
    if any(not isinstance(v,dict) or not isinstance(v.get('reason'),str) or not v['reason'] for v in checks.values()):
        return {'status':'FAIL','exit_code':1,'reasons':['CHECK_REASON_MISSING_OR_INVALID'],'checks':checks}
    statuses=[v.get('status') if isinstance(v,dict) else None for v in checks.values()]
    status='PASS' if all(x=='PASS' for x in statuses) else ('BLOCKED' if all(x in ('PASS','BLOCKED') for x in statuses) else 'FAIL')
    return {'status':status,'exit_code':{'PASS':0,'FAIL':1,'BLOCKED':2}[status],
            'reasons':[k+':'+str(v.get('reason','CHECK_NOT_PASSED')) for k,v in checks.items() if isinstance(v,dict) and v.get('status')!='PASS'],
            'checks':checks,'scope':'REVIEW_TABLE_COUNTS_CURRENT_BOUND_GRAPH_AUDIT_TEMPORAL_RESTORATION',
            'road_verification_required':False,'ci_and_release_acceptance':'SEPARATE_NOT_INFERRED'}

def consume_summary(path):
    """Automation protocol guard; not an independent re-audit of the source files."""
    try:
        summary=json.loads(Path(path).read_text(encoding='utf-8'))
        supplied=summary['technical_acceptance']
        result=technical_acceptance(supplied['checks'])
        if summary.get('status')!=result['status'] or supplied.get('status')!=result['status'] or type(supplied.get('exit_code')) is not int or supplied['exit_code']!=result['exit_code'] or supplied.get('reasons')!=result['reasons']:
            return {'status':'FAIL','exit_code':1,'reasons':['SUMMARY_STATUS_INCONSISTENT']}
        return result
    except (OSError,UnicodeError,ValueError,TypeError,KeyError,AttributeError) as e:
        return {'status':'FAIL','exit_code':1,'reasons':['SUMMARY_READ_OR_SCHEMA_ERROR:'+type(e).__name__]}

if __name__=='__main__':
    import argparse
    import sys
    parser=argparse.ArgumentParser(description='Read explicit technical integration status; never infer road validity.')
    parser.add_argument('--summary',required=True,type=Path)
    result=consume_summary(parser.parse_args().summary)
    print(json.dumps(result))
    sys.exit(result['exit_code'])
