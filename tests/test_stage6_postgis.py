import json
from pathlib import Path
import tempfile
import unittest
from scripts.stage6.contract import make_record,canonical
from scripts.stage6.postgis import generate

class PostgisContractTests(unittest.TestCase):
    def record(self,synthetic=True):
        return make_record('route_scenario','fixture:'+str(synthetic),
            dict(source_id='synthetic' if synthetic else 'open-fixture',source_type='synthetic' if synthetic else 'open_mapping',locator='unit fixture',sha256=None,retrieved_at=None),
            {'text':"quote'\t\\\nעברית"},{'status':'INCOMPLETE'},['bounded fixture'],synthetic=synthetic)

    def test_sql_copy_roundtrip_and_protection_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'in.jsonl';out=root/'out.sql';row=self.record()
            src.write_text(canonical(row)+'\n')
            self.assertEqual(generate(src,out),1)
            sql=out.read_text()
            self.assertLess(sql.index('current_database()'),sql.index('CREATE EXTENSION'))
            self.assertIn("'^trucksil_stage6_test_[a-z0-9_]+$'",sql)
            self.assertIn('inet_server_addr() IS NOT NULL',sql)
            copied=sql.split('COPY incoming(payload) FROM stdin;\n')[1].split('\n\\.\n')[0]
            self.assertEqual(json.loads(copied.replace('\\\\','\\')),row)
            self.assertIn('STAGE6_POSTGIS_PASS',sql)

    def test_source_and_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.jsonl';p.write_text(canonical(self.record())+'\n');original=p.read_bytes()
            with self.assertRaises(ValueError):generate(p,p)
            self.assertEqual(p.read_bytes(),original)
            out=Path(tmp)/'out.sql';out.write_text('existing')
            with self.assertRaises(ValueError):generate(p,out)
            self.assertEqual(out.read_text(),'existing')

    def test_synthetic_real_mixing_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.jsonl';p.write_text(''.join(canonical(self.record(s))+'\n' for s in [True,False]))
            with self.assertRaisesRegex(ValueError,'separate imports'):generate(p,Path(tmp)/'out.sql')

    def test_false_navigation_and_uncertainty_sql_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.jsonl';row=self.record();row['navigation_eligible']=True;p.write_text(json.dumps(row)+'\n')
            with self.assertRaises(Exception):generate(p,Path(tmp)/'out.sql')


    def test_extracted_json_is_grouped_before_key_subtraction(self):
        # Regression for actual PostgreSQL parse failure in run 38214494862.
        # Arithmetic '-' binds more tightly than the JSON extraction operator.
        from scripts.stage6.postgis import HEADER
        self.assertIn("(payload->'geometry') - ARRAY['type','coordinates']",HEADER)
        self.assertIn("(payload->'geometry') ?& ARRAY['type','coordinates']",HEADER)
        self.assertNotRegex(HEADER,r"->\s*'[^']+'\s*[-+*/](?!>)")
