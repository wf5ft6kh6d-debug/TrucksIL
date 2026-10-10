"""Synthetic unit cases only; never published as real road restrictions."""
import unittest
from scripts.stage4.national_graph import categories,direction,tile,segment,DSU
class NationalTests(unittest.TestCase):
 def test_missing_direction_unknown(self):self.assertEqual(direction({'highway':'motorway'}),'unknown')
 def test_roundabout_not_inferred(self):self.assertEqual(direction({'junction':'roundabout'}),'unknown')
 def test_reverse(self):self.assertEqual(direction({'oneway':'-1'}),'reverse')
 def test_unknown_conditional(self):self.assertEqual(direction({'oneway:conditional':'yes @ (08:00-10:00)'}),'unknown')
 def test_original_units_preserved(self):
  t={'maxheight':'12 ft','maxweight:conditional':'7.5 @ (Mo-Fr)'};self.assertIn('maxweight',categories(t));self.assertEqual(t['maxheight'],'12 ft')
 def test_context_not_clearance(self):self.assertEqual(categories({'bridge':'yes'}),['bridge_context'])
 def test_no_zero_length(self):self.assertIsNone(segment((1,35,32),(2,35,32)))
 def test_coordinates_guard(self):
  with self.assertRaises(ValueError):segment((1,181,32),(2,35,32))
 def test_no_snap(self):
  d=DSU();d.join(1,2);d.join(3,4);self.assertEqual(d.sizes(),[2,2])
 def test_grid_boundary(self):self.assertEqual(tile(35.0,32.5),'35.0,32.5')
 def test_dsu_transitive(self):
  d=DSU();d.join(1,2);d.join(2,3);self.assertEqual(d.sizes(),[3])
 def test_hazmat_conditional(self):self.assertEqual(categories({'hazmat:conditional':'no @ (wet)'}),['hazmat','conditional'])
 def test_provenance_hash(self):
  import tempfile,hashlib
  from pathlib import Path
  from scripts.stage4.national_graph import sha
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source';p.write_bytes(b'unchanged source');self.assertEqual(sha(p),hashlib.sha256(b'unchanged source').hexdigest())
 def test_large_union_without_recursion(self):
  d=DSU()
  for i in range(100000):d.join(i,i+1)
  self.assertEqual(d.sizes(),[100001])
 def test_unknown_oneway_value(self):self.assertEqual(direction({'oneway':'reversible'}),'unknown')
 def test_unlicensed_manifest_refused(self):
  from scripts.stage4.national_graph import validate_manifest
  with self.assertRaises(ValueError):validate_manifest({'license':'unknown'})
 def test_invalid_checksum_refused(self):
  from scripts.stage4.national_graph import validate_manifest
  with self.assertRaises(ValueError):validate_manifest({'license':'ODbL-1.0','sha256':'bad'})
 def test_manifest_attribution_required(self):
  from scripts.stage4.national_graph import validate_manifest
  with self.assertRaises(ValueError):validate_manifest({'license':'ODbL-1.0','sha256':'0'*64})
 def test_incomplete_way_quarantined_without_gap_connection(self):
  import importlib.util
  if importlib.util.find_spec('osmium') is None:self.skipTest('full fixture executed in national CI with osmium')
  import tempfile,json,sqlite3,io,contextlib
  from pathlib import Path
  from scripts.stage4.national_graph import build,sha
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);source=p/'fixture.osm'
   source.write_text('<osm version="0.6"><node id="1" lat="32" lon="35" version="1"/><node id="3" lat="32.01" lon="35.01" version="1"/><way id="7" version="1"><nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="highway" v="residential"/><tag k="maxheight" v="3.1"/></way></osm>')
   m={'license':'ODbL-1.0','attribution':'synthetic unit fixture, not real evidence','sha256':sha(source),'snapshot_at':'2026-10-10T00:00:00Z'};(p/'manifest.json').write_text(json.dumps(m))
   with contextlib.redirect_stdout(io.StringIO()):build(source,p/'out',p/'manifest.json')
   with sqlite3.connect(p/'out/graph.sqlite') as db:
    self.assertEqual(db.execute('SELECT count(*) FROM segments').fetchone()[0],0)
    self.assertEqual(db.execute('SELECT geometry,status FROM candidates').fetchone(),('null','QUARANTINE'))
