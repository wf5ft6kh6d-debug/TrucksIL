"""Entirely synthetic coverage fixtures; never a road restriction corpus."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from scripts.stage7.coverage import build_coverage, write_outputs, sha256


class CoverageTests(unittest.TestCase):
    def rows(self):
        return ([{'source_id': 'synthetic-source', 'regions': ['NORTH'], 'source_status': 'SYNTHETIC_TEST'}],
                [{'id': 'synthetic-test-record', 'sources': ['synthetic-source'], 'synthetic': False,
                  'scope': 'LOCAL', 'evidence_status': 'QUARANTINE',
                  'location': {'region': 'NORTH', 'road_refs': ['1'], 'direction': None}}])

    def graph(self, path):
        with sqlite3.connect(path) as c:
            c.executescript('CREATE TABLE ways(id INTEGER,tags TEXT); CREATE TABLE segments(id INTEGER);')
            c.executemany('INSERT INTO ways VALUES (?,?)', [(1, json.dumps({'ref': '1'})), (2, json.dumps({'ref': '11'})), (3, json.dumps({'ref': '1; 20'}))])

    def test_unavailable_is_not_absent(self):
        s, r = self.rows()
        result = build_coverage(s, r, '/does-not-exist/synthetic-graph')
        self.assertEqual(result['graph_observation']['availability'], 'UNAVAILABLE_AT_REQUESTED_PATH')
        self.assertEqual(result['geolocation'][0]['binding_status'], 'UNKNOWN')

    def test_readonly_exact_reference_candidates_never_binding(self):
        s, r = self.rows()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'synthetic.sqlite'; self.graph(p); before = sha256(p)
            result = build_coverage(s, r, p)
            self.assertEqual(result['geolocation'][0]['candidate_way_ids'], [1, 3])
            self.assertEqual(result['geolocation'][0]['binding_status'], 'AMBIGUOUS')
            self.assertIsNone(result['geolocation'][0]['bound_geometry'])
            self.assertEqual(sha256(p), before)

    def test_single_candidate_still_ambiguous(self):
        s, r = self.rows(); r[0]['location']['road_refs'] = ['20']
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'synthetic.sqlite'; self.graph(p)
            self.assertEqual(build_coverage(s, r, p)['geolocation'][0]['binding_status'], 'AMBIGUOUS')

    def test_invalid_region_not_silently_inside_country(self):
        s, r = self.rows(); r[0]['location']['region'] = 'UNRESOLVED_JURISDICTION'
        result = build_coverage(s, r)
        self.assertEqual(result['matrix'][-1]['records'], 1)
        self.assertEqual(result['geolocation'][0]['jurisdiction_status'], 'UNKNOWN')

    def test_general_norm_not_local_road(self):
        s, r = self.rows(); r[0]['scope'] = 'GENERAL_VEHICLE_NORM'
        self.assertEqual(build_coverage(s, r)['geolocation'][0]['binding_status'], 'NOT_APPLICABLE')

    def test_sources_not_counted_as_records_or_coverage(self):
        s, r = self.rows(); result = build_coverage(s, [])
        north = next(x for x in result['matrix'] if x['region'] == 'NORTH')
        self.assertEqual(north['source_registry_entries'], 1); self.assertEqual(north['records'], 0)
        self.assertTrue(all(x['completeness'] == 'UNKNOWN' for x in result['matrix']))

    def test_no_missing_source_or_duplicate_identity(self):
        s, r = self.rows()
        for sources, records in [(s+s,r),(s,r+r),([],r)]:
            with self.assertRaises(ValueError): build_coverage(sources, records)

    def test_synthetic_corpus_rejected(self):
        s, r = self.rows(); r[0]['synthetic'] = True
        with self.assertRaises(ValueError): build_coverage(s,r)

    def test_repeat_and_no_input_mutation(self):
        s, r = self.rows(); original = copy.deepcopy((s,r))
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d)/'a', Path(d)/'b'
            write_outputs(build_coverage(s,r), a); write_outputs(build_coverage(s,r), b)
            self.assertEqual({p.name:p.read_bytes() for p in a.iterdir()}, {p.name:p.read_bytes() for p in b.iterdir()})
        self.assertEqual((s,r), original)

    def test_candidate_limit_explicit(self):
        s,r = self.rows()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'synthetic.sqlite';self.graph(p)
            with sqlite3.connect(p) as c:
                c.executemany('INSERT INTO ways VALUES (?,?)', [(i,json.dumps({'ref':'1'})) for i in range(100,160)])
            binding=build_coverage(s,r,p)['geolocation'][0]
            self.assertEqual(len(binding['candidate_way_ids']),50)
            self.assertEqual(binding['candidate_counts_by_ref']['1'],62)
            self.assertTrue(binding['candidate_list_may_be_truncated'])

    def test_invalid_query_not_a_completed_pass(self):
        sources, records = self.rows()
        attempts = [{'region':'NORTH','query_pass':0}, {'region':'NORTH','query_pass':1}]
        north = next(r for r in build_coverage(sources,records,search_attempts=attempts)['matrix'] if r['region']=='NORTH')
        self.assertEqual(north['search_attempts'],2)
        self.assertEqual(north['invalid_query_attempts'],1)
        self.assertEqual(north['valid_query_attempts'],1)
        self.assertEqual(north['query_passes_executed'],[1])
