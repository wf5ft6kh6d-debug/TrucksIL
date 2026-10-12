"""SYNTHETIC inputs only; no private original or live-road rule fixture."""
import copy
import unittest
from scripts.stage6.claims import build_registry
from scripts.stage7.temporal_gaps import build_gaps, public_summary

class TemporalGapTests(unittest.TestCase):
    def setUp(self):
        self.registry=build_registry('SYNTHETIC road', [{'claim_id':'test','span':[0,14]}],
            {'source_id':'synthetic','locator':'https://example.invalid/test','original_date':'2026-01-01','received_date':'2026-01-01','testimony':{}})
        self.sources=[{'source_id':'official-test'}]
        self.reviews={'test':{'source_ids':['official-test'],'assessment':'SOURCE_BLOCKED','reason':'SYNTHETIC unavailable'}}
    def build(self):
        return build_gaps(self.registry,self.reviews,self.sources,'2026-10-12')
    def test_immutable_original(self):
        before=copy.deepcopy(self.registry);out=self.build()
        self.assertEqual(before,self.registry)
        self.assertEqual(out['records'][0]['original_claim'],before['claims'][0])
        out['records'][0]['original_claim']['fields']['days']='changed'
        self.assertEqual(before,self.registry)
    def test_every_claim_reviewed(self):
        self.reviews={}
        with self.assertRaises(ValueError):self.build()
    def test_extra_claim_rejected(self):
        self.reviews['extra']=self.reviews['test']
        with self.assertRaises(ValueError):self.build()
    def test_source_link_required(self):
        self.reviews['test']['source_ids']=['missing']
        with self.assertRaises(ValueError):self.build()
    def test_duplicate_source_rejected(self):
        self.sources*=2
        with self.assertRaises(ValueError):self.build()
    def test_status_override_rejected(self):
        self.reviews['test']['evidence_status']='VERIFIED'
        with self.assertRaises(ValueError):self.build()
    def test_no_permission_inference(self):
        self.reviews['test']['source_ids']=[]
        self.reviews['test']['assessment']='NO_CURRENT_PRIMARY_FOUND'
        out=self.build()['records'][0]
        self.assertFalse(out['navigation_eligible']);self.assertEqual(out['interpretation_status'],'UNKNOWN')
    def test_public_allowlist(self):
        out=public_summary(self.build())
        self.assertNotIn('SYNTHETIC',str(out));self.assertNotIn('example.invalid',str(out));self.assertEqual(out['status_counts']['VERIFIED'],0)
    def test_corrupt_source_rejected(self):
        self.registry['original_text']='changed'
        with self.assertRaises(ValueError):self.build()
    def test_export_escalation_rejected(self):
        out=self.build();out['records'][0]['evidence_status']='VERIFIED'
        with self.assertRaises(ValueError):public_summary(out)
    def test_explicit_reason_required(self):
        self.reviews['test']['reason']=''
        with self.assertRaises(ValueError):self.build()
    def test_date_validated(self):
        with self.assertRaises(ValueError):build_gaps(self.registry,self.reviews,self.sources,'not-date')
