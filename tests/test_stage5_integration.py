import json
from pathlib import Path
import tempfile
import unittest
from scripts.stage5.contract import make_record,canonical
from scripts.stage5.postgis import generate
from scripts.stage5.run_research import decision,wrap,artifact_manifest,REQUIRED_ARTIFACTS

class IntegrationTests(unittest.TestCase):
    def test_restricted_not_allowed(self):
        self.assertEqual(decision('RESTRICTED'),'UNKNOWN')
        self.assertEqual(decision('UNKNOWN'),'UNKNOWN')
        self.assertEqual(decision('TAGGED_DENIED'),'TAGGED_DENIED')
    def test_raw_and_interpretation_preserved(self):
        source=dict(source_id='synthetic',source_type='synthetic',locator='unit fixture',retrieved_at=None,sha256=None)
        native={'raw':'no @ (Mo-Fr 07:00-09:00)','parse_status':'SUPPORTED','reasons':[]}
        row=wrap(native,'conditional','synthetic:1',source,synthetic=True)
        self.assertEqual(row['raw'],native)
        self.assertEqual(row['status'],'QUARANTINE')
        self.assertFalse(row['navigation_eligible'])
    def test_sql_copy_escaping_and_transaction(self):
        source=dict(source_id='synthetic',source_type='synthetic',locator='unit fixture',retrieved_at=None,sha256=None)
        row=make_record('barrier','synthetic:1',source,{'text':"quote'\t\\\nעברית"},{'decision':'UNKNOWN'},['test'],synthetic=True)
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'rows.jsonl';b=Path(tmp)/'test.sql'
            a.write_text(canonical(row)+'\n');self.assertEqual(generate(a,b),1)
            sql=b.read_text()
            self.assertLess(sql.index('CREATE EXTENSION'),sql.index('geometry(Geometry'))
            self.assertIn('ROLLBACK;',sql)
            self.assertIn('STAGE5_POSTGIS_PASS',sql)
            copied=sql.split('COPY incoming(payload) FROM stdin;\n',1)[1].split('\n\\.\n',1)[0]
            # COPY only introduces escape pairs because all controls were JSON escaped.
            self.assertEqual(json.loads(copied.replace('\\\\','\\')),row)
    def test_sql_rejects_verified_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.jsonl';path.write_text('{"status":"VERIFIED"}\n')
            with self.assertRaises(Exception):generate(path,Path(tmp)/'bad.sql')


class ArtifactManifestTests(unittest.TestCase):
    def populate(self, root):
        for name in REQUIRED_ARTIFACTS:
            path=root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('SYNTHETIC fixture: '+name+'\n')

    def test_manifest_ignores_incidental_sync_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.populate(root)
            before=artifact_manifest(root)
            (root/'.research.jsonl.0TBAVM').write_text('SYNTHETIC transient sync copy')
            (root/'barriers/.way-access.jsonl.sync').write_text('SYNTHETIC sidecar')
            (root/'editor-temporary.tmp').write_text('SYNTHETIC unrelated temporary output')
            self.assertEqual(artifact_manifest(root),before)
            self.assertEqual(set(before),set(REQUIRED_ARTIFACTS))
            self.assertEqual(len(before),9)

    def test_each_missing_required_output_fails(self):
        for name in REQUIRED_ARTIFACTS:
            with self.subTest(artifact=name), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);self.populate(root)
                (root/name).unlink()
                with self.assertRaisesRegex(ValueError,'required artifact'):
                    artifact_manifest(root)

    def test_required_artifact_mutation_changes_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.populate(root)
            before=artifact_manifest(root)
            (root/'research.jsonl').write_text('SYNTHETIC altered content')
            self.assertNotEqual(artifact_manifest(root),before)
