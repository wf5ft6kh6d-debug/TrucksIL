import tempfile
import unittest
from pathlib import Path
from scripts.stage8.postgis import generate
from test_stage8_contract import review,source
class ReviewSqlTests(unittest.TestCase):
    def test_full_payload_transaction_and_dimensions_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'gate.sql';generate([review()],{'synthetic-source':source()},out);text=out.read_text()
            for value in ['STAGE8_POSTGIS_PASS','trucksil_stage8_test_','ROLLBACK;','source provenance mismatch','conflicting identity replay','operational_change','currentness_status','geobinding_status','rights_status','CREATE INDEX records_geom_gist','immutable_source','invalid dimension accepted']:self.assertIn(value,text)
            self.assertNotIn('trucksil_stage6_test',text)
    def test_public_gate_rejects_private_before_sql(self):
        row=review();row['rights_status']='PRIVATE'
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):generate([row],{'synthetic-source':source()},Path(td)/'gate')
    def test_private_sql_is_explicit(self):
        row=review();row['rights_status']='PRIVATE'
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'gate';generate([row],{'synthetic-source':source()},out,public=False);self.assertNotIn('private review in public import',out.read_text())
    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'gate';out.write_text('keep')
            with self.assertRaises(ValueError):generate([review()],{'synthetic-source':source()},out)
            self.assertEqual(out.read_text(),'keep')

    def test_mirrored_statuses_cannot_diverge(self):
        row=review();row['evidence_status']='UNKNOWN'
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'gate';generate([row],{'synthetic-source':source()},out);text=out.read_text()
            self.assertIn('"status":"UNKNOWN"',text)
            self.assertIn("r->>'evidence_status'=NEW.status",text)
            self.assertIn("r->'interpretation_status'=NEW.payload->'interpretation'->'interpretation_status'",text)
            self.assertIn('divergent evidence copy accepted',text)
            self.assertIn('divergent interpretation copy accepted',text)
