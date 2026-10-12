import unittest
from scripts.stage6.contract import make_record,validate_record

class ResearchContractTests(unittest.TestCase):
    def record(self):
        return make_record('route_scenario','synthetic:route',
            dict(source_id='synthetic-stage6',source_type='synthetic',locator='unit synthetic fixture',sha256=None,retrieved_at=None),
            {'scope':'synthetic'},{'status':'ADMISSIBILITY_UNDETERMINED'},['unknown access'],synthetic=True)

    def test_interpretation_does_not_promote_evidence(self):
        row=self.record();row['interpretation']['status']='RESEARCH_PATH_FOUND'
        validate_record(row)
        self.assertEqual(row['status'],'QUARANTINE');self.assertFalse(row['navigation_eligible'])

    def test_closed_status_and_navigation(self):
        for key,value in [('status','VERIFIED'),('navigation_eligible',True),('schema_version','stage5.research.v1')]:
            with self.subTest(key=key):
                row=self.record();row[key]=value
                with self.assertRaises(Exception):validate_record(row)

    def test_private_and_synthetic_provenance_not_interchangeable(self):
        row=self.record();row['source']['source_type']='user_report'
        with self.assertRaises(Exception):validate_record(row)
        row=self.record();row['synthetic']=False
        with self.assertRaises(Exception):validate_record(row)

    def test_explicit_raw_reason_and_source_required(self):
        for key in ('raw','reasons','source'):
            row=self.record();del row[key]
            with self.assertRaises(Exception):validate_record(row)

    def test_invalid_geometry_rejected(self):
        for geometry in [{'type':'Point','coordinates':[181,0]}, {'type':'LineString','coordinates':[[1,1]]}, {'type':'Point','coordinates':[True,2]}]:
            row=self.record();row['geometry']=geometry
            with self.assertRaises(ValueError):validate_record(row)

    def test_nan_and_naive_timestamp_rejected(self):
        row=self.record();row['raw']['v']=float('nan')
        with self.assertRaises(ValueError):validate_record(row)
        row=self.record();row['source']['retrieved_at']='2026-10-12T07:00:00'
        with self.assertRaises(Exception):validate_record(row)

    def test_additional_keys_and_json_null_rejected(self):
        row=self.record();row['unexpected']=True
        with self.assertRaises(Exception):validate_record(row)
        for key in ('raw','interpretation','reasons','source'):
            row=self.record();row[key]=None
            with self.assertRaises(Exception):validate_record(row)

    def test_independent_schema_corpus(self):
        from scripts.stage6.contract import compare_schema_engines
        result=compare_schema_engines()
        self.assertEqual(result['mismatches'],0)
        self.assertGreater(result['comparisons'],30)

    def test_manifest_has_explicit_complete_inventory(self):
        import tempfile
        from pathlib import Path
        from scripts.stage6.run_research import artifact_manifest,REQUIRED_ARTIFACTS
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in REQUIRED_ARTIFACTS:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic test')
            expected=artifact_manifest(root)
            (root/'.sync-sidecar.tmp').write_text('synthetic sidecar')
            self.assertEqual(artifact_manifest(root),expected)
            (root/'research.jsonl').unlink()
            with self.assertRaises(ValueError):artifact_manifest(root)
