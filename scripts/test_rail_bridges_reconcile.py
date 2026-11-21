"""Unit tests for rail_bridges_reconcile (synthetic data only, osmium not needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rail_bridges_reconcile as R  # noqa: E402

HEADER = "מספר,תיאור,שלב,מיקום,אחריות,קוד רשות תמרור,שם מסילה,האם רכבת מעל,כביש,הקטומטר\n"
CSV = HEADER + "\n".join([
    '1,x,a,עיר א,b,1,ק,כן,כביש 431,1',
    '2,x,a,עיר א,b,1,ק,כן,"כביש 6, כביש 444",2',
    '3,x,a,עיר ב,b,1,ק,לא,כביש 4,3',
    '4,x,a,עיר ב,b,1,ק,כן,רחוב הרצל,4',
    '5,x,a,עיר ג,b,1,ק,כן,כביש 99,5',
    '6,x,a,עיר ג,b,1,ק,כן,כביש 431,6',
]) + "\n"


def cr(refs, lon, lat, cl=None):
    return {"refs": refs, "name": "n", "lon": lon, "lat": lat,
            "clearance_raw": cl, "clearance_m": None}


class ParseTests(unittest.TestCase):
    def test_parse_roads(self):
        self.assertEqual(R.parse_roads("כביש 431"), ["431"])
        self.assertEqual(R.parse_roads("כביש 6, כביש 444"), ["6", "444"])
        self.assertEqual(R.parse_roads("רחוב הרצל"), [])
        self.assertEqual(R.parse_roads(""), [])
        self.assertEqual(R.parse_roads("כביש 04 / 4"), ["4"])

    def test_parse_refs(self):
        self.assertEqual(R.parse_refs("40;431"), ["40", "431"])
        self.assertEqual(R.parse_refs("A1"), [])
        self.assertEqual(R.parse_refs(None), [])

    def test_load_csv(self):
        rows, total = R.load_csv_rows(CSV)
        self.assertEqual(total, 6)
        self.assertEqual([r["id"] for r in rows], ["1", "2", "4", "5", "6"])
        self.assertEqual(rows[1]["roads"], ["6", "444"])

    def test_missing_column(self):
        with self.assertRaises(ValueError):
            R.load_csv_rows("a,b\n1,2\n")


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        rows, total = R.load_csv_rows(CSV)
        osm = [
            cr(["431"], 34.80000, 32.00000, "5.4"),
            cr(["431"], 34.80010, 32.00010),          # same site (other carriageway)
            cr(["431"], 34.90000, 32.10000),
            cr(["6"], 35.00000, 32.20000),
            cr(["1"], 35.10000, 31.80000),
            cr(["1"], 35.20000, 31.80000),
            cr([], 34.7, 32.0, "4.0"),
        ]
        self.out = R.reconcile(rows, total, osm)

    def test_counts(self):
        pr = self.out["per_road"]
        self.assertEqual(pr["431"]["csv_rows"], 2)
        self.assertEqual(pr["431"]["osm_crossings"], 3)
        self.assertEqual(pr["431"]["osm_sites"], 2)
        self.assertEqual(pr["431"]["osm_sites_with_clearance"], 1)
        self.assertEqual(pr["431"]["gap_without_clearance"], 1)
        self.assertEqual(self.out["osm"]["crossings_without_road_ref"],
                         {"total": 1, "with_clearance": 1})
        self.assertEqual(self.out["csv"]["rows_unparsed_road"], ["4"])

    def test_absent_lists(self):
        self.assertEqual(self.out["csv_rows_road_absent_in_osm"], [{"id": "5", "roads": ["99"]}])
        self.assertEqual(self.out["osm_roads_absent_in_csv"], {"1": 2})
        self.assertEqual(self.out["roads_in_both"], 2)

    def test_priority(self):
        pri = [p["road"] for p in self.out["priority"]]
        self.assertEqual(pri[0], "1")
        self.assertIn("99", pri)
        self.assertEqual(len(self.out["priority"][0]["osm_points_without_clearance"]), 2)

    def test_no_raw_text_leak(self):
        import json
        s = json.dumps(self.out, ensure_ascii=False)
        self.assertNotIn("עיר", s)
        self.assertNotIn("הרצל", s)


class SummarizeTests(unittest.TestCase):
    def test_summarize_with_geometry(self):
        bridges = {1: {"coords": [(0.0, -1.0), (0.0, 1.0)], "nodes": [1, 2], "layer": 1}}
        roads = {10: {"coords": [(-1.0, 0.0), (1.0, 0.0)], "nodes": [3, 4], "layer": 0,
                      "ref": "4", "name": "x", "mh": None, "mh_nodes": [((0.0, 0.0001), "4.2")]}}
        out = R.summarize_crossings(R.find_crossings(bridges, roads), roads)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["refs"], ["4"])
        self.assertAlmostEqual(out[0]["clearance_m"], 4.2)


if __name__ == "__main__":
    unittest.main()
