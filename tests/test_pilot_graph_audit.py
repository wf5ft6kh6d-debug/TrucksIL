"""Frozen real data and explicitly synthetic mutations; never operational evidence."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from osm_pilot import load_snapshot,normalize
from pilot_graph_audit import supplement,audit,components


class GraphAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base,cls.manifest=load_snapshot(ROOT/'data/stage3/osm-haifa-20261010')
        cls.folder=ROOT/'data/stage3/osm-members-20261010'
        cls.extra,cls.sm=supplement(cls.folder,cls.base,cls.manifest)
        cls.graph=normalize(cls.base,cls.manifest)

    def reject_mutation(self,manifest_change=None,data_change=None):
        m=copy.deepcopy(self.sm)
        raw=gzip.decompress((self.folder/'raw.json.gz').read_bytes())
        if data_change:
            d=json.loads(raw);data_change(d);raw=json.dumps(d).encode()
            m['sha256']=hashlib.sha256(raw).hexdigest();m['bytes']=len(raw)
        if manifest_change:manifest_change(m)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'manifest.json').write_text(json.dumps(m))
            (p/'raw.json.gz').write_bytes(gzip.compress(raw,mtime=0))
            with self.assertRaises(ValueError):supplement(p,self.base,self.manifest)

    def test_real_six_references_resolved_without_graph_expansion(self):
        before=copy.deepcopy(self.graph)
        r=audit(self.base,self.manifest,self.graph,self.extra)
        self.assertEqual(r['summary']['resolved_references'],6)
        self.assertEqual(r['summary']['unique_dependency_ways'],5)
        self.assertTrue(all(f['all_nodes_outside_bbox'] for f in r['missing_reference_report']))
        self.assertEqual(self.graph,before)
        self.assertEqual(normalize(self.base,self.manifest),before)
        self.assertTrue(all(t['status']=='quarantine' and t['truck_applicability']=='unknown' for t in r['turns']))

    def test_incomplete_turns_remain_quarantined(self):
        old={(e['type'],e['id']):e for e in self.base['elements']}
        r=audit(self.base,self.manifest,self.graph,old)
        self.assertEqual(r['summary']['missing_references_after'],6)
        self.assertEqual(r['summary']['turn_reasons']['incomplete'],6)
        self.assertEqual(r['summary']['verified_restrictions'],0)

    def test_checksum_rejection(self):
        self.reject_mutation(lambda m:m.update(sha256='0'*64))

    def test_mixed_dates_and_scope_rejected(self):
        self.reject_mutation(lambda m:m.update(source_snapshot_at='2026-10-10T10:00:00Z'))
        self.reject_mutation(lambda m:m.update(query='way(1);out;'))
        self.reject_mutation(lambda m:m.update(bbox_wgs84=[34,32,36,34]))

    def test_license_evidence_required(self):
        for k,v in [('decision','pending'),('identifier','unknown'),('evidence_url','https://example.invalid')]:
            self.reject_mutation(lambda m:m['license'].update({k:v}))

    def test_missing_extra_and_duplicate_objects_rejected(self):
        self.reject_mutation(data_change=lambda d:d['elements'].pop())
        self.reject_mutation(data_change=lambda d:d['elements'].append(copy.deepcopy(d['elements'][0])))
        self.reject_mutation(data_change=lambda d:d.update(remark='timeout'))

    def test_conflicting_shared_node_rejected(self):
        def change(d):
            ids={(e['type'],e['id']) for e in self.base['elements']}
            e=next(e for e in d['elements'] if e['type']=='node' and (e['type'],e['id']) in ids)
            e['lon']+=0.00001
        self.reject_mutation(data_change=change)

    def test_future_revision_rejected(self):
        self.reject_mutation(data_change=lambda d:d['elements'][0].update(timestamp='2027-01-01T00:00:00Z'))

    def test_components_cycles_isolates_and_reverse_edges(self):
        edges=[(1,2),(2,1),(2,3),(4,3)]
        self.assertEqual(components(range(1,6),edges),[[1,2,3,4],[5]])
        self.assertEqual(components(range(1,6),edges,True),[[1,2],[3],[4],[5]])

    def test_unknown_direction_does_not_add_arcs(self):
        g={'nodes':[{'id':'a'},{'id':'b'}], 'segments':[{'from_node':'a','to_node':'b','direction':'unknown'}]}
        s=audit({'elements':[]},self.manifest,g,{})['summary']
        self.assertEqual(s['explicit_direction_arcs'],0)
        self.assertEqual(s['weak_components'],1)
        self.assertEqual(s['strong_components_explicit_directions_only'],2)

    def test_extra_member_role_not_silently_ignored(self):
        p=copy.deepcopy(self.base);r=next(e for e in p['elements'] if e['type']=='relation' and e['id']==10115408)
        extra=copy.deepcopy(r['members'][0]);extra['role']='unrecognized';r['members'].append(extra)
        result=audit(p,self.manifest,self.graph,self.extra)
        row=next(t for t in result['turns'] if t['id']==r['id'])
        self.assertEqual(row['reason'],'unsupported_member_structure')

    def test_conditional_and_hgv_exception_not_flattened(self):
        for key,value in [('restriction:conditional','no_left_turn @ (Mo-Fr)'),('except','hgv')]:
            p=copy.deepcopy(self.base);r=next(e for e in p['elements'] if e['type']=='relation' and e['id']==10115408)
            r['tags'][key]=value
            result=audit(p,self.manifest,self.graph,self.extra)
            row=next(t for t in result['turns'] if t['id']==r['id'])
            self.assertEqual(row['reason'],'qualified_or_conditional_semantics')
            self.assertEqual(row['truck_applicability'],'unknown')
