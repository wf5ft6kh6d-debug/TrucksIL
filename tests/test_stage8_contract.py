"""Synthetic contract fixtures only; never actual restrictions."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from scripts.stage8.contract import validate_review
from scripts.stage8.run_review import collect, run

def source():
    return dict(source_id='synthetic-source',url='https://example.invalid/synthetic',locator='synthetic fixture',checked_at='2026-10-12',document_date=None,rights='synthetic fixture',source_status='SYNTHETIC')
def review():
    return dict(schema_version='stage8.review.v1',id='synthetic-review',subject_id='synthetic-subject',review_kind='NORM',finding='Synthetic contract fixture, not a road fact',evidence_status='QUARANTINE',interpretation_status='UNKNOWN',currentness_status='UNKNOWN',geobinding_status='NOT_APPLICABLE',rights_status='PUBLIC_METADATA_ONLY',unknown_reasons=['Synthetic fixture'],sources=['synthetic-source'],checked_at='2026-10-12',navigation_eligible=False,operational_change=False)
class ReviewTests(unittest.TestCase):
    def test_valid_dimensions_independent(self):
        row=review();row.update(interpretation_status='SUPPORTED',currentness_status='CURRENT');self.assertEqual(validate_review(row)['evidence_status'],'QUARANTINE')
    def test_no_verified_promotion(self):
        row=review();row['evidence_status']='VERIFIED'
        with self.assertRaises(Exception):validate_review(row)
    def test_private_not_public(self):
        row=review();row['rights_status']='PRIVATE';validate_review(row,public=False)
        with self.assertRaises(ValueError):validate_review(row,public=True)
    def test_rights_unknown_not_public(self):
        row=review();row['rights_status']='UNKNOWN'
        with self.assertRaises(ValueError):validate_review(row,public=True)
    def test_unknown_requires_reason(self):
        row=review();row['unknown_reasons']=[]
        with self.assertRaises(Exception):validate_review(row)
    def test_missing_source_rejected(self):
        with self.assertRaises(ValueError):validate_review(review(),{})
    def test_no_policy_or_navigation_activation(self):
        for key in ['navigation_eligible','operational_change']:
            row=review();row[key]=True
            with self.assertRaises(Exception):validate_review(row)
    def test_date_and_extra_fields_rejected(self):
        for patch in [{'checked_at':'2026-02-30'},{'raw_private_excerpt':'not permitted'}]:
            row=review();row.update(patch)
            with self.assertRaises(Exception):validate_review(row)
    def test_replay_and_input_immutability(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)/'input';d.mkdir();(d/'sources-fixture.json').write_text(json.dumps({'sources':[source()]}));(d/'reviews-fixture.json').write_text(json.dumps({'reviews':[review()]}))
            before={p.name:p.read_bytes() for p in d.iterdir()}
            left=Path(td)/'left';right=Path(td)/'right';self.assertEqual(run(d,left),run(d,right))
            self.assertEqual({p.name:p.read_bytes() for p in left.iterdir()},{p.name:p.read_bytes() for p in right.iterdir()});self.assertEqual(before,{p.name:p.read_bytes() for p in d.iterdir()})
    def test_duplicate_review_id_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/'sources-fixture.json').write_text(json.dumps({'sources':[source()]}));(d/'reviews-fixture.json').write_text(json.dumps({'reviews':[review(),review()]}))
            with self.assertRaises(ValueError):collect(d)
    def test_no_synthetic_substitution_for_empty_corpus(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):collect(td)
