"""Synthetic fixtures test algorithms, never added to the source dataset."""
import unittest
from scripts.stage4.geometry_audit import relation,classify

class GeometryAuditTests(unittest.TestCase):
    def test_exact_cross(self):
        self.assertEqual(relation((0,0),(2,2),(0,2),(2,0)),'cross')
    def test_exact_overlap(self):
        self.assertEqual(relation((0,0),(4,0),(2,0),(6,0)),'overlap')
    def test_distinct_parallel(self):
        self.assertIsNone(relation((0,0),(4,0),(0,1),(4,1)))
    def test_t_touch(self):
        self.assertEqual(relation((0,0),(4,0),(2,0),(2,2)),'touch')
    def test_valid_closed_ring(self):
        r=classify([1,2,3,4,1],[(0,0),(1,0),(1,1),(0,1),(0,0)])
        self.assertTrue(r['exact_simple']);self.assertTrue(r['shapely_simple'])
        self.assertEqual(r['counts']['repeated_coordinates'],0)
    def test_retraced_geometry(self):
        r=classify([1,2,1,3],[(0,0),(1,0),(0,0),(0,1)])
        self.assertFalse(r['exact_simple']);self.assertFalse(r['shapely_simple']);self.assertGreater(r['counts']['overlap'],0)
    def test_bowtie(self):
        r=classify([1,2,3,4],[(0,0),(1,1),(0,1),(1,0)])
        self.assertEqual(r['counts']['cross'],1);self.assertFalse(r['exact_simple']);self.assertFalse(r['shapely_simple'])
    def test_duplicate_coordinate_distinct_ids(self):
        r=classify([1,2,3,4,5],[(0,0),(1,0),(0,0),(0,1),(1,1)])
        self.assertEqual(r['counts']['repeated_coordinates'],1);self.assertEqual(r['counts']['repeated_node_ids'],0)
    def test_consecutive_duplicate_does_not_imply_non_simple(self):
        r=classify([1,1,2],[(0,0),(0,0),(1,0)])
        self.assertEqual(r['counts']['degenerate_pairs'],1);self.assertTrue(r['exact_simple']);self.assertTrue(r['shapely_simple'])
    def test_missing_node_fails_instead_of_invented_coordinate(self):
        with self.assertRaises((TypeError,ValueError)):classify([1,2],[(0,0),None])

if __name__=='__main__':unittest.main()
