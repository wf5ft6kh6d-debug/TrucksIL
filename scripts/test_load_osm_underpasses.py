"""Unit tests for pure parts of load_osm_underpasses (synthetic ways, no osmium, no DB)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import load_osm_underpasses as m  # noqa: E402
import osm_bridge_clearance as obc  # noqa: E402

BRIDGES = {100: {"coords": [(34.80, 32.00), (34.80, 32.01)], "nodes": [1, 2], "layer": 1, "kind": "rail"}}
ROADS = {
    7: {"coords": [(34.79, 32.005), (34.81, 32.005)], "nodes": [3, 4], "layer": 0, "class": "primary",
        "mh": None, "mh_nodes": [((34.8001, 32.005), "4.2")], "ref": "4"},
    8: {"coords": [(34.79, 32.008), (34.81, 32.008)], "nodes": [5, 6], "layer": 0, "class": "residential",
        "mh": None, "mh_nodes": [], "ref": None},
    9: {"coords": [(34.79, 32.009), (34.81, 32.009)], "nodes": [2, 6], "layer": 0, "class": "service",
        "mh": "default", "mh_nodes": [], "ref": None},  # shares a node with the bridge: not under it
}


class Rows(unittest.TestCase):
    def setUp(self):
        self.rows = m.build_rows(BRIDGES, ROADS, obc.find_crossings(BRIDGES, ROADS), "2026-11-01T00:00:00+00:00")

    def test_crossings(self):
        self.assertEqual([(r["osm_road_way_id"], r["osm_bridge_way_id"]) for r in self.rows], [(7, 100), (8, 100)])
        r = self.rows[0]
        self.assertEqual((r["bridge_kind"], r["road_ref"], r["road_class"]), ("rail", "4", "primary"))
        self.assertEqual(r["geom"], "SRID=4326;POINT(34.8000000 32.0050000)")

    def test_maxheight_candidate(self):
        self.assertEqual((self.rows[0]["osm_maxheight_text"], self.rows[0]["osm_maxheight_m"]), ("4.2", 4.2))
        self.assertIsNone(self.rows[1]["osm_maxheight_text"])
        self.assertIsNone(self.rows[1]["osm_maxheight_m"])
        self.assertEqual(m.maxheight_for({"mh": "default"}, (0, 0)), "default")
        self.assertIsNone(obc.parse_height("default"))

    def test_psql_script(self):
        s = m.to_psql_script(self.rows + [dict(self.rows[1], road_ref="a\tb\\c")])
        lines = s.split("\n")
        self.assertEqual(lines[1:3], ["BEGIN;", "TRUNCATE osm_underpasses RESTART IDENTITY;"])
        self.assertTrue(lines[3].startswith("COPY osm_underpasses (osm_road_way_id,"))
        self.assertEqual(lines[4].split("\t")[:3], ["7", "100", "rail"])
        self.assertIn("\\N", lines[5].split("\t"))
        self.assertIn("a\\tb\\\\c", lines[6])
        self.assertEqual(lines[-3:], ["\\.", "COMMIT;", ""])


if __name__ == "__main__":
    unittest.main()
