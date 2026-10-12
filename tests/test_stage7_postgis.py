import tempfile
import unittest
from pathlib import Path
from scripts.stage7.postgis import generate
from test_stage7_contract import record,source
class PostgisTests(unittest.TestCase):
    def test_reused_gate_preserves_full_raw_and_stage7_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'acceptance.sql';generate([record()],{'synthetic-test':source()},out);sql=out.read_text()
            for item in ('trucksil_stage7_test_','STAGE7_POSTGIS_PASS','ROLLBACK;','CREATE INDEX records_geom_gist','conflicting identity replay','source provenance mismatch','Synthetic contract test','source_status','GENERAL'):
                if item!='GENERAL':self.assertIn(item,sql)
            self.assertNotIn('trucksil_stage6_test',sql)
    def test_direct_generator_cannot_promote_verified(self):
        r=record();r.update(evidence_status='VERIFIED',interpretation_status='SUPPORTED',unknown_reasons=[],independent_review=dict(reviewer='synthetic',reviewed_at='2026-10-12',criteria=['synthetic'],evidence_ids=['synthetic-test'],decision='PASS'))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):generate([r],{'synthetic-test':source()},Path(d)/'out')
    def test_existing_output_protected(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out';out.write_text('keep')
            with self.assertRaises(ValueError):generate([record()],{'synthetic-test':source()},out)
            self.assertEqual(out.read_text(),'keep')
    def test_empty_real_corpus_not_substituted(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):generate([],{},Path(d)/'out')
