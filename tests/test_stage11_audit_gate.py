"""Synthetic regression fixtures only: no real road fact or audit evidence."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.stage11 import audit_gate as m

class GraphAuditGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='trucksil-synthetic-audit-')
        self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name);self.root=self.source/'review'
        self.files={
          'graph_archive':self.source/'recovery/graph-archive/TrucksIL-national-research-261008.zip',
          'graph_candidates':self.source/'recovery/stage10/stage10-private/geometry/graph-candidates.jsonl',
          'passage_review':self.root/'geometry/passage-binding-review.csv',
          'audit_checker':self.root/'audit/check_graph.py'}
        payloads={'graph_archive':b'SYNTHETIC_NOT_A_GRAPH_ARCHIVE',
          'graph_candidates':b''.join((json.dumps({'record_id':f'SYNTHETIC-{i}'})+'\n').encode() for i in range(2431)),
          'passage_review':('record_id\n'+''.join(f'SYNTHETIC-{i}\n' for i in range(2431))).encode(),
          'audit_checker':b'# SYNTHETIC CHECKER FIXTURE NOT EXECUTED\n'}
        for k,p in self.files.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(payloads[k])
        self.archive_hash=m.digest(self.files['graph_archive'])
        self.expected_patch=patch.object(m,'EXPECTED_ARCHIVE',self.archive_hash);self.expected_patch.start();self.addCleanup(self.expected_patch.stop)
        self.report={'schema_version':1,'status':'PASS_EXACT_ID_SQL_SCOPE','method':'INDEPENDENT_FRESH_TEMP_EXTRACTION_IMMUTABLE_SQL',
          'sqlite_integrity_check_before':'PASS','sqlite_integrity_check_after':'PASS','sqlite_integrity_check':'PASS','reference_check':'PASS_2431_EXACT_REFERENCES','failures':[],'records_checked':2431,'csv_records_checked':2431,
          'distance_recalculation':'NOT_RUN_NO_NEW_GEOMETRY_ALGORITHM','db_bytes':m.EXPECTED_DB_BYTES,
          'db_sha256_before':m.EXPECTED_DB,'db_sha256_after':m.EXPECTED_DB,'archive_sha256':self.archive_hash,
          'inputs':{k:{'bytes':p.stat().st_size,'sha256':m.digest(p)} for k,p in self.files.items()}}
        self.report['db_bytes_after']=m.EXPECTED_DB_BYTES;self.report['inputs_after']=copy.deepcopy(self.report['inputs'])
        self.report_path=self.root/'audit/graph-checks.json';self.save()
    def save(self):
        self.report['inputs_after']=copy.deepcopy(self.report['inputs'])
        self.report_path.write_text(json.dumps(self.report))
    def validate(self):return m.validate_graph_audit(self.root,self.source)
    def test_valid_current_report_passes(self):self.assertEqual(self.validate()['status'],'PASS')
    def test_missing_report_blocks(self):
        self.report_path.unlink();self.assertEqual(self.validate()['status'],'BLOCKED')
    def test_failed_report_fails(self):
        self.report['status']='FAIL';self.save();self.assertEqual(self.validate()['status'],'FAIL')
    def test_legacy_report_blocks(self):
        del self.report['schema_version'];self.save();self.assertEqual(self.validate()['status'],'BLOCKED')
    def test_malformed_and_nonobject_report_fail(self):
        for value in ('{','[]','null'):
            self.report_path.write_text(value);self.assertEqual(self.validate()['status'],'FAIL')
    def test_stale_every_bound_input_blocks(self):
        for name,p in self.files.items():
            with self.subTest(name=name):
                original=p.read_bytes();p.write_bytes(original+b'X')
                self.assertEqual(self.validate()['reason'],'STALE_AUDIT_INPUT:'+name)
                p.write_bytes(original)
    def test_invalid_counts_fail(self):
        for key in ('records_checked','csv_records_checked'):
            for value in (2430,2432,True,'2431',None):
                with self.subTest(key=key,value=value):
                    self.report[key]=value;self.save();self.assertEqual(self.validate()['status'],'FAIL')
            self.report[key]=2431
    def test_invalid_hash_and_metadata_fail(self):
        original=copy.deepcopy(self.report)
        for change in ({'bytes':True,'sha256':'f'*64},{'bytes':1,'sha256':'bad'}, {'bytes':-1,'sha256':'f'*64}):
            self.report=copy.deepcopy(original);self.report['inputs']['passage_review']=change;self.save()
            self.assertEqual(self.validate()['status'],'FAIL')
    def test_input_unavailable_blocks(self):
        self.files['graph_candidates'].unlink();self.assertEqual(self.validate()['status'],'BLOCKED')
    def test_fresh_hash_does_not_hide_wrong_row_count(self):
        p=self.files['passage_review'];p.write_text('record_id\nSYNTHETIC-0\n')
        self.report['inputs']['passage_review']={'bytes':p.stat().st_size,'sha256':m.digest(p)};self.save()
        self.assertEqual(self.validate()['reason'],'CURRENT_INPUT_COUNT_MISMATCH')
    def test_audit_failures_cannot_pass(self):
        self.report['failures']=['SYNTHETIC_FAILURE'];self.save();self.assertEqual(self.validate()['status'],'FAIL')
    def test_wrong_database_digest_fails(self):
        self.report['db_sha256_after']='0'*64;self.save();self.assertEqual(self.validate()['status'],'FAIL')
    def test_missing_audit_directory_blocks(self):
        shutil.rmtree(self.root/'audit') # disposable synthetic fixture only
        self.assertEqual(self.validate()['status'],'BLOCKED')


    def test_integrity_reference_absent_vs_failed(self):
        original=copy.deepcopy(self.report)
        for key in ('sqlite_integrity_check','sqlite_integrity_check_before','sqlite_integrity_check_after','reference_check'):
            with self.subTest(field=key,outcome='missing'):
                self.report=copy.deepcopy(original);del self.report[key];self.save()
                self.assertEqual(self.validate()['status'],'BLOCKED')
            with self.subTest(field=key,outcome='failed'):
                self.report[key]='FAIL';self.save();self.assertEqual(self.validate()['status'],'FAIL')


    def test_after_audit_metadata_missing_or_invalid(self):
        original=copy.deepcopy(self.report)
        cases=[('db_bytes_after',None,'BLOCKED'),('db_bytes_after',1,'FAIL'),('inputs_after',None,'BLOCKED'),('inputs_after',{},'FAIL')]
        for field,value,status in cases:
            with self.subTest(field=field,value=value):
                self.report=copy.deepcopy(original)
                if value is None:del self.report[field]
                else:self.report[field]=value
                self.report_path.write_text(json.dumps(self.report))
                self.assertEqual(self.validate()['status'],status)


class TechnicalAcceptanceTests(unittest.TestCase):
    def checks(self):return {k:{'status':'PASS','reason':'SYNTHETIC'} for k in ('tables','graph','temporal')}
    def test_pass_does_not_require_verified(self):
        result=m.technical_acceptance(self.checks())
        self.assertEqual(result['exit_code'],0);self.assertEqual(result['status'],'PASS');self.assertFalse(result['road_verification_required'])
    def test_failed_or_blocked_check_cannot_exit_zero(self):
        for key in self.checks():
            for status,code in [('FAIL',1),('BLOCKED',2),('UNKNOWN',1),('PASS_FROM_HISTORY',1)]:
                checks=self.checks();checks[key]['status']=status
                self.assertEqual(m.technical_acceptance(checks)['exit_code'],code)
    def test_missing_checks_fail(self):
        self.assertEqual(m.technical_acceptance({})['exit_code'],1)
    def test_status_not_truthiness(self):
        checks=self.checks();checks['graph']['status']=True
        self.assertEqual(m.technical_acceptance(checks)['status'],'FAIL')

class AutomationConsumerTests(unittest.TestCase):
    def test_cli_status_and_exit_normal_and_optimized(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory(prefix='synthetic-summary-') as tmp:
            path=Path(tmp)/'summary.json'
            for optimize in (False,True):
                for state,code in [('PASS',0),('BLOCKED',2),('FAIL',1)]:
                    checks={key:{'status':'PASS','reason':'SYNTHETIC'} for key in ('tables','graph','temporal')}
                    checks['graph']['status']=state
                    acceptance=m.technical_acceptance(checks)
                    path.write_text(json.dumps({'status':state,'technical_acceptance':acceptance}))
                    command=[sys.executable]+(['-O'] if optimize else [])+[m.__file__,'--summary',str(path)]
                    process=subprocess.run(command,capture_output=True,text=True)
                    self.assertEqual(process.returncode,code,process.stderr)
                    self.assertEqual(json.loads(process.stdout)['status'],state)
    def test_stale_top_level_pass_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'summary.json';checks={key:{'status':'BLOCKED','reason':'SYNTHETIC'} for key in ('tables','graph','temporal')}
            path.write_text(json.dumps({'status':'PASS','technical_acceptance':m.technical_acceptance(checks)}))
            self.assertEqual(m.consume_summary(path)['exit_code'],1)
    def test_missing_and_invalid_reports_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'summary.json'
            self.assertEqual(m.consume_summary(path)['exit_code'],1)
            for text in ('{','null','[]','{}'):
                path.write_text(text);self.assertEqual(m.consume_summary(path)['exit_code'],1)

class MalformedAcceptanceTests(unittest.TestCase):
    def test_non_object_checks_and_missing_reasons_rejected(self):
        for checks in (None,[],True,{'tables':{},'graph':{},'temporal':{}}):
            self.assertEqual(m.technical_acceptance(checks)['exit_code'],1)
    def test_consumer_missing_reasons_or_wrong_exit_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'summary.json'
            checks={key:{'status':'PASS','reason':'SYNTHETIC'} for key in ('tables','graph','temporal')}
            for field in ('reasons','exit_code'):
                result=m.technical_acceptance(checks);del result[field]
                path.write_text(json.dumps({'status':'PASS','technical_acceptance':result}))
                self.assertEqual(m.consume_summary(path)['exit_code'],1)

if __name__=='__main__':unittest.main(verbosity=2)
