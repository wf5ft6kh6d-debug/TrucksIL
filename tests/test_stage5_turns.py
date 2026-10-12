"""SYNTHETIC fixtures only; directed research topology is not legal evidence."""
import unittest
from scripts.stage5.turns import analyze_turn

class TurnResearch(unittest.TestCase):
    def setUp(self):
        self.w={1:{'nodes':[1,2],'tags':{'oneway':'yes'}},2:{'nodes':[2,3,4],'tags':{'oneway':'yes'}},3:{'nodes':[4,5],'tags':{'oneway':'yes'}}}
        self.m=[{'type':'w','role':'from','id':1},{'type':'w','role':'via','id':2},{'type':'w','role':'to','id':3}]
    def run_rule(self,tags=None): return analyze_turn(tags or {'restriction':'no_left_turn'},self.m,self.w,{'synthetic':True})
    def test_via_way(self): self.assertEqual(self.run_rule()['parse_status'],'SUPPORTED')
    def test_only(self): self.assertEqual(self.run_rule({'restriction':'only_straight_on'})['semantics'],'ONLY_SEQUENCE')
    def test_reverse_conflict(self):
        self.w[2]['tags']['oneway']='-1'; self.assertIn('directed_chain_conflict',self.run_rule()['reasons'])
    def test_unknown_direction(self):
        self.w[2]['tags']={}; self.assertEqual(self.run_rule()['parse_status'],'UNKNOWN')
    def test_no_geometry_snapping(self):
        self.w[2]['nodes']=[9,3,4]; self.assertIn('missing_or_ambiguous_connection',self.run_rule()['reasons'])
    def test_missing_way(self):
        del self.w[2]; self.assertIn('missing_way',self.run_rule()['reasons'])
    def test_multiple_joins(self):
        self.w[1]['nodes']=[1,2,3]; self.assertIn('missing_or_ambiguous_connection',self.run_rule()['reasons'])
    def test_closed_way_unknown(self):
        self.w[2]['nodes']=[2,3,4,2]; self.assertEqual(self.run_rule()['parse_status'],'UNKNOWN')
    def test_vehicle_priority(self): self.assertEqual(self.run_rule({'restriction':'only_left_turn','restriction:hgv':'no_right_turn'})['restriction'],'no_right_turn')
    def test_car_not_hgv(self): self.assertEqual(self.run_rule({'restriction:motorcar':'no_left_turn'})['parse_status'],'UNKNOWN')
    def test_except_hgv(self): self.assertFalse(self.run_rule({'restriction':'no_left_turn','except':'hgv'})['applies_to_hgv'])
    def test_specific_except_conflict(self): self.assertIn('specific_rule_except_conflict',self.run_rule({'restriction:hgv':'no_left_turn','except':'hgv'})['reasons'])
    def test_unknown_except(self): self.assertIn('unsupported_except',self.run_rule({'restriction':'no_left_turn','except':'delivery'})['reasons'])
    def test_conditional(self): self.assertEqual(self.run_rule({'restriction:conditional':'no_left_turn @ (Mo-Fr 08:00-10:00)'})['parse_status'],'SUPPORTED')
    def test_holiday_unknown(self): self.assertEqual(self.run_rule({'restriction:conditional':'no_left_turn @ (PH)'})['parse_status'],'UNKNOWN')
    def test_stays_quarantined(self):
        r=self.run_rule(); self.assertEqual(r['status'],'QUARANTINE'); self.assertFalse(r['navigation_eligible'])
    def test_node_via(self):
        self.m=[self.m[0],{'type':'n','role':'via','id':2},{'type':'w','role':'to','id':2}]
        self.assertEqual(self.run_rule()['parse_status'],'SUPPORTED')
    def test_repeated_way(self):
        self.m[-1]['id']=1; self.assertIn('repeated_way_ambiguous',self.run_rule()['reasons'])

    def test_base_conditional_conflict(self): self.assertIn('base_conditional_value_conflict',self.run_rule({'restriction':'no_left_turn','restriction:conditional':'only_right_turn @ (Mo 08:00-09:00)'})['reasons'])
    def test_multiple_vehicle_conditional_scopes(self): self.assertIn('multiple_vehicle_conditional_scopes',self.run_rule({'restriction:hgv':'no_left_turn','restriction:conditional':'no_left_turn @ (Mo 08:00-09:00)'})['reasons'])
    def test_unsupported_direction_qualifier(self): self.assertIn('unsupported_restriction_qualifier',self.run_rule({'restriction':'no_left_turn','restriction:hgv:forward':'only_right_turn'})['reasons'])

    def test_conditional_oneway_not_known(self):
        self.w[2]['tags']['oneway:conditional']='no @ (Mo 08:00-09:00)'
        r=self.run_rule(); self.assertEqual(r['parse_status'],'UNKNOWN'); self.assertIn('unsupported_oneway_modifier',r['reasons'])
    def test_hgv_oneway_not_known(self):
        self.w[2]['tags']['oneway:hgv']='no'
        self.assertEqual(self.run_rule()['parse_status'],'UNKNOWN')
