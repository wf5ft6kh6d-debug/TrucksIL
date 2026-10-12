"""Synthetic fixtures only; no private bridge values."""
import copy
import unittest
import json
import hashlib
import tempfile
from pathlib import Path
from scripts.stage6.bridge_gaps import build_registry, DIMENSIONS
from scripts.stage7.bridge_review import assess, process


def fixture():
    return {'record_id':'synthetic:bridge:1','status':'QUARANTINE','navigation_eligible':False,
            'source':{'sha256':'a'*64,'sheet':'synthetic','member':'sheet.xml','row':2},
            'dimensions':{k:{'raw':None,'parsed_decimal':None} for k in DIMENSIONS}}


class BridgeContinuationTests(unittest.TestCase):
    def test_preserves_unknown_despite_source_level_reading(self):
        r=fixture(); g=build_registry([r])['records']; result=assess([r],g)[0]
        self.assertEqual(result['interpretation_status'],'UNKNOWN')
        self.assertEqual(result['current_evidence'],[])
        self.assertFalse(result['navigation_eligible'])
        self.assertEqual(result['external_row_check'],'NOT_RUN')
    def test_modified_provenance_rejected(self):
        r=fixture(); g=build_registry([r])['records'];g[0]['source']['row']=99
        with self.assertRaises(ValueError): assess([r],g)
    def test_closed_gap_rejected(self):
        r=fixture();g=build_registry([r])['records'];g[0]['evidence_gaps'][0]['status']='VERIFIED'
        with self.assertRaises(ValueError): assess([r],g)
    def test_missing_or_duplicate_gap_rejected(self):
        r=fixture();g=build_registry([r])['records']
        for gaps in ([],g+copy.deepcopy(g)):
            with self.assertRaises(ValueError): assess([r],gaps)
    def test_structural_height_not_clearance(self):
        r=fixture();r['dimensions']['pier_height']={'raw':'syntheticvalue','parsed_decimal':None}
        result=assess([r],build_registry([r])['records'])[0]
        self.assertEqual(result['priority_reason'],'PIER_ONLY_NOT_CLEARANCE')
        self.assertEqual(result['unit_status'],'UNKNOWN')
    def test_stable_no_mutation(self):
        r=fixture();g=build_registry([r])['records'];before=copy.deepcopy((r,g))
        self.assertEqual(assess([r],g),assess([r],g));self.assertEqual((r,g),before)


class BridgeProcessTests(unittest.TestCase):
    def fixture_dirs(self, root):
        a=root/'accepted';s=root/'stage6';a.mkdir();s.mkdir()
        r=fixture();r['record_id']='xlsx:'+r['source']['sha256']+':sheet.xml:2'
        for n,v in {'manifest.json':{'sha256':'a'*64},'summary.json':{'record_count':1}}.items():
            (a/n).write_text(json.dumps(v))
        (a/'records.jsonl').write_text(json.dumps(r)+'\n')
        result=build_registry([r])
        (s/'bridge-evidence-gaps.jsonl').write_text(json.dumps(result['records'][0])+'\n')
        (s/'summary.json').write_text(json.dumps(result['summary']))
        (s/'source-research.json').write_text(json.dumps({'records':[]}))
        (s/'manifest.json').write_text(json.dumps({'input_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.iterdir()}}))
        return a,s
    def test_exact_repeat_and_preserved_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a,s=self.fixture_dirs(root)
            before={p:p.read_bytes() for d in (a,s) for p in d.iterdir()}
            process(a,s,root/'one');process(a,s,root/'two')
            for p in (root/'one').iterdir():self.assertEqual(p.read_bytes(),(root/'two'/p.name).read_bytes())
            self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))
    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a,s=self.fixture_dirs(root)
            (a/'records.jsonl').write_text((a/'records.jsonl').read_text()+'\n')
            with self.assertRaises(ValueError):process(a,s,root/'out')
            self.assertFalse((root/'out').exists())
    def test_overwrite_source_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a,s=self.fixture_dirs(root)
            with self.assertRaises(ValueError):process(a,s,s)
