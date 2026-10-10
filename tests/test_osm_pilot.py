"""Synthetic adversarial tests; real frozen snapshot tested separately. No invented road evidence."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts/stage3')]
from osm_pilot import normalize,load_snapshot,decode_tag,loads,coordinate
from build_pilot import copy_field,sql_plan
from ingest_restrictions import validate_record


def fixture():
    def node(n,x,y): return {'type':'node','id':n,'version':1,'timestamp':'2026-10-01T00:00:00Z','lon':x,'lat':y}
    p={'elements':[node(1,34.991,32.812),node(2,34.992,32.813),node(3,34.995,32.810),
        {'type':'way','id':1,'version':2,'timestamp':'2026-10-02T00:00:00Z','nodes':[1,2,3],
         'tags':{'highway':'service','oneway':'-1','maxheight:conditional':'4 @ (Mo-Fr)', 'maxheight':'3.5'}}]}
    m={'bbox_wgs84':[34.990,32.811,35.004,32.821],'sha256':'a'*64,
       'source_snapshot_at':'2026-10-10T00:00:00Z','retrieved_at':'2026-10-10T01:00:00Z'}
    return p,m


class PilotTests(unittest.TestCase):
    def test_metric_units_and_no_unsafe_defaults(self):
        for key,value,result in [('maxheight','3.50 m','3.50'),('maxweight','7500 kg','7.5'),('maxaxleload','8','8')]:
            self.assertEqual(decode_tag(key,value)['value'],result)
        for key,v in [('maxheight','none'),('maxheight','0'),('maxheight','-3'),('maxheight','NaN'),
                      ('maxheight','4,5'),('maxheight','12\'6"'),('maxweight','3 m'),('hgv','destination'),('hgv','yes')]:
            self.assertIsNone(decode_tag(key,v))
    def test_direction_and_conditions_are_not_flattened(self):
        self.assertEqual(decode_tag('maxheight:backward','3')['direction'],'reverse')
        self.assertEqual(decode_tag('maxheight','3')['direction'],'unknown')
        self.assertIsNone(decode_tag('maxheight:conditional','3 @ (Mo-Fr)'))
        self.assertIsNone(decode_tag('maxheight:physical','3'))
        self.assertEqual(decode_tag('hazmat','no')['value'],'1')
    def test_bounds_source_identity_and_reverse(self):
        p,m=fixture();r=normalize(p,m)
        self.assertEqual(len(r['segments']),1);self.assertEqual(r['summary']['boundary_pairs_excluded'],1)
        seg=r['segments'][0];self.assertEqual(seg['direction'],'reverse')
        self.assertEqual(seg['geometry']['coordinates'],[[34.991,32.812],[34.992,32.813]])
        self.assertIn(':v2:0',seg['id']);self.assertEqual(seg['source_revision'],m['sha256'])
    def test_missing_and_duplicate_nodes_rejected(self):
        p,m=fixture();p['elements'].pop(0)
        with self.assertRaises(ValueError): normalize(p,m)
        p,m=fixture();p['elements'].append(copy.deepcopy(p['elements'][0]))
        with self.assertRaises(ValueError): normalize(p,m)
    def test_invalid_coordinates_and_revisions_rejected(self):
        for x,y in [(True,32),(181,32),(34,91),(float('nan'),32)]:
            with self.assertRaises(ValueError):coordinate(x,y)
        p,m=fixture();p['elements'][0]['version']=True
        with self.assertRaises(ValueError):normalize(p,m)
        p,m=fixture();p['elements'][0]['timestamp']='2027-01-01T00:00:00Z'
        with self.assertRaises(ValueError):normalize(p,m)
    def test_no_connection_from_coordinate_intersection(self):
        p,m=fixture();p['elements'].insert(0,{'type':'node','id':4,'version':1,'timestamp':'2026-10-01T00:00:00Z','lon':34.991,'lat':32.812})
        p['elements'].append({'type':'way','id':2,'version':1,'timestamp':'2026-10-01T00:00:00Z','nodes':[4,2],'tags':{'highway':'service','bridge':'yes','layer':'1'}})
        r=normalize(p,m);self.assertNotEqual(r['segments'][0]['from_node'],r['segments'][1]['from_node'])
        self.assertEqual(r['segments'][1]['tags']['layer'],'1')
    def test_conditional_direction_and_construction(self):
        p,m=fixture();p['elements'][-1]['tags']['oneway:conditional']='yes @ (Mo-Fr)'
        self.assertEqual(normalize(p,m)['segments'][0]['direction'],'unknown')
        p['elements'][-1]['tags']['highway']='construction'
        self.assertEqual(normalize(p,m)['segments'],[])
    def test_quarantine_not_a_valid_restriction(self):
        p,m=fixture();r=normalize(p,m)
        for o in r['observations']:
            self.assertIsNone(o['observed_at']);self.assertEqual(o['status'],'unverified')
            with self.assertRaises(ValueError):validate_record(o)
        self.assertFalse(r['summary']['route_safety_certified']);self.assertEqual(r['summary']['restriction_records_emitted'],0)
    def test_duplicate_keys_nonfinite_json_and_copy_escape(self):
        for text in ['{"a":1,"a":2}','[NaN]']:
            with self.assertRaises(ValueError):loads(text)
        self.assertEqual(copy_field('a\tb\nc\\d'),r'a\tb\nc\\d')
    def test_frozen_snapshot_reproducible(self):
        folder=ROOT/'data/stage3/osm-haifa-20261010';p,m=load_snapshot(folder)
        actual=normalize(p,m);self.assertEqual(actual['summary'],json.loads((folder/'expected-summary.json').read_text()))
        self.assertEqual(actual,normalize(p,m))
        self.assertEqual(m['sha256'],'ea8f94139f2f7c48372b7c53c30ada916dcfebaf5d6207315a76f0fde51e3b31')
    def test_checksum_and_license_gates(self):
        source=ROOT/'data/stage3/osm-haifa-20261010'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);p.joinpath('raw.json.gz').write_bytes(source.joinpath('raw.json.gz').read_bytes())
            m=json.loads(source.joinpath('manifest.json').read_text());original=copy.deepcopy(m)
            for key,value in [('decision','pending'),('identifier','unknown'),('evidence_url','https://example.invalid')]:
                m=copy.deepcopy(original);m['license'][key]=value
                p.joinpath('manifest.json').write_text(json.dumps(m))
                with self.assertRaises(ValueError):load_snapshot(p)
            m=copy.deepcopy(original);m['sha256']='0'*64;p.joinpath('manifest.json').write_text(json.dumps(m))
            with self.assertRaises(ValueError):load_snapshot(p)
    def test_sql_replay_is_guarded_and_always_rolls_back(self):
        folder=ROOT/'data/stage3/osm-haifa-20261010';p,m=load_snapshot(folder);sql=sql_plan(normalize(p,m),m)
        self.assertIn("inet_server_addr() IS NOT NULL",sql)
        self.assertIn('Pilot replay requires empty staging tables',sql)
        self.assertIn('ROLLBACK;',sql);self.assertNotIn('COMMIT;',sql)
        self.assertNotIn('COPY restriction_staging',sql);self.assertNotIn('DISABLE TRIGGER',sql)
