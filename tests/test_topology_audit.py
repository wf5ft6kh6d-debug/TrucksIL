"""Synthetic fixtures for diagnostic rules, never road restrictions."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from topology_audit import relation,classify,endpoint_evidence
class TopologyAuditTests(unittest.TestCase):
 def test_endpoint_touch(self):self.assertEqual(relation([(0,0),(1,1)],[(1,1),(2,0)]),'endpoint_touch')
 def test_t_touch(self):self.assertEqual(relation([(0,0),(2,0)],[(1,0),(1,1)]),'interior_touch')
 def test_partial_overlap(self):self.assertEqual(relation([(0,0),(2,0)],[(1,0),(3,0)]),'overlaps')
 def test_contained_overlap(self):self.assertEqual(relation([(0,0),(3,0)],[(1,0),(2,0)]),'contained_overlap')
 def test_reverse_duplicate(self):self.assertEqual(relation([(0,0),(1,1)],[(1,1),(0,0)]),'equals')
 def test_different_levels_not_connection(self):self.assertEqual(classify('crosses',[],{'layer':'1'},{'layer':'-1'})[0],'UNKNOWN')
 def test_bridge_transition_not_automatic_defect(self):self.assertEqual(classify('endpoint_touch',[1],{'bridge':'yes','layer':'1'}, {})[0],'VERIFIED')
 def test_tunnel_endpoint_not_confirmed_portal(self):self.assertFalse(endpoint_evidence({'id':1,'nodes':[2,3]}, {2:{'lon':1,'lat':2},3:{'lon':2,'lat':3}},[])[0]['physical_portal_confirmed'])
 def test_missing_osm_node(self):self.assertTrue(endpoint_evidence({'id':1,'nodes':[2,3]}, {},[])[0]['missing_node'])
 def test_ambiguous_touch_is_quarantined(self):self.assertEqual(classify('interior_touch',[],{}, {})[0],'QUARANTINE')
 def test_same_node_different_levels_needs_review(self):self.assertEqual(classify('endpoint_touch',[1],{'layer':'1'},{'layer':'0'})[0],'UNKNOWN')
 def test_zero_length_rejected(self):
  with self.assertRaises(ValueError):relation([(0,0),(0,0)],[(0,0),(1,1)])
