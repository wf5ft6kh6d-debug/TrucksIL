"""Synthetic rule regressions only, never source data or permissions."""
import unittest
from scripts.stage4.infrastructure_audit import active,crossing_class,direction,turn_check

class InfrastructureRules(unittest.TestCase):
    def test_inactive_bridge_values(self):
        for x in ('no','false','0'):self.assertFalse(active({'bridge':x},'bridge'))
        self.assertTrue(active({'bridge':'viaduct'},'bridge'))
    def test_implicit_direction_not_inferred(self):
        self.assertEqual(direction({'junction':'roundabout','highway':'motorway'}),'unknown')
    def test_different_layers_not_verified(self):
        r=crossing_class({'layer':'1'},{'layer':'0'},[])
        self.assertEqual(r['classification'],'different_explicit_layer_candidate')
        self.assertFalse(r['physical_connection_verified'])
    def test_same_layer_no_node_unknown(self):
        self.assertEqual(crossing_class({'layer':'0'},{'layer':'0'},[])['status'],'UNKNOWN')
    def test_shared_node_not_physical_proof(self):
        self.assertFalse(crossing_class({}, {}, [5])['physical_connection_verified'])
    def fixture(self):
        ways={1:{'nodes':[1,2],'tags':{'oneway':'yes'}},2:{'nodes':[2,3],'tags':{'oneway':'yes'}}}
        m=[{'role':'from','id':1,'type':'w'},{'role':'via','id':2,'type':'n'},{'role':'to','id':2,'type':'w'}]
        return ways,m
    def test_incidence_quarantine(self):
        w,m=self.fixture();r=turn_check({},m,w)
        self.assertFalse(r['issues']);self.assertEqual(r['status'],'QUARANTINE')
    def test_reverse_direction_conflict(self):
        w,m=self.fixture();w[1]['tags']['oneway']='-1'
        self.assertIn('from_explicit_direction_conflict',turn_check({},m,w)['issues'])
    def test_missing_way_and_via(self):
        w,m=self.fixture();del w[1];m[1]['id']=99
        issues=turn_check({},m,w)['issues']
        self.assertIn('from_not_in_highway_graph',issues);self.assertIn('to_via_node_not_on_way',issues)
    def test_conditional_except_hgv_no_permission(self):
        w,m=self.fixture();r=turn_check({'restriction:conditional':'no_left_turn @ (Mo-Fr)','except':'hgv','restriction:hgv':'no_left_turn'},m,w)
        self.assertIn('except_requires_vehicle_interpretation',r['issues'])
        self.assertIn('vehicle_specific_restriction',r['issues']);self.assertEqual(r['status'],'QUARANTINE')
    def test_missing_from_not_invented(self):
        w,m=self.fixture();r=turn_check({},m[1:],w)
        self.assertIn('missing_from',r['issues']);self.assertEqual(r['direction_incidence'],{})
    def test_via_way_path_not_assumed(self):
        w,m=self.fixture();m[1]['type']='w'
        self.assertIn('via_way_requires_path_analysis',turn_check({},m,w)['issues'])

if __name__=='__main__':unittest.main()
