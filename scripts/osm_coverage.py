#!/usr/bin/env python3
"""Measure truck-relevant restriction tags in an OSM extract (e.g. Geofabrik
israel-and-palestine-latest.osm.pbf). Prints aggregate counts only.

Usage: python3 scripts/osm_coverage.py path/to/extract.osm.pbf [--json]
Requires: pip install osmium

Israel vs West Bank/Gaza split is a crude approximation: a way's first node
is tested against rough bounding boxes (see REGIONS). It is NOT a legal or
precise boundary; mixed areas (Jerusalem, seam zone) will be misclassified.
"""
import json
import re
import sys
from collections import Counter, defaultdict

import osmium

TAGS = ["maxheight", "maxheight:physical", "maxwidth", "maxlength", "maxweight",
        "maxaxleload", "hgv", "hazmat"]
CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary", "residential"]
NON_ROAD = {"footway", "path", "cycleway", "steps", "pedestrian", "bridleway",
            "corridor", "proposed", "construction", "platform", "elevator"}

# Very rough polygons as (lon, lat) rings.
GAZA = [(34.21, 31.22), (34.57, 31.59), (34.50, 31.60), (34.20, 31.33)]
WEST_BANK = [(34.95, 31.35), (35.57, 31.35), (35.57, 32.55), (35.50, 32.55),
             (35.00, 32.45), (35.00, 32.10), (34.95, 31.85)]


def in_poly(lon, lat, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def region(lon, lat):
    if in_poly(lon, lat, GAZA):
        return "gaza"
    if in_poly(lon, lat, WEST_BANK):
        return "west_bank"
    return "israel"


NUM_M = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m)?\s*$")
FT_IN = re.compile(r"^\s*(\d+)\s*'\s*(?:(\d+)\s*\")?\s*$")
FT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*ft\s*$")


def parse_height(v):
    """Return (metres or None, unit label)."""
    m = NUM_M.match(v.replace(",", "."))
    if m:
        return float(m.group(1)), "m" if m.group(2) else "bare-number"
    m = FT_IN.match(v)
    if m:
        return (int(m.group(1)) * 12 + int(m.group(2) or 0)) * 0.0254, "ft/in"
    m = FT.match(v)
    if m:
        return float(m.group(1)) * 0.3048, "ft"
    return None, "non-numeric"


def hclass(h):
    if h in CLASSES:
        return h
    if h.endswith("_link") and h[:-5] in CLASSES:
        return h[:-5]
    return "other"


class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ts = 0
        self.tag_ways = Counter()
        self.tag_nodes = Counter()
        self.ways_by_class = Counter()
        self.mh_by_class = Counter()
        self.struct = defaultdict(Counter)  # bridge/tunnel/covered -> total/with_mh
        self.mh_values = Counter()
        self.mh_units = Counter()
        self.mh_buckets = Counter()
        self.mh_nonnum = Counter()
        self.region_ways = Counter()
        self.region_mh = Counter()
        self.mh_ways_total = 0

    def _ts(self, o):
        t = int(o.timestamp.timestamp()) if o.timestamp else 0
        if t > self.ts:
            self.ts = t

    def node(self, n):
        self._ts(n)
        for t in TAGS:
            if t in n.tags:
                self.tag_nodes[t] += 1

    def way(self, w):
        self._ts(w)
        h = w.tags.get("highway")
        if not h or h in NON_ROAD:
            return
        c = hclass(h)
        self.ways_by_class[c] += 1
        for t in TAGS:
            if t in w.tags:
                self.tag_ways[t] += 1
        mh = w.tags.get("maxheight") or w.tags.get("maxheight:physical")
        for s in ("bridge", "tunnel", "covered"):
            v = w.tags.get(s)
            if v and v != "no":
                self.struct[s]["total"] += 1
                if mh:
                    self.struct[s]["with_maxheight"] += 1
        try:
            loc = w.nodes[0].location
            r = region(loc.lon, loc.lat) if loc.valid() else "unknown"
        except Exception:
            r = "unknown"
        self.region_ways[r] += 1
        if mh:
            self.mh_ways_total += 1
            self.mh_by_class[c] += 1
            self.region_mh[r] += 1
            val, unit = parse_height(mh)
            self.mh_units[unit] += 1
            if val is None:
                self.mh_nonnum[mh.strip().lower()] += 1
            else:
                self.mh_values[round(val, 1)] += 1
                b = ("<2.0" if val < 2 else "2.0-3.0" if val < 3 else "3.0-4.0" if val < 4
                     else "4.0-4.5" if val < 4.5 else "4.5-5.0" if val < 5
                     else "5.0-7.0" if val <= 7 else ">7.0")
                self.mh_buckets[b] += 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    h = H()
    h.apply_file(args[0], locations=True, idx="flex_mem")
    import datetime
    out = {
        "max_object_timestamp_utc": datetime.datetime.fromtimestamp(h.ts, datetime.timezone.utc).isoformat(),
        "highway_ways_by_class": dict(h.ways_by_class),
        "maxheight_ways_by_class": dict(h.mh_by_class),
        "tag_counts_ways": dict(h.tag_ways),
        "tag_counts_nodes": dict(h.tag_nodes),
        "structures": {k: dict(v) for k, v in h.struct.items()},
        "maxheight_units": dict(h.mh_units),
        "maxheight_buckets_m": dict(h.mh_buckets),
        "maxheight_non_numeric": dict(h.mh_nonnum.most_common(15)),
        "maxheight_top_values_m": dict(h.mh_values.most_common(15)),
        "region_highway_ways": dict(h.region_ways),
        "region_maxheight_ways": dict(h.region_mh),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
