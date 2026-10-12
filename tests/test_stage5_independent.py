"""Synthetic tamper cases for independent acceptance; no real road rules."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
spec = importlib.util.spec_from_file_location('stage5_independent', Path(__file__).resolve().parents[1] / 'scripts/stage5/independent_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class IndependentStage5Tests(unittest.TestCase):
    def setUp(self):
        self.row = {'schema_version': 'stage5.research.v1', 'record_id': 'synthetic:1', 'kind': 'synthetic_test', 'source': {'source_id': 'fixture', 'source_type': 'synthetic', 'locator': 'tests:1', 'retrieved_at': None, 'sha256': 'a' * 64}, 'raw': {}, 'interpretation': {}, 'reasons': ['SYNTHETIC_TEST'], 'status': 'UNKNOWN', 'navigation_eligible': False, 'synthetic': True, 'geometry': None}

    def check(self, rows, hashes=None):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'research.jsonl'
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            return audit.audit_file(path, hashes)

    def test_synthetic_valid(self):
        self.assertEqual(self.check([self.row])['records_checked'], 1)

    def test_verified_rejected(self):
        self.row['status'] = 'VERIFIED'
        with self.assertRaisesRegex(ValueError, 'escalation'): self.check([self.row])

    def test_navigation_string_false_rejected(self):
        self.row['navigation_eligible'] = 'false'
        with self.assertRaisesRegex(ValueError, 'navigation'): self.check([self.row])

    def test_duplicate_identity(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.check([self.row, self.row])

    def test_source_tamper(self):
        with self.assertRaisesRegex(ValueError, 'digest mismatch'): self.check([self.row], {'fixture': 'b' * 64})

    def test_synthetic_cannot_be_real(self):
        self.row['synthetic'] = False
        with self.assertRaisesRegex(ValueError, 'mislabeled'): self.check([self.row])

    def test_missing_reason(self):
        self.row['reasons'] = []
        with self.assertRaisesRegex(ValueError, 'reasons'): self.check([self.row])

    def test_no_records_not_pass(self):
        with self.assertRaisesRegex(ValueError, 'empty'): self.check([])

class IndependentTemporalInventory(unittest.TestCase):
    def test_synthetic_original_payload_tamper_rejected(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'synthetic.sqlite'
            db = sqlite3.connect(path)
            db.executescript('CREATE TABLE ways(id INTEGER,tags TEXT,nodes TEXT); CREATE TABLE candidates(id INTEGER,tags TEXT,type TEXT); CREATE TABLE relations(id INTEGER,tags TEXT,members TEXT,missing_refs TEXT);')
            db.execute('INSERT INTO ways VALUES(1,?,?)', (json.dumps({'access:conditional':'no @ (Mo 08:00-09:00)'}), '[1,2]'))
            db.commit(); db.close()
            row = {'object_type':'way','object_id':1,'tag_key':'access:conditional','raw':'yes @ (Mo 08:00-09:00)', 'status':'QUARANTINE','navigation_eligible':False,'parse_status':'UNKNOWN'}
            with self.assertRaisesRegex(ValueError, 'inventory/source mismatch'):
                audit.audit_temporal_sources(path, [row], [])
            row['raw'] = 'no @ (Mo 08:00-09:00)'
            self.assertEqual(audit.audit_temporal_sources(path, [row], [])['conditional_records_checked'], 1)
            with self.assertRaisesRegex(ValueError, 'inventory/source mismatch'):
                audit.audit_temporal_sources(path, [], [])

if __name__ == '__main__': unittest.main()
