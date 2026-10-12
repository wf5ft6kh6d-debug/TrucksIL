"""SYNTHETIC research-only segment fixtures, never real transport restrictions."""
import datetime as dt
import unittest
from unittest.mock import patch
from scripts.stage5.temporal import parse_conditional, ZONE
from scripts.stage6.routing import research_route, normalize_rules

T = dt.datetime(2026,10,12,8,tzinfo=ZONE)
def edge(eid,a,b,way,seconds=1,**kw):
    return dict(id=eid,**{'from':a,'to':b},way_id=way,duration_seconds=seconds,
                direction_status='KNOWN',admissibility='KNOWN',**kw)
def rule(sequence,joins,kind='no',**kw):
    return dict(id='synthetic-rule',sequence=sequence,connection_nodes=joins,kind=kind,
                parse_status='SUPPORTED',**kw)

class ResearchRouting(unittest.TestCase):
    def setUp(self):
        self.edges=[edge('a',0,1,'A'),edge('b1',1,2,'B'),edge('b2',2,3,'B'),edge('c',3,4,'C')]
        self.rule=rule(['A','B','C'],[1,3])
    def route(self,edges=None,rules=None,start=0,goal=4,**kw):
        return research_route(self.edges if edges is None else edges,start,goal,
                              [self.rule] if rules is None else rules,kw.pop('departure',T),**kw)
    def test_no_rule_path(self): self.assertEqual(self.route(rules=[])['edge_ids'],['a','b1','b2','c'])
    def test_no_chain_blocked(self): self.assertEqual(self.route()['status'],'NO_ROUTE')
    def test_other_entrance_not_blocked(self):
        es=[edge('x',9,1,'X')]+self.edges
        self.assertEqual(self.route(es,start=9)['status'],'RESEARCH_PATH_FOUND')
    def test_other_join_not_blocked(self):
        es=[edge('x',0,2,'A')]+self.edges[2:]
        self.assertEqual(self.route(es)['status'],'RESEARCH_PATH_FOUND')
    def test_via_backtracking_cannot_evade_no(self):
        es=self.edges+[edge('back',2,1,'B')]
        self.assertEqual(self.route(es)['status'],'NO_ROUTE')
    def test_sameway_segment_history(self):
        es=self.edges+[edge('loop1',2,5,'B'),edge('loop2',5,2,'B')]
        self.assertEqual(self.route(es)['status'],'NO_ROUTE')
    def test_only_allows_ordered_chain(self):
        self.rule['kind']='only'; self.assertEqual(self.route()['status'],'RESEARCH_PATH_FOUND')
    def test_only_forbids_early_via_exit(self):
        self.rule['kind']='only'; es=self.edges[:2]+[edge('escape',2,4,'D')]
        self.assertEqual(self.route(es)['status'],'NO_ROUTE')
    def test_only_does_not_bind_earlier_from_exit(self):
        self.rule['kind']='only'; es=[edge('a',0,5,'A'),edge('x',5,4,'X')]
        self.assertEqual(self.route(es)['status'],'RESEARCH_PATH_FOUND')
    def test_only_forbids_skip_junction_sameway(self):
        r=rule(['A','C'],[1],'only'); es=[edge('a',0,1,'A'),edge('continue',1,4,'A')]
        self.assertEqual(self.route(es,[r])['status'],'NO_ROUTE')
    def test_only_forbids_skip_final_via_junction(self):
        self.rule['kind']='only'; es=self.edges[:3]+[edge('continue',3,4,'B')]
        self.assertEqual(self.route(es)['status'],'NO_ROUTE')
    def test_except_hgv(self):
        self.rule['except']=['hgv']; self.assertEqual(self.route()['status'],'RESEARCH_PATH_FOUND')
    def test_except_motorcar_not_hgv(self):
        self.rule['except']=['motorcar']; self.assertEqual(self.route()['status'],'NO_ROUTE')
    def test_unknown_except_not_exempt(self):
        self.rule['except']=['delivery']; self.assertEqual(self.route()['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_arrival_start_boundary(self):
        self.rule['conditional']=parse_conditional('no_left_turn @ (Mo 08:00-10:00)')
        start=dt.datetime(2026,10,12,7,59,57,tzinfo=ZONE)
        self.assertEqual(self.route(departure=start)['status'],'NO_ROUTE')
    def test_arrival_before_start(self):
        self.rule['conditional']=parse_conditional('no_left_turn @ (Mo 08:00-10:00)')
        start=dt.datetime(2026,10,12,7,59,56,tzinfo=ZONE)
        self.assertEqual(self.route(departure=start)['status'],'RESEARCH_PATH_FOUND')
    def test_arrival_end_boundary(self):
        self.rule['conditional']=parse_conditional('no_left_turn @ (Mo 08:00-10:00)')
        start=dt.datetime(2026,10,12,9,59,57,tzinfo=ZONE)
        self.assertEqual(self.route(departure=start)['status'],'RESEARCH_PATH_FOUND')
    def test_dst_fallback_unknown(self):
        self.rule['conditional']=parse_conditional('no_left_turn @ (00:00-03:00)')
        start=dt.datetime(2026,10,25,1,30,tzinfo=ZONE)
        self.assertEqual(self.route(departure=start)['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_imaginary_departure_unknown(self):
        self.assertEqual(self.route(rules=[],departure=dt.datetime(2026,3,27,2,30,tzinfo=ZONE))['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_unknown_time_not_permission(self): self.assertEqual(self.route(rules=[],departure=None)['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_unknown_duration(self):
        self.edges[0]['duration_seconds']=None
        self.assertEqual(self.route(rules=[])['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_unknown_direction(self):
        self.edges[0]['direction_status']='UNKNOWN'
        self.assertEqual(self.route(rules=[])['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_missing_admissibility(self):
        del self.edges[0]['admissibility']
        self.assertEqual(self.route(rules=[])['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_denied_edge(self):
        self.edges[0]['admissibility']='DENIED'; self.assertEqual(self.route(rules=[])['status'],'NO_ROUTE')
    def test_unknown_rule_not_dropped(self):
        self.rule['parse_status']='UNKNOWN'; self.assertEqual(self.route()['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_malformed_global_rule_not_dropped(self):
        self.assertEqual(self.route(rules=[{'id':'unknown','raw':'unsupported'}])['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_state_cap_incomplete(self): self.assertEqual(self.route(rules=[],limits={'max_states':2})['status'],'INCOMPLETE')
    def test_input_cap_incomplete(self): self.assertIn('input_edge_limit',self.route(limits={'max_input_edges':1})['reasons'])
    def test_memory_cap_incomplete(self): self.assertIn('memory_limit',self.route(limits={'max_memory_bytes':100})['reasons'])
    def test_expansion_cap_incomplete(self): self.assertIn('expansion_limit',self.route(limits={'max_expansions':1})['reasons'])
    def test_rule_length_cap_incomplete(self): self.assertIn('rule_length_limit',self.route(limits={'max_rule_length':2})['reasons'])
    def test_runtime_cap_incomplete(self):
        with patch('scripts.stage6.routing.time.monotonic',side_effect=[0,2]):
            self.assertIn('runtime_limit',self.route(limits={'max_runtime_seconds':1})['reasons'])
    def test_duplicate_id_rejected(self): self.assertIn('duplicate_edge_id',self.route(self.edges+self.edges[:1])['reasons'])
    def test_revisited_node_not_pruned(self):
        es=[edge('a',0,1,'A'),edge('b',1,2,'B'),edge('d',2,1,'D'),edge('c',1,4,'C')]
        r=rule(['A','C'],[1])
        self.assertEqual(self.route(es,[r])['edge_ids'],['a','b','d','c'])
    def test_repeated_nonconsecutive_way_chain(self):
        es=[edge('a',0,1,'A'),edge('b',1,2,'B'),edge('again',2,3,'A'),edge('c',3,4,'C')]
        r=rule(['A','B','A','C'],[1,2,3])
        self.assertEqual(self.route(es,[r])['status'],'NO_ROUTE')
    def test_sameway_u_turn(self):
        es=[edge('a',0,1,'A'),edge('back',1,0,'A'),edge('c',0,4,'C')]
        r=rule(['A','A'],[1])
        # Transition API isolates the manoeuvre because origin has a direct C edge.
        from scripts.stage6.routing import transition_decision
        self.assertTrue(transition_decision((('A',0),),es[0],es[1],normalize_rules([r]),T)['blocked'])
    def test_conditional_base_not_erased(self):
        r=dict(self.rule,conditional=parse_conditional('no_left_turn @ (00:00-01:00)'),
               selected_key='restriction',raw={'tags':{'restriction':'no_left_turn'}})
        self.assertEqual(self.route(rules=[r])['status'],'NO_ROUTE')
    def test_no_navigation_claim(self): self.assertFalse(self.route(rules=[])['navigation_eligible'])
    def test_reproducible_output(self): self.assertEqual(self.route(rules=[]),self.route(rules=[]))

    def test_malformed_conditional_unknown(self):
        self.rule['conditional']={'parse_status':'SUPPORTED'}
        self.assertEqual(self.route()['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_unhashable_rule_identifier_unknown(self):
        self.rule['sequence']=[['nested'],'B','C']
        self.assertEqual(self.route()['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_unhashable_exception_unknown(self):
        self.rule['except']=[{'bad':'exception'}]
        self.assertEqual(self.route()['status'],'ADMISSIBILITY_UNDETERMINED')
    def test_unhashable_edge_identifier_incomplete(self):
        self.edges[0]['id']=['bad']
        self.assertEqual(self.route()['status'],'INCOMPLETE')
    def test_duration_overflow_unknown(self):
        for e in self.edges: e['duration_seconds']=1e308
        self.assertEqual(self.route(rules=[])['status'],'ADMISSIBILITY_UNDETERMINED')
