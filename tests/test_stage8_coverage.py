"""SYNTHETIC coverage fixtures: never national restriction evidence."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from scripts.stage8.coverage import inventory, REGIONS, sha256


class Coverage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'synthetic.sqlite'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE ways(id INTEGER, tags TEXT)')
            db.execute('CREATE TABLE segments(way_id INTEGER,direction TEXT)')
            db.executemany('INSERT INTO ways VALUES(?,?)', [(1,json.dumps({'highway':'motorway'})),(2,'{}'),(3,json.dumps({'highway':'footway'}))])
            db.executemany('INSERT INTO segments VALUES(?,?)', [(1,'both'),(1,'forward'),(2,'unknown'),(3,'both')])
        self.matrix = [dict(region=r, records=0) for r in REGIONS]
    def test_counts_source_segments_not_directed_arcs(self):
        r = inventory(self.path, self.matrix)
        self.assertEqual((r['source_way_count'],r['source_segment_count']),(3,4))
        self.assertEqual(next(x for x in r['road_classes'] if x['road_class']=='motorway')['source_segments'],2)
    def test_excluded_and_missing_class_preserved(self):
        self.assertEqual({r['road_class'] for r in inventory(self.path,self.matrix)['road_classes']},{'motorway','footway','UNKNOWN'})
    def test_no_regional_zero_or_country_inference(self):
        r=inventory(self.path,self.matrix)
        self.assertEqual(len(r['region_road_classes']),18)
        self.assertTrue(all(x['source_way_denominator'] is None and x['verified_restrictions'] is None for x in r['region_road_classes']))
        self.assertFalse(r['legal_boundary_reference'])
    def test_orphan_segment_rejected(self):
        with sqlite3.connect(self.path) as db: db.execute('INSERT INTO segments VALUES(999,"both")')
        with self.assertRaisesRegex(ValueError,'orphan'): inventory(self.path,self.matrix)
    def test_missing_and_duplicate_regions_rejected(self):
        for matrix in (self.matrix[:-1],self.matrix+self.matrix[:1]):
            with self.assertRaises(ValueError): inventory(self.path,matrix)
    def test_repeat_and_input_preservation(self):
        before=sha256(self.path)
        self.assertEqual(inventory(self.path,self.matrix),inventory(self.path,self.matrix))
        self.assertEqual(before,sha256(self.path))
