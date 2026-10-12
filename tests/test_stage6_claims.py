"""SYNTHETIC claim fixtures only. No private message content or real road rules."""
import copy
import unittest
from scripts.stage6.claims import build_registry,validate_registry,public_summary

class SyntheticClaimTests(unittest.TestCase):
    def setUp(self):
        self.text='SYNTHETIC דרך X 07:00-08:00 🚚'
        self.source={'source_id':'synthetic','locator':'synthetic://fixture','original_date':'2026-01-01','received_date':'2026-01-02','testimony':{'confirmed_by_user':True}}
        start=self.text.index('07:00')
        self.spec=[{'claim_id':'synthetic-1','span':[0,len(self.text)],'field_spans':{'times':[[start,start+11]]}}]
        self.r=build_registry(self.text,self.spec,self.source)
    def test_verbatim_unicode(self): self.assertEqual(self.r['claims'][0]['raw_text'],self.text)
    def test_no_days_inference(self): self.assertIsNone(self.r['claims'][0]['fields']['days'])
    def test_no_mass_inference(self): self.assertIsNone(self.r['claims'][0]['fields']['mass'])
    def test_testimony_not_official(self): self.assertFalse(self.r['source']['independent_official_evidence'])
    def test_no_promotion(self):
        self.r['claims'][0]['status']='VERIFIED'
        with self.assertRaises(ValueError):validate_registry(self.r)
    def test_no_navigation(self):
        self.r['claims'][0]['navigation_eligible']=True
        with self.assertRaises(ValueError):validate_registry(self.r)
    def test_tamper_original(self):
        self.r['original_text']+='!'
        with self.assertRaises(ValueError):validate_registry(self.r)
    def test_tamper_span(self):
        self.r['claims'][0]['span'][1]-=1
        with self.assertRaises(ValueError):validate_registry(self.r)
    def test_duplicate(self):
        with self.assertRaises(ValueError):build_registry(self.text,self.spec*2,self.source)
    def test_field_outside_claim(self):
        self.spec[0]['span']=[0,3]
        with self.assertRaises(ValueError):build_registry(self.text,self.spec,self.source)
    def test_summary_no_private_text_or_locator(self):
        s=str(public_summary(self.r));self.assertNotIn(self.text,s);self.assertNotIn('synthetic://',s)
    def test_missing_inventory_tamper(self):
        self.r['claims'][0]['missing_fields']=[]
        with self.assertRaises(ValueError):validate_registry(self.r)
    def test_no_input_mutation(self):
        self.assertNotIn('sha256',self.source);self.assertNotIn('status',self.spec[0])
    def test_no_evidence_promotion(self):
        self.r['claims'][0]['independent_official_verification']='PASS'
        with self.assertRaises(ValueError):validate_registry(self.r)
    def test_empty_span(self):
        self.spec[0]['span']=[0,0]
        with self.assertRaises(ValueError):build_registry(self.text,self.spec,self.source)
    def test_bool_offset(self):
        self.spec[0]['span']=[False,2]
        with self.assertRaises(ValueError):build_registry(self.text,self.spec,self.source)

if __name__=='__main__':unittest.main()
