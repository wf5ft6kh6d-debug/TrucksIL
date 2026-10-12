"""Only synthetic fixtures; no real road restrictions are created here."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from scripts.stage5.scenarios import (dimension_decision, combine_decisions, graph_metrics,
                                      analyze_connectivity, _edge_filter, _rule_map,
                                      synthetic_scenarios)


class ScenarioTests(unittest.TestCase):
    def evidence(self, **kw):
        return dict(dict(quantity='permitted_clearance', unit='m', current=True,
                         value='4.20', source='SYNTHETIC'), **kw)

    def test_decimal_boundary_and_margin(self):
        for h, expected in [('4.19','TAGGED_ALLOWED'),('4.20','UNKNOWN'),('4.21','TAGGED_DENIED')]:
            result = dimension_decision(h, [self.evidence()])
            self.assertEqual(result['decision'], expected)
            self.assertFalse(result['navigation_eligible'])

    def test_structure_history_missing_units_invalid(self):
        for evidence in [[], [self.evidence(quantity='structure_height')],
                         [self.evidence(current=False)], [self.evidence(unit='ft')],
                         [self.evidence(value='NaN')], [self.evidence(source='')]]:
            self.assertEqual(dimension_decision('4',evidence)['decision'], 'UNKNOWN')
        for h in ['NaN','Infinity','-1','bad','0']:
            self.assertEqual(dimension_decision(h,[self.evidence()])['decision'], 'UNKNOWN')

    def test_conflicting_values_do_not_choose_larger(self):
        self.assertEqual(dimension_decision('4',[self.evidence(),self.evidence(value='4.3')])['decision'],'UNKNOWN')

    def test_composition_preserves_deny_and_unknown(self):
        self.assertEqual(combine_decisions(['TAGGED_ALLOWED','TAGGED_DENIED']),'UNKNOWN')
        for d in [[], ['TAGGED_ALLOWED','UNKNOWN'], ['QUARANTINE'], ['malformed']]:
            self.assertEqual(combine_decisions(d),'UNKNOWN')

    def test_directed_reachability_separates_unknown_from_topology(self):
        r=graph_metrics([10,20,30,40], [(0,1,'forward'),(1,2,'unknown')], [0,2])
        self.assertEqual(r['weak_topology']['components'],2)
        self.assertEqual(r['known_direction_weak']['components'],3)
        self.assertEqual([x['reachable_nodes'] for x in r['directed_reachability']],[2,1])

    def test_reverse_and_both(self):
        r=graph_metrics([1,2,3],[(0,1,'reverse'),(1,2,'both')],[0,1,2])
        self.assertEqual([x['reachable_nodes'] for x in r['directed_reachability']],[1,3,3])

    def test_directional_deny_not_global_road_deletion(self):
        rules=_rule_map([dict(id=10,direction='forward',decision='TAGGED_DENIED')])
        r=list(_edge_filter([(10,1,2,'both')],{1:0,2:1},{},rules,False))
        self.assertEqual(r,[(0,1,'reverse')])

    def test_unknown_rule_sensitivity_not_permission(self):
        rules=_rule_map([dict(id=1,decision='UNKNOWN')])
        self.assertEqual(list(_edge_filter([(10,1,2,'forward')],{1:0,2:1},rules,{},False)),[(0,1,'forward')])
        self.assertEqual(list(_edge_filter([(10,1,2,'forward')],{1:0,2:1},rules,{},True)),[])

    def test_multiple_rule_sources_are_not_overwritten(self):
        r=_rule_map([dict(id=1,decision='TAGGED_DENIED'),dict(id=1,decision='TAGGED_ALLOWED')])
        self.assertEqual(len(r[1]),2)
        self.assertEqual(list(_edge_filter([(10,1,2,'both')],{1:0,2:1},r,{},False)),[])

    def test_read_only_repeat_and_fixed_nodes(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'fixture.sqlite'; out=Path(temp)/'out.json'
            db=sqlite3.connect(source)
            db.executescript('CREATE TABLE ways(id INTEGER,tags TEXT); CREATE TABLE segments(id INTEGER,way_id INTEGER,a INTEGER,b INTEGER,direction TEXT);')
            db.executemany('INSERT INTO ways VALUES(?,?)',[(10,json.dumps({'highway':'primary'})),(20,json.dumps({'highway':'footway'}))])
            db.executemany('INSERT INTO segments VALUES(?,?,?,?,?)',[(1,10,1,2,'both'),(2,10,2,3,'forward'),(3,20,3,4,'both')])
            db.commit();db.close()
            original=source.read_bytes()
            r=analyze_connectivity(source,out,node_rules=[dict(id=2,decision='TAGGED_DENIED')])
            self.assertEqual(r['baseline']['vertices'],3)
            self.assertEqual(r['tagged_denial_sensitivity']['vertices'],3)
            self.assertEqual(r['tagged_denial_sensitivity']['weak_topology']['components'],3)
            first=out.read_bytes()
            analyze_connectivity(source,out,node_rules=[dict(id=2,decision='TAGGED_DENIED')])
            self.assertEqual(first,out.read_bytes());self.assertEqual(original,source.read_bytes())
            self.assertEqual(r['classification_way_counts'],{'EXCLUDED':1,'INCLUDED':1})

    def test_actual_temporal_turn_scenarios(self):
        from scripts.stage5.scenarios import temporal_turn_scenarios
        cases={r['id']:r for r in temporal_turn_scenarios()}
        self.assertTrue(cases['start_inclusive']['result']['active'])
        self.assertFalse(cases['end_exclusive']['result']['active'])
        self.assertTrue(cases['overnight_previous_day']['result']['active'])
        self.assertFalse(cases['overnight_end_exclusive']['result']['active'])
        for name in ('holiday_unsupported','dst_repeated','dst_missing'):
            self.assertIsNone(cases[name]['result']['active'])
        self.assertEqual(cases['no_via_sequence']['result']['parse_status'],'SUPPORTED')
        self.assertEqual(cases['no_via_sequence']['result']['chain_way_ids'],[10,20,30])
        self.assertEqual(cases['only_via_sequence']['result']['semantics'],'ONLY_SEQUENCE')
        self.assertFalse(cases['except_hgv']['result']['applies_to_hgv'])
        self.assertEqual(cases['incomplete_chain']['result']['parse_status'],'UNKNOWN')
        self.assertEqual(cases['contradictory_via_direction']['result']['parse_status'],'UNKNOWN')
        self.assertEqual(cases['time_path_7']['result']['directed_reachability'][0]['reachable_nodes'],2)
        self.assertEqual(cases['time_path_9']['result']['directed_reachability'][0]['reachable_nodes'],3)
        self.assertEqual(cases['barrier_path']['result']['directed_reachability'][0]['reachable_nodes'],1)
        for name in ('no_sequence_blocks','only_sequence_blocks_other_exit'):
            self.assertEqual(cases[name]['baseline']['result'],'REACHABLE_IN_SYNTHETIC_MODEL')
            self.assertEqual(cases[name]['result']['result'],'UNREACHABLE_IN_SYNTHETIC_MODEL')
        self.assertEqual(cases['hgv_exception_preserves_path']['result']['result'],'REACHABLE_IN_SYNTHETIC_MODEL')
        self.assertTrue(all(r['synthetic'] and not r['navigation_eligible'] for r in cases.values()))

    def test_conditional_overlay_never_turns_inactive_or_yes_into_permission(self):
        import datetime as dt
        from zoneinfo import ZoneInfo
        from scripts.stage5.scenarios import conditional_overlay
        from scripts.stage5.temporal import parse_conditional
        records=[]
        for identity, raw, key in [(1,'no @ (Mo 07:00-09:00)','hgv:conditional'),
                                    (2,'yes @ (Mo 07:00-09:00)','hgv:conditional'),
                                    (3,'no @ (PH 07:00-09:00)','access:conditional'),
                                    (4,'no @ (Mo 07:00-09:00)','motorcar:conditional')]:
            r=parse_conditional(raw,'SYNTHETIC');r.update(object_type='way',object_id=identity,tag_key=key);records.append(r)
        _,ways,counts=conditional_overlay(records,dt.datetime(2026,10,12,7,tzinfo=ZoneInfo('Asia/Jerusalem')))
        self.assertEqual({r['id']:r['decision'] for r in ways},{1:'TAGGED_DENIED',2:'UNKNOWN',3:'UNKNOWN'})
        self.assertEqual(counts['not_modeled_tag_or_object'],1)
        _,ways,counts=conditional_overlay(records,dt.datetime(2026,10,12,9,tzinfo=ZoneInfo('Asia/Jerusalem')))
        self.assertEqual(ways,[dict(id=3,decision='UNKNOWN',direction='both')])
        self.assertEqual(counts['inactive_no_overlay'],2)

    def test_output_cannot_overwrite_original_or_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'original.sqlite'
            source.write_bytes(b'unchanged original sentinel')
            link=Path(temp)/'output-link.json';link.symlink_to(source)
            hardlink=Path(temp)/'output-hardlink.json';hardlink.hardlink_to(source)
            for output in (source,link,hardlink):
                with self.assertRaisesRegex(ValueError,'must not overwrite'):
                    analyze_connectivity(source,output)
                self.assertEqual(source.read_bytes(),b'unchanged original sentinel')

    def test_all_fixtures_explicitly_synthetic(self):
        self.assertTrue(all(r['synthetic'] and not r['navigation_eligible'] for r in synthetic_scenarios()))

if __name__=='__main__': unittest.main()
