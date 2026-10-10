"""Real regressions and labeled synthetic mutations; no navigation promotion."""
import copy,gzip,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from osm_pilot import load_snapshot,normalize
from pilot_graph_audit import supplement
from relation_review import review_relation,topology_diagnostics,load_current,IDS

class RelationReviewTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.p,cls.m=load_snapshot(ROOT/'data/stage3/osm-haifa-20261010');cls.o,_=supplement(ROOT/'data/stage3/osm-members-20261010',cls.p,cls.m)
 def review(self,i,o=None):
  o=self.o if o is None else o;return review_relation(o['relation',i],o,self.m['bbox_wgs84'])
 def test_no_left_turn_against_oneway_is_not_required_movement(self):
  r=self.review(10115408);self.assertEqual(r['finding'],'prohibited_manoeuvre_already_unreachable');self.assertTrue(r['incoming_arcs']);self.assertFalse(r['outgoing_arcs']);self.assertEqual(r['status'],'quarantine')
 def test_no_u_turn_on_same_oneway_is_redundant_not_permission(self):
  r=self.review(10115411);self.assertEqual(r['finding'],'prohibited_manoeuvre_already_unreachable');self.assertEqual(r['truck_applicability'],'unknown')
 def test_only_turn_with_unreachable_exit_is_distinct_synthetic(self):
  o=copy.deepcopy(self.o);o['relation',10115408]['tags']['restriction']='only_left_turn'
  self.assertEqual(self.review(10115408,o)['finding'],'required_manoeuvre_direction_conflict')
 def test_two_incomplete_relations_have_absent_from_not_missing_way(self):
  for i in (12303230,13395546):
   r=self.review(i);self.assertEqual(r['role_counts'],{'from':0,'via':1,'to':1});self.assertEqual(r['finding'],'missing_from_member');self.assertTrue(all(not x.get('missing') for x in r['member_evidence']))
 def test_conditional_or_hgv_exception_prevents_unconditional_inference(self):
  for key in ('restriction:conditional','except'):
   o=copy.deepcopy(self.o);o['relation',10115408]['tags'][key]='hgv'
   self.assertEqual(self.review(10115408,o)['finding'],'unknown_semantics_or_direction')
 def test_missing_oneway_remains_unknown_synthetic(self):
  o=copy.deepcopy(self.o);o['way',983720407]['tags'].pop('oneway')
  self.assertEqual(self.review(10115408,o)['finding'],'unknown_semantics_or_direction')
 def test_topology_boundary_filter_and_unresolved_partition(self):
  g=normalize(self.p,self.m);before=copy.deepcopy(g);r=topology_diagnostics(self.p,self.m,g)
  self.assertEqual(r['summary']['leaf_findings'],{'bbox_cut':36,'filtered_class_adjacency':21,'source_endpoint_unresolved':43});self.assertEqual(r['summary']['full_raw_components_touching_pilot'],4);self.assertEqual(g,before)
  self.assertEqual(r['summary']['unknown_direction_reasons'],{'missing_oneway':575})
 def test_current_comparison_all_25_objects_unchanged(self):
  o,m=load_current(ROOT/'data/stage3/osm-review-20261010');self.assertEqual(len(o),25)
  for ident,e in o.items():
   clean=lambda x:{k:v for k,v in x.items() if k not in ('user','uid')}
   self.assertEqual(clean(e),clean(self.o[ident]))
 def test_current_checksum_license_and_scope_gates(self):
  folder=ROOT/'data/stage3/osm-review-20261010'
  for change in ('checksum','license','bbox'):
   with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp);m=json.loads((folder/'manifest.json').read_text())
    if change=='checksum':m['sha256']='0'*64
    elif change=='license':m['license']['decision']='pending'
    else:m['bbox_wgs84']=[34,32,36,34]
    (p/'manifest.json').write_text(json.dumps(m));(p/'raw.json.gz').write_bytes((folder/'raw.json.gz').read_bytes())
    with self.assertRaises(ValueError):load_current(p)
