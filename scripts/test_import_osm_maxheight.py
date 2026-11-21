"""Unit tests for import_osm_maxheight (synthetic OSM objects; no osmium, no DB)."""
import json
import os
import shutil
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_osm_maxheight as m  # noqa: E402

EXTRACT = "2026-11-20T21:14:03Z"
WAYS = {
    7: {"tags": {"highway": "primary", "maxheight": "4.2 m", "source:maxheight": "sign"},
        "coords": [(34.79, 32.005), (34.81, 32.005)], "bridge": False},        # under a bridge
    8: {"tags": {"highway": "secondary", "tunnel": "yes", "maxheight": "13'6\"", "oneway": "yes"},
        "coords": [(34.70, 32.0), (34.71, 32.0)], "bridge": False},
    9: {"tags": {"highway": "service", "maxheight": "default", "maxheight:physical": "3.1"},
        "coords": [(34.72, 32.0), (34.73, 32.0)], "bridge": False},
    10: {"tags": {"highway": "residential", "maxheight": "none"}, "coords": [(34.74, 32.0), (34.75, 32.0)], "bridge": False},
    11: {"tags": {"highway": "residential", "maxheight": "1.5"}, "coords": [(34.74, 32.1), (34.75, 32.1)], "bridge": False},
    12: {"tags": {"highway": "primary", "bridge": "yes", "maxheight": "4.5"}, "coords": [(34.76, 32.0), (34.77, 32.0)], "bridge": True},
    13: {"tags": {"highway": "tertiary", "maxheight": "12", "oneway": "-1", "maxheight:signed": "yes"},
         "coords": [(34.78, 32.2), (34.79, 32.2)], "bridge": False},
}
NODES = {
    500: {"tags": {"maxheight": "3.8"}, "loc": (34.8001, 32.005), "way_ids": [70, 7]},
    501: {"tags": {"maxheight": "4"}, "loc": (34.9, 32.0), "way_ids": []},  # barrier not on a highway
    502: {"tags": {"maxheight:physical": "4.05", "maxheight": "below_default"}, "loc": (34.91, 32.0), "way_ids": [3]},
}
CROSSINGS = {(100, 7): (34.8, 32.005), (101, 7): (34.805, 32.005), (102, 99): (34.0, 32.0)}


class Parsing(unittest.TestCase):
    def test_values(self):
        c = Counter()
        self.assertEqual(m.choose_height({"maxheight": "4.2"}, c), (4.2, "unknown", "maxheight"))
        self.assertEqual(m.choose_height({"maxheight": "4.2 m"}, c)[0], 4.2)
        self.assertEqual(m.choose_height({"maxheight": "4,35"}, c)[0], 4.35)
        self.assertEqual(m.choose_height({"maxheight": "13'6\""}, c)[0], 4.11)
        self.assertEqual(m.choose_height({"maxheight": "14 ft"}, c)[0], 4.27)
        self.assertEqual(m.choose_height({"maxheight": "4.2", "source:maxheight": "sign"}, c)[1], "posted_sign")
        self.assertEqual(m.choose_height({"maxheight": "4.2", "maxheight:signed": "yes"}, c)[1], "posted_sign")
        self.assertEqual(c, Counter())

    def test_posted_preferred_over_physical(self):
        self.assertEqual(m.choose_height({"maxheight": "4.0", "maxheight:physical": "4.3"}), (4.0, "unknown", "maxheight"))
        self.assertEqual(m.choose_height({"maxheight:physical": "4.3"}), (4.3, "measured", "maxheight:physical"))

    def test_skips_counted(self):
        c = Counter()
        for v in ("default", "none", "below_default", "1.9", "7.5", "abc"):
            self.assertIsNone(m.choose_height({"maxheight": v}, c))
        self.assertEqual(c, Counter({"skipped_non_numeric": 4, "skipped_outlier_low": 1, "skipped_outlier_high": 1}))

    def test_direction(self):
        self.assertEqual([m.direction_of({"oneway": v}) for v in ("yes", "-1", "no")], ["forward", "backward", "both"])
        self.assertEqual(m.direction_of({}), "both")


class Records(unittest.TestCase):
    def setUp(self):
        self.recs, self.stats = m.build_records(WAYS, NODES, CROSSINGS, EXTRACT)
        self.by_id = {r["id"]: r for r in self.recs}

    def test_ids_and_counts(self):
        self.assertEqual(sorted(self.by_id), [
            "osm-maxheight-node500", "osm-maxheight-node502",
            "osm-maxheight-way7-crossing100", "osm-maxheight-way7-crossing101",
            "osm-maxheight-way8", "osm-maxheight-way9"])
        self.assertEqual((self.stats["crossing"], self.stats["way"], self.stats["node"]), (2, 2, 2))
        self.assertEqual(self.stats["skipped_bridge_way"], 1)
        self.assertEqual(self.stats["skipped_node_not_on_highway"], 1)
        self.assertEqual(self.stats["skipped_non_numeric"], 1)   # way 10 'none'
        self.assertEqual(self.stats["skipped_outlier_low"], 1)   # way 11
        self.assertEqual(self.stats["skipped_outlier_high"], 1)  # way 13
        # stable: same input -> same output
        self.assertEqual(m.build_records(WAYS, NODES, CROSSINGS, EXTRACT)[0], self.recs)

    def test_crossing_record(self):
        r = self.by_id["osm-maxheight-way7-crossing100"]
        self.assertEqual(r["geometry"], {"type": "Point", "coordinates": [34.8, 32.005]})
        self.assertEqual((r["roadSegmentId"], r["direction"], r["value"], r["valueSource"]), ("osm:way:7", "both", 4.2, "posted_sign"))
        self.assertEqual(r["source"], {"name": "OpenStreetMap contributors", "reference": "osm:way/7@2026-11-20",
                                       "url": "https://www.openstreetmap.org/way/7", "license": "ODbL-1.0"})
        self.assertEqual((r["status"], r["restrictionType"], r["unit"], r["observedAt"]), ("unverified", "max_height", "m", EXTRACT))
        self.assertNotIn("osm-maxheight-way7", self.by_id)  # no LineString for a way with crossings

    def test_way_and_node_records(self):
        w = self.by_id["osm-maxheight-way8"]
        self.assertEqual((w["geometry"]["type"], w["direction"], w["value"]), ("LineString", "forward", 4.11))
        self.assertEqual(self.by_id["osm-maxheight-way9"]["valueSource"], "measured")
        n = self.by_id["osm-maxheight-node500"]
        self.assertEqual((n["roadSegmentId"], n["geometry"]["type"], n["source"]["url"]),
                         ("osm:way:7", "Point", "https://www.openstreetmap.org/node/500"))
        self.assertEqual(self.by_id["osm-maxheight-node502"]["valueSource"], "measured")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_schema_valid(self):
        self.assertEqual(m.validate(self.recs)["valid"], len(self.recs))
        bad = dict(self.recs[0], value=0)
        with self.assertRaises(RuntimeError):
            m.validate([bad])

    def test_sql(self):
        sql = m.to_psql_script(self.recs)
        self.assertIn("BEGIN;", sql)
        self.assertIn("DELETE FROM restrictions WHERE id LIKE 'osm-maxheight-%';", sql)
        self.assertLess(sql.index("\\."), sql.index("DELETE FROM restrictions"))
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))
        self.assertNotIn("TRUNCATE", sql)
        rows = sql.split("FROM STDIN;\n")[1].split("\n\\.")[0].split("\n")
        self.assertEqual(len(rows), len(self.recs))
        first = rows[0].split("\t")
        self.assertEqual(len(first), len(m.STAGE_COLUMNS))
        self.assertEqual(json.loads(first[2])["type"], "Point")


if __name__ == "__main__":
    unittest.main()
