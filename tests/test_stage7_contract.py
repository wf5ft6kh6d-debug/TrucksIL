"""Synthetic contract fixtures; never road evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from scripts.stage7.contract import validate_record,validate_source
from scripts.stage7.run_research import collect,run

def source():
    return dict(source_id='synthetic-test',url='https://example.invalid/test',locator='synthetic test only',checked_at='2026-10-12',document_date=None,rights='synthetic fixture',source_status='TEST_ONLY')
def record():
    return dict(schema_version='stage7.restriction.v1',id='synthetic-test',restriction_type='test_only',scope='LOCAL',geometry=None,location=dict(description='synthetic fixture',road_refs=[],region='UNKNOWN',direction=None,lane=None),vehicle_conditions={},value=dict(amount=None,unit=None,mass_basis=None),validity=dict(effective_from=None,effective_to=None,days=[],hours=[],exceptions=[],last_checked='2026-10-12'),sources=['synthetic-test'],evidence_status='QUARANTINE',interpretation_status='UNKNOWN',unknown_reasons=['Synthetic unit-test fixture, not road evidence'],explanation='Synthetic contract test',independent_review=None,synthetic=False,navigation_eligible=False)
class ContractTests(unittest.TestCase):
    def test_unresolved_record_valid(self):validate_record(record(),{'synthetic-test':source()})
    def test_source_date(self):
        s=source();s['checked_at']='2026-99-99'
        with self.assertRaises(ValueError):validate_source(s)
    def test_unknown_requires_reason(self):
        r=record();r['unknown_reasons']=[]
        with self.assertRaises(ValueError):validate_record(r)
    def test_navigation_forbidden(self):
        r=record();r['navigation_eligible']=True
        with self.assertRaises(Exception):validate_record(r)
    def test_unregistered_source(self):
        with self.assertRaises(ValueError):validate_record(record(),{})
    def test_verified_without_review(self):
        r=record();r['evidence_status']='VERIFIED'
        with self.assertRaises(ValueError):validate_record(r)
    def test_invalid_geometry(self):
        r=record();r['geometry']={'type':'Point','coordinates':[34,100]}
        with self.assertRaises(ValueError):validate_record(r)
    def test_null_geometry_not_permission(self):
        r=validate_record(record());self.assertFalse(r['navigation_eligible']);self.assertEqual(r['interpretation_status'],'UNKNOWN')
    def test_extra_envelope_field_rejected(self):
        r=record();r['allow']=True
        with self.assertRaises(Exception):validate_record(r)
    def test_duplicate_source_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'sources-x.json').write_text(json.dumps({'sources':[source(),source()]}))
            with self.assertRaises(ValueError):collect(d)
    def test_self_signed_verified_rejected_by_runner(self):
        r=record();r.update(evidence_status='VERIFIED',interpretation_status='SUPPORTED',unknown_reasons=[],independent_review=dict(reviewer='self',reviewed_at='2026-10-12',criteria=['test'],evidence_ids=['synthetic-test'],decision='PASS'))
        with tempfile.TemporaryDirectory() as d:
            Path(d,'sources-x.json').write_text(json.dumps({'sources':[source()]}));Path(d,'records-x.json').write_text(json.dumps({'records':[r]}))
            with self.assertRaises(ValueError):collect(d)
    def test_replay_no_input_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);inp=p/'inputs';inp.mkdir();sp=inp/'sources-x.json';rp=inp/'records-x.json'
            sp.write_text(json.dumps({'sources':[source()]}));rp.write_text(json.dumps({'records':[record()]}));before=rp.read_bytes()
            run(inp,p/'a');run(inp,p/'b')
            self.assertEqual(before,rp.read_bytes());self.assertEqual({x.name:x.read_bytes() for x in (p/'a').iterdir()},{x.name:x.read_bytes() for x in (p/'b').iterdir()})
if __name__=='__main__':unittest.main()
