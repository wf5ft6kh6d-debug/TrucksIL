"""Independent oracle and research adapter fixtures are explicitly synthetic."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo
from scripts.stage6.validation import validate_cases,reference_route,_transition,fixture_cases
from scripts.stage6.national import measurement_decision,profile_admissibility,ROUTE_LIMITS,WORKER_MEMORY_BYTES,WORKER_TIMEOUT_SECONDS


class Stage6ValidationTests(unittest.TestCase):
    def test_differential_full_walk_oracle(self):
        result=validate_cases()
        self.assertEqual(result['status'],'PASS',[(c['id'],c['reference'],c['actual']['status']) for c in result['cases'] if c['status']!='PASS'])
        self.assertGreaterEqual(result['case_count'],27)
        self.assertTrue(all(c['synthetic'] and not c['navigation_eligible'] for c in result['cases']))

    def test_oracle_truncation_is_not_no_route(self):
        edges=[dict(id='loop',**{'from':1,'to':1},way_id=1,duration_seconds=1,direction_status='KNOWN',admissibility='KNOWN')]
        r=reference_route(edges,1,2,[],dt.datetime(2026,10,12,tzinfo=ZoneInfo('Asia/Jerusalem')),max_depth=3)
        self.assertEqual(r['status'],'REFERENCE_INCONCLUSIVE')

    def test_backtracking_does_not_erase_via_obligation(self):
        case=next(c for c in fixture_cases() if c['id']=='no_via_full_sequence')
        path=case['edges'][:3]
        path += [dict(path[2],id='reverse',**{'from':4,'to':3}),path[2]]
        allowed,unknown=_transition(path,case['edges'][3],case['rules'],dt.datetime(2026,10,12,tzinfo=ZoneInfo('Asia/Jerusalem')))
        self.assertFalse(allowed);self.assertFalse(unknown)

    def test_height_mass_boundaries_and_propagation(self):
        from scripts.stage6.routing import research_route
        tags={'hgv':'yes','maxheight':'4.20 m','maxweight':'20 t'}
        for profile,expected in [({'height_m':'4.19','mass_t':'19.99'},'RESEARCH_PATH_FOUND'),
                                 ({'height_m':'4.20','mass_t':'19.99'},'ADMISSIBILITY_UNDETERMINED'),
                                 ({'height_m':'4.21','mass_t':'19.99'},'NO_ROUTE'),
                                 ({'height_m':'4.19','mass_t':'20'},'ADMISSIBILITY_UNDETERMINED'),
                                 ({'height_m':'4.19','mass_t':'20.01'},'NO_ROUTE')]:
            d=profile_admissibility(tags,profile)
            edge=dict(id='synthetic',**{'from':1,'to':2},way_id=1,duration_seconds=1,direction_status='KNOWN',admissibility=d['admissibility'])
            r=research_route([edge],1,2,[],dt.datetime(2026,10,12,tzinfo=ZoneInfo('Asia/Jerusalem')))
            self.assertEqual(r['status'],expected)
            self.assertFalse(r['navigation_eligible'])

    def test_missing_units_history_and_conflicts_unknown(self):
        profile={'height_m':'4','mass_t':'18'}
        for tags in [{'hgv':'yes'}, {'hgv':'yes','maxheight':'4.2','maxweight':'20'},
                     {'hgv':'yes','bridge:height':'10 m','maxweight':'20 t'},
                     {'hgv':'yes','maxheight':'4.2 m','maxweight':'20 t','maxheight:physical':'4.1 m'}]:
            self.assertEqual(profile_admissibility(tags,profile)['admissibility'],'UNKNOWN')
        d=profile_admissibility({'hgv':'yes','maxheight':'4.2 m','maxweight':'20 t'},profile,node_tags=[{'hgv':'no'}])
        self.assertEqual(d['admissibility'],'UNKNOWN')

    def test_scoped_unknown_overrides_base_numeric_denial(self):
        for key,profile in [('maxheight',{'height_m':'4.5','mass_t':'18'}),('maxweight',{'height_m':'4','mass_t':'30'})]:
            tags={'hgv':'yes','maxheight':'4.2 m','maxweight':'20 t',key+':conditional':'none @ (Mo 07:00-09:00)'}
            self.assertEqual(profile_admissibility(tags,profile)['admissibility'],'UNKNOWN')

    def test_invalid_measurements_never_pass(self):
        for vehicle in ['NaN','Infinity','-1','0','garbage',None]:
            self.assertEqual(measurement_decision('4.2 m',vehicle,'m')[0],'UNKNOWN')
        for limit in ['NaN m','-1 m','0 m','4 ft','4.2',None]:
            self.assertEqual(measurement_decision(limit,'4','m')[0],'UNKNOWN')

    def test_node_only_and_unscopable_relations_are_retained(self):
        import sqlite3
        from scripts.stage6.national import _select_corridors
        db=sqlite3.connect(':memory:')
        db.executescript('CREATE TABLE ways(id INTEGER,tags TEXT,nodes TEXT); CREATE TABLE segments(id INTEGER,way_id INTEGER,seq INTEGER,a INTEGER,b INTEGER,direction TEXT,length_m REAL); CREATE TABLE relations(id INTEGER,tags TEXT,members TEXT,missing_refs TEXT);')
        for wid,nodes in [(10,[1,2]),(20,[2,3,4]),(30,[4,5])]:
            db.execute('INSERT INTO ways VALUES(?,?,?)',(wid,json.dumps({'highway':'primary','oneway':'yes'}),json.dumps(nodes)))
        db.executemany('INSERT INTO segments VALUES(?,?,?,?,?,?,?)',[(1,10,0,1,2,'forward',1),(2,20,0,2,3,'forward',1),(3,20,1,3,4,'forward',1),(4,30,0,4,5,'forward',1)])
        members=[{'type':'w','id':10,'role':'from'},{'type':'w','id':20,'role':'via'},{'type':'w','id':30,'role':'to'}]
        for rid,mem in [(1,members),(2,[{'type':'n','id':3,'role':'via'}]),(3,[])]:
            db.execute('INSERT INTO relations VALUES(?,?,?,?)',(rid,json.dumps({'type':'restriction','restriction':'no_straight_on'}),json.dumps(mem),'[]'))
        corridors,_,_,_,coverage=_select_corridors(db,{'synthetic':True})
        db.close()
        self.assertEqual(len(corridors),1)
        byid={r['object_id']:r for r in corridors[0]['rules']}
        self.assertEqual(set(byid),{1,2,3})
        self.assertEqual(byid[2]['parse_status'],'UNKNOWN')
        self.assertEqual(byid[3]['parse_status'],'UNKNOWN')
        self.assertEqual(coverage['no_spatial_member_ids'],[3])

    def test_timeout_preserves_complete_scenarios_and_discards_partial_line(self):
        import subprocess
        from unittest.mock import patch
        from scripts.stage6.national import run
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);graph=root/'graph';pbf=root/'pbf';out=root/'out'
            graph.write_bytes(b'synthetic graph sentinel');pbf.write_bytes(b'synthetic pbf sentinel')
            def timeout(*args,**kwargs):
                (out/'national-scenarios.jsonl').write_text('{"id":"completed","synthetic":true}\n{"id":')
                raise subprocess.TimeoutExpired(args[0],300)
            with patch('scripts.stage6.national.subprocess.run',side_effect=timeout):
                result=run(graph,pbf,out)
            self.assertEqual(result['status'],'INCOMPLETE')
            self.assertEqual(result['reason'],'worker_wall_time_limit')
            self.assertEqual(result['actual_corridors'],1)
            self.assertEqual(result['completed_corridor_ids'],['completed'])
            self.assertEqual(len((out/'national-scenarios.jsonl').read_text().splitlines()),1)
            self.assertEqual(graph.read_bytes(),b'synthetic graph sentinel')

    def test_resource_budgets_predeclared(self):
        self.assertEqual(ROUTE_LIMITS['max_states'],20000)
        self.assertEqual(ROUTE_LIMITS['max_runtime_seconds'],10)
        self.assertEqual(WORKER_TIMEOUT_SECONDS,300)
        self.assertEqual(WORKER_MEMORY_BYTES,512*1024*1024)

if __name__=='__main__':unittest.main()
