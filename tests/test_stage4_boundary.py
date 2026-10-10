import tempfile
from pathlib import Path
import unittest
try:
 from shapely.geometry import LineString,box
 from scripts.stage4.boundary_audit import classify,load_poly
 AVAILABLE=True
except ImportError:AVAILABLE=False

@unittest.skipUnless(AVAILABLE,'Shapely dependency required')
class BoundaryAuditTests(unittest.TestCase):
 def test_outside_tail_of_crossing_way(self):
  self.assertEqual(classify(LineString([(2,0.5),(3,.5)]),LineString([(.5,.5),(2,.5),(3,.5)]),box(0,0,1,1)),'OUTSIDE_SEGMENT_OF_INTERSECTING_WAY')
 def test_fully_outside_parent_unknown(self):
  line=LineString([(2,.5),(3,.5)])
  self.assertEqual(classify(line,line,box(0,0,1,1)),'ENTIRE_WAY_OUTSIDE_SOURCE_POLYGON')
 def test_outside_midpoint_crossing(self):
  line=LineString([(.8,.5),(2,.5)])
  self.assertEqual(classify(line,line,box(0,0,1,1)),'SEGMENT_CROSSES_SOURCE_BOUNDARY')
 def test_touch_boundary(self):
  line=LineString([(1,.5),(2,.5)])
  self.assertEqual(classify(line,line,box(0,0,1,1)),'SEGMENT_TOUCHES_SOURCE_BOUNDARY')
 def test_boundary_midpoint_covered(self):
  line=LineString([(1,0),(1,1)])
  self.assertEqual(classify(line,line,box(0,0,1,1)),'MIDPOINT_COVERED')
 def test_poly_hole_and_disjoint_ring(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source.poly';p.write_text('source\n1\n0 0\n4 0\n4 4\n0 4\n0 0\nEND\n!2\n1 1\n2 1\n2 2\n1 2\n1 1\nEND\n3\n10 10\n11 10\n11 11\n10 11\n10 10\nEND\nEND\n')
   self.assertEqual(load_poly(p).area,16)

@unittest.skipUnless(AVAILABLE,'Shapely dependency required')
class OSMEvidenceTests(unittest.TestCase):
 def test_history_sanitization_and_visible_versions(self):
  from scripts.stage4.boundary_audit import sanitized_osm_history
  source=b'<osm><way id="7" version="1" visible="true" timestamp="2021-01-01T00:00:00Z" user="PRIVATE" uid="99" changeset="88"><nd ref="4"/><tag k="highway" v="trunk"/></way><way id="7" version="2" visible="false" timestamp="2022-01-01T00:00:00Z"/></osm>'
  result=sanitized_osm_history(source,'way')
  self.assertEqual([r['visible'] for r in result],['true','false'])
  self.assertEqual(result[0]['nodes'],['4'])
  self.assertNotIn('user',result[0]);self.assertNotIn('uid',result[0]);self.assertNotIn('changeset',result[0])
 def test_committed_missing_member_evidence_stays_quarantined(self):
  import json
  evidence=json.loads((Path(__file__).resolve().parents[1]/'data/stage4/boundary-osm-evidence.json').read_text())
  self.assertEqual(evidence['status'],'QUARANTINE')
  self.assertEqual(evidence['reconstruction'],'NOT PERFORMED')
  self.assertFalse(evidence['current_geometry_evidence']['way_intersects_source_polygon'])
  self.assertEqual(evidence['history_evidence'][0]['versions'][-1]['visible'],'true')
