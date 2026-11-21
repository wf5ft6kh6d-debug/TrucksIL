"""Unit tests for import_osm_truck_poi (synthetic OSM objects; no osmium, no DB)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_osm_truck_poi as p  # noqa: E402

EXTRACT = "2026-11-20T21:14:03Z"
OBJECTS = [
    ("node", 5, {"amenity": "parking", "hgv": "designated", "name": "חניון משאיות"}, (34.8, 32.1)),
    ("node", 6, {"amenity": "parking"}, (34.8, 32.1)),                       # no hgv -> ignored
    ("node", 7, {"amenity": "parking", "hgv": "no"}, (34.8, 32.1)),          # ignored
    ("node", 8, {"amenity": "fuel", "hgv": "yes", "name:en": "Fuel"}, (34.9, 32.0)),
    ("node", 9, {"amenity": "fuel"}, (34.9, 32.0)),                          # ignored
    ("way", 40, {"highway": "rest_area", "amenity": "parking", "hgv": "yes"},
     None),                                                                   # no geometry
    ("way", 30, {"highway": "rest_area", "name": "Rest\tA"}, (35.0, 31.5)),
]


class Classify(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(p.classify({"amenity": "parking", "hgv": "yes"}), ["parking"])
        self.assertEqual(p.classify({"amenity": "parking", "hgv": "designated"}), ["parking"])
        self.assertEqual(p.classify({"amenity": "parking", "hgv": "no"}), [])
        self.assertEqual(p.classify({"amenity": "parking"}), [])
        self.assertEqual(p.classify({"highway": "rest_area"}), ["rest_area"])
        self.assertEqual(p.classify({"amenity": "fuel", "hgv": "yes"}), ["fuel_hgv"])
        self.assertEqual(p.classify({"amenity": "fuel"}), [])
        self.assertEqual(p.classify({"highway": "rest_area", "amenity": "parking", "hgv": "yes"}), ["parking", "rest_area"])

    def test_centroid(self):
        self.assertEqual(p.centroid([(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]), (1, 1))
        self.assertEqual(p.centroid([(1, 1), (3, 3)]), (2, 2))
        self.assertIsNone(p.centroid([]))


class Records(unittest.TestCase):
    def setUp(self):
        self.recs, self.stats = p.make_records(OBJECTS, EXTRACT)
        self.by_id = {r["id"]: r for r in self.recs}

    def test_ids_and_stats(self):
        self.assertEqual(sorted(self.by_id), ["osm-poi-node5-parking", "osm-poi-node8-fuel_hgv", "osm-poi-way30-rest_area"])
        self.assertEqual(self.stats["skipped_no_geometry"], 1)
        self.assertEqual(self.stats["records"], 3)
        self.assertEqual(p.make_records(list(reversed(OBJECTS)), EXTRACT)[0], self.recs)  # stable order

    def test_fields(self):
        r = self.by_id["osm-poi-node5-parking"]
        self.assertEqual((r["kind"], r["name"], r["status"], r["position"]), ("parking", "חניון משאיות", "unverified", [34.8, 32.1]))
        self.assertEqual(self.by_id["osm-poi-node8-fuel_hgv"]["name"], "Fuel")
        self.assertEqual(r["sourceExtractDate"], EXTRACT)

    def test_sql(self):
        sql = p.to_psql_script(self.recs)
        self.assertIn("BEGIN;", sql)
        self.assertLess(sql.index("\\."), sql.index("DELETE FROM truck_poi;"))
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))
        rows = sql.split("FROM STDIN;\n")[1].split("\n\\.")[0].split("\n")
        self.assertEqual(len(rows), 3)
        cols = rows[2].split("\t")
        self.assertEqual(len(cols), len(p.STAGE_COLUMNS))
        self.assertEqual(cols[4], "Rest\\tA")  # tab escaped for COPY
        self.assertEqual(json.loads(rows[0].split("\t")[7])["hgv"], "designated")
        self.assertEqual(p.to_psql_script([]).count("COPY"), 1)


if __name__ == "__main__":
    unittest.main()
