import copy
import unittest
from scripts.stage5.contract import make_record, validate_record, canonical

class ContractTests(unittest.TestCase):
    def fixture(self):
        return make_record('barrier','node:1',dict(source_id='synthetic-fixture',source_type='synthetic',locator='unit fixture',retrieved_at=None,sha256=None),{'barrier':'gate'},{'decision':'UNKNOWN'},['synthetic gate'],synthetic=True)
    def test_valid_unknown(self):
        self.assertEqual(validate_record(self.fixture())['status'],'QUARANTINE')
    def test_reject_verified(self):
        r=self.fixture();r['status']='VERIFIED'
        with self.assertRaises(Exception):validate_record(r)
    def test_reject_navigation(self):
        r=self.fixture();r['navigation_eligible']=True
        with self.assertRaises(Exception):validate_record(r)
    def test_require_raw_and_reasons(self):
        for key in ('raw','source','reasons'):
            r=self.fixture();del r[key]
            with self.assertRaises(Exception):validate_record(r)
    def test_synthetic_cannot_masquerade(self):
        r=self.fixture();r['synthetic']=False
        with self.assertRaises(Exception):validate_record(r)
    def test_real_cannot_masquerade_as_synthetic(self):
        r=self.fixture();r['source']['source_type']='open_mapping'
        with self.assertRaises(Exception):validate_record(r)
    def test_nonfinite_rejected(self):
        r=self.fixture();r['raw']['value']=float('nan')
        with self.assertRaises(ValueError):validate_record(r)
    def test_timestamp_requires_timezone(self):
        r=self.fixture();r['source']['retrieved_at']='2026-01-01'
        with self.assertRaises(Exception):validate_record(r)
