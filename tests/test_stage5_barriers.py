"""All fixtures in this file are SYNTHETIC; none is a real road restriction."""
import importlib.util
from pathlib import Path
import unittest
import json
import sqlite3
import tempfile

spec = importlib.util.spec_from_file_location('stage5_barriers', Path(__file__).parents[1] / 'scripts/stage5/barriers.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


class SyntheticBarrierTests(unittest.TestCase):
    def assertDecision(self, tags, expected, **kwargs):
        d = b.classify_access(tags, **kwargs)
        self.assertEqual(d['interpretation'], expected)
        self.assertEqual(d['evidence_status'], 'QUARANTINE')
        self.assertFalse(d['navigation_eligible'])
        self.assertEqual(d['physical_passability'], 'UNKNOWN')
        return d

    def test_missing(self): self.assertDecision({}, 'UNKNOWN')
    def test_motorcar_does_not_grant_hgv(self): self.assertDecision({'motorcar': 'yes'}, 'UNKNOWN')
    def test_hgv_override_general(self): self.assertDecision({'access': 'no', 'hgv': 'yes'}, 'TAGGED_ALLOWED')
    def test_hgv_denied_despite_car(self): self.assertDecision({'motorcar': 'yes', 'hgv': 'no'}, 'TAGGED_DENIED')
    def test_motorvehicle_over_vehicle(self): self.assertDecision({'vehicle': 'yes', 'motor_vehicle': 'no'}, 'TAGGED_DENIED')
    def test_vehicle_over_access(self): self.assertDecision({'access': 'yes', 'vehicle': 'no'}, 'TAGGED_DENIED')
    def test_private_requires_permission(self): self.assertDecision({'hgv': 'private'}, 'RESTRICTED')
    def test_destination_requires_purpose(self): self.assertDecision({'hgv': 'destination'}, 'RESTRICTED')
    def test_hgv_designated(self): self.assertDecision({'hgv': 'designated'}, 'TAGGED_ALLOWED')
    def test_blanket_designated(self): self.assertDecision({'access': 'designated'}, 'UNKNOWN')
    def test_gates_no_default(self): self.assertDecision({'barrier': 'gate'}, 'UNKNOWN', is_node=True)
    def test_bollards_no_default(self): self.assertDecision({'barrier': 'bollard'}, 'UNKNOWN', is_node=True)
    def test_barrier_explicit_not_physical_permission(self): self.assertDecision({'barrier': 'gate', 'hgv': 'yes'}, 'TAGGED_ALLOWED', is_node=True)
    def test_directional(self):
        self.assertDecision({'hgv:forward': 'no', 'hgv': 'yes'}, 'TAGGED_DENIED')
        self.assertDecision({'hgv:forward': 'no', 'hgv': 'yes'}, 'TAGGED_ALLOWED', direction='backward')
    def test_mode_precedes_general_direction(self): self.assertDecision({'hgv': 'no', 'access:forward': 'yes'}, 'TAGGED_DENIED')
    def test_node_direction_ambiguous(self): self.assertDecision({'hgv:forward': 'yes'}, 'UNKNOWN', is_node=True)
    def test_conditional_never_falls_back_allow(self): self.assertDecision({'hgv': 'yes', 'hgv:conditional': 'no @ (Mo 07:00-09:00)'}, 'UNKNOWN')
    def test_exception_unresolved(self): self.assertDecision({'hgv': 'no', 'except': 'hgv'}, 'UNKNOWN')
    def test_unrecognized_scope(self): self.assertDecision({'hgv': 'yes', 'hgv:trailer': 'no'}, 'UNKNOWN')
    def test_unrecognized_value(self): self.assertDecision({'hgv': 'foo'}, 'UNKNOWN')
    def test_wrong_direction(self):
        with self.assertRaises(ValueError): b.classify_access({}, 'north')
    def test_node_way_conflict(self):
        r = b.combine_access(b.classify_access({'hgv':'no'}), b.classify_access({'hgv':'yes'}))
        self.assertEqual(r['interpretation'], 'UNKNOWN')
        self.assertEqual(r['reason'], 'node_way_conflicting_explicit_access')
    def test_way_allow_not_clear_unknown_gate(self):
        r = b.combine_access(b.classify_access({'barrier':'gate'}), b.classify_access({'hgv':'yes'}))
        self.assertEqual(r['interpretation'], 'UNKNOWN')
    def test_explicit_deny_blocks_unknown(self):
        r = b.combine_access(b.classify_access({'hgv':'no'}), b.classify_access({}))
        self.assertEqual(r['interpretation'], 'TAGGED_DENIED')
    def test_relevant(self):
        self.assertTrue(b.relevant({'vehicle:conditional':'no @ (PH)'}))
        self.assertFalse(b.relevant({'motorcar':'yes'}))


class SyntheticExtractionTests(unittest.TestCase):
    def test_source_nodes_and_repeated_way_membership_are_preserved(self):
        try:
            import osmium
        except ImportError:
            self.skipTest('pyosmium unavailable')
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            pbf = base / 'synthetic.osm'
            pbf.write_text('<osm version="0.6"><node id="1" version="1" lat="32" lon="35"><tag k="barrier" v="gate"/></node><node id="2" version="1" lat="32.1" lon="35.1"><tag k="hgv" v="no"/></node></osm>')
            source = base / 'synthetic.sqlite'
            db = sqlite3.connect(source)
            db.execute('CREATE TABLE ways(id INTEGER PRIMARY KEY,version INTEGER,timestamp TEXT,tags TEXT,nodes TEXT)')
            db.execute('INSERT INTO ways VALUES(10,1,?,?,?)', ('2026-01-01',json.dumps({'highway':'service','hgv':'yes'}), '[1,3,1]'))
            db.commit(); db.close()
            m = {'source_id':'SYNTHETIC', 'license':'ODbL-1.0','attribution':'synthetic test fixture', 'snapshot_at':'2026-01-01T00:00:00Z','sha256':b.sha256(pbf)}
            manifest = base / 'manifest.json'; manifest.write_text(json.dumps(m))
            before = b.sha256(source)
            first = b.build(pbf, source, base / 'one', manifest)
            second = b.build(pbf, source, base / 'two', manifest)
            self.assertEqual(first, second)
            self.assertEqual(b.sha256(source), before)
            self.assertEqual(first['counts']['node_records'],2)
            self.assertEqual(first['counts']['nodes_without_highway_membership'],1)
            self.assertEqual(first['counts']['node_way_incidence_records'],2)
            nodes = [json.loads(line) for line in (base/'one/barrier-nodes.jsonl').read_text().splitlines()]
            self.assertEqual(nodes[0]['geometry']['coordinates'],[35.0,32.0])
            self.assertEqual(nodes[0]['source_way_occurrences'],2)
            self.assertEqual(first['evidence_status_counts']['VERIFIED'],0)
            with self.assertRaises(ValueError): b.build(pbf, source, base / 'one', manifest)


if __name__ == '__main__': unittest.main()
