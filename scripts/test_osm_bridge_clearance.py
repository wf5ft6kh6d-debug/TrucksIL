"""Unit tests for pure geometry helpers in osm_bridge_clearance (no osmium)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import osm_bridge_clearance as m  # noqa: E402


def way(coords, nodes, layer, **kw):
    d = {"coords": coords, "nodes": nodes, "layer": layer}
    d.update(kw)
    return d


class Geometry(unittest.TestCase):
    def test_cross(self):
        p = m.segment_intersection((0, 0), (1, 1), (0, 1), (1, 0))
        self.assertAlmostEqual(p[0], 0.5)
        self.assertAlmostEqual(p[1], 0.5)

    def test_no_cross_and_parallel(self):
        self.assertIsNone(m.segment_intersection((0, 0), (1, 0), (0, 1), (1, 1)))
        self.assertIsNone(m.segment_intersection((0, 0), (1, 0), (0.5, 0), (2, 0)))
        self.assertIsNone(m.segment_intersection((0, 0), (1, 1), (2, 0), (1.6, 0.4)))

    def test_haversine(self):
        d = m.haversine_m((34.78, 32.08), (34.78, 32.09))
        self.assertAlmostEqual(d, 1112, delta=3)

    def test_cells(self):
        cells = m.cells_for_segment((34.7801, 32.0001), (34.7911, 32.0001), 0.005)
        self.assertEqual(len(cells), 3)

    def test_parse_height(self):
        self.assertEqual(m.parse_height("4.5"), 4.5)
        self.assertEqual(m.parse_height("4,2 m"), 4.2)
        self.assertAlmostEqual(m.parse_height("13'6\""), 4.1148, places=3)
        self.assertIsNone(m.parse_height("default"))
        self.assertEqual(m.height_bucket(4.2), "4.0-4.5")
        self.assertEqual(m.height_bucket(1.5), "<2.0 (suspect)")

    def test_layer(self):
        self.assertEqual(m.parse_layer(None, 1), 1)
        self.assertEqual(m.parse_layer("-1"), -1)
        self.assertTrue(m.layer_ok(1, 0))
        self.assertFalse(m.layer_ok(0, 0))


class Crossings(unittest.TestCase):
    def setUp(self):
        # bridge west-east at lat 32.0005 across lon 34.780..34.790 (crosses grid cells)
        self.bridges = {1: way([(34.780, 32.0005), (34.790, 32.0005)], [10, 11], 1)}

    def test_pass_under(self):
        roads = {2: way([(34.7851, 31.999), (34.7851, 32.002)], [20, 21], 0)}
        res = m.find_crossings(self.bridges, roads)
        self.assertEqual(list(res), [(1, 2)])
        self.assertAlmostEqual(res[(1, 2)][0], 34.7851)

    def test_shared_node_is_connection(self):
        roads = {2: way([(34.780, 32.0005), (34.780, 32.002)], [10, 21], 0)}
        self.assertEqual(m.find_crossings(self.bridges, roads), {})

    def test_same_layer_excluded(self):
        roads = {2: way([(34.7851, 31.999), (34.7851, 32.002)], [20, 21], 1)}
        self.assertEqual(m.find_crossings(self.bridges, roads), {})

    def test_far_road(self):
        roads = {2: way([(35.0, 31.0), (35.1, 31.1)], [20, 21], 0)}
        self.assertEqual(m.find_crossings(self.bridges, roads), {})

    def test_flat_storage_and_multi_segment(self):
        roads = {3: {"flat": [34.783, 31.99, 34.783, 32.0, 34.783, 32.01],
                     "nodes": [30, 31, 32], "layer": -1}}
        self.assertEqual(list(m.find_crossings(self.bridges, roads)), [(1, 3)])

    def test_nearby_heights(self):
        p = (34.7851, 32.0005)
        nodes = [((34.7851, 32.0007), 4.3), ((34.7851, 32.002), 3.9)]  # ~22 m, ~167 m
        self.assertEqual(m.nearby_heights(p, nodes), [4.3])


if __name__ == "__main__":
    unittest.main()
