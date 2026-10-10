"""Synthetic diagnostic fixtures only; never imported as road data."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/stage3'))
from research_gaps import proper_crossing, integer_point, append_crossing_check

class GapResearchTests(unittest.TestCase):
    def test_interior_crossing_orientation_invariant(self):
        self.assertTrue(proper_crossing((0,0),(2,2),(0,2),(2,0)))
        self.assertTrue(proper_crossing((2,2),(0,0),(2,0),(0,2)))
    def test_contacts_and_overlaps_are_not_interior_crossings(self):
        for c,d in [((2,2),(3,0)),((1,1),(2,0)),((1,1),(3,3))]:
            self.assertFalse(proper_crossing((0,0),(2,2),c,d))
    def test_precision_is_exact_or_rejected(self):
        self.assertEqual(integer_point((34.990000001,32.811)),(34990000001,32811000000))
        with self.assertRaises(ValueError): integer_point(('0.0000000001',0))
    def test_sql_keeps_existing_checks_and_rollback(self):
        result={'summary':{'proper_crossings_without_shared_node':0}}
        sql=append_crossing_check('BEGIN;\n-- existing checks\nROLLBACK;',result)
        self.assertIn('-- existing checks',sql)
        self.assertIn('ST_Crosses',sql)
        self.assertEqual(sql.count('ROLLBACK;'),1)
        self.assertTrue(sql.endswith('ROLLBACK;'))
        with self.assertRaises(ValueError): append_crossing_check('COMMIT;',result)
