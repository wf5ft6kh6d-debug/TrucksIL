#!/usr/bin/env python3
"""Estimate clearance coverage UNDER bridges in an OSM .pbf extract.

In OSM the clearance under a bridge is tagged on the road passing below
(maxheight / maxheight:physical on the way, or on a node), not on the bridge.
This script finds road ways that cross a bridge in 2D without sharing a node
and checks whether those under-roads carry a clearance tag.

Usage:  python3 scripts/osm_bridge_clearance.py israel-and-palestine-latest.osm.pbf
Requires: pip install osmium   (only for main(); geometry helpers are pure Python)
Prints JSON aggregates only (no raw OSM data).
"""
import json
from array import array
import math
import re
import sys
from collections import Counter, defaultdict

CELL = 0.005  # grid cell size in degrees (~500 m)
NODE_RADIUS_M = 30.0
EXCLUDED = {"footway", "path", "cycleway", "steps", "construction", "proposed",
            "pedestrian", "bridleway", "corridor", "elevator", "platform", "raceway"}
CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary",
           "unclassified", "residential", "service", "track", "living_street", "road")
HEIGHT_TAGS = ("maxheight", "maxheight:physical")

NUM_M = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m)?\s*$")
FT_IN = re.compile(r"^\s*(\d+)\s*'\s*(?:(\d+)\s*\")?\s*$")
FT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*ft\s*$")


# ---------------------------------------------------------------- pure helpers
def parse_height(v):
    """Metres from a maxheight value, or None for non-numeric values."""
    if v is None:
        return None
    m = NUM_M.match(v.replace(",", "."))
    if m:
        return float(m.group(1))
    m = FT_IN.match(v)
    if m:
        return (int(m.group(1)) * 12 + int(m.group(2) or 0)) * 0.0254
    m = FT.match(v)
    if m:
        return float(m.group(1)) * 0.3048
    return None


def height_bucket(h):
    if h is None:
        return "non-numeric"
    if h < 2.0:
        return "<2.0 (suspect)"
    if h > 7.0:
        return ">7.0 (suspect)"
    for lo, hi in ((2.0, 3.5), (3.5, 4.0), (4.0, 4.5), (4.5, 5.0), (5.0, 5.5)):
        if h < hi:
            return f"{lo:.1f}-{hi:.1f}"
    return "5.5-7.0"


def hclass(h):
    if h in CLASSES:
        return h
    if h and h.endswith("_link") and h[:-5] in CLASSES:
        return h[:-5]
    return "other"


def parse_layer(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def layer_ok(bridge_layer, road_layer):
    """Road can pass under the bridge only if its layer is lower."""
    return road_layer < bridge_layer


def segment_intersection(p1, p2, q1, q2, eps=1e-12):
    """Intersection point of segments p1-p2 and q1-q2 (lon,lat tuples), or None.
    Collinear overlaps are ignored (not a pass-under)."""
    rx, ry = p2[0] - p1[0], p2[1] - p1[1]
    sx, sy = q2[0] - q1[0], q2[1] - q1[1]
    den = rx * sy - ry * sx
    if abs(den) < eps:
        return None
    qpx, qpy = q1[0] - p1[0], q1[1] - p1[1]
    t = (qpx * sy - qpy * sx) / den
    u = (qpx * ry - qpy * rx) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (p1[0] + t * rx, p1[1] + t * ry)
    return None


def haversine_m(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def cells_for_segment(a, b, cell=CELL):
    """Grid cells covered by the segment's bounding box."""
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    return [(i, j)
            for i in range(math.floor(x0 / cell), math.floor(x1 / cell) + 1)
            for j in range(math.floor(y0 / cell), math.floor(y1 / cell) + 1)]


class GridIndex:
    """Segments of bridge ways bucketed by grid cell."""

    def __init__(self, cell=CELL):
        self.cell = cell
        self.cells = defaultdict(list)

    def add_way(self, way_key, coords):
        for k in range(len(coords) - 1):
            for c in cells_for_segment(coords[k], coords[k + 1], self.cell):
                self.cells[c].append((way_key, k))

    def candidates(self, a, b):
        out = set()
        for c in cells_for_segment(a, b, self.cell):
            out.update(self.cells.get(c, ()))
        return out


def coords_of(w):
    """Coordinates as (lon,lat) tuples; ways may store a compact flat array."""
    c = w.get("coords")
    if c is not None:
        return c
    f = w["flat"]
    return list(zip(f[0::2], f[1::2]))


def find_crossings(bridges, roads, cell=CELL):
    """bridges/roads: dict key -> {"coords": [(lon,lat)], "nodes": [ids], "layer": int}.
    Returns {(bridge_key, road_key): first intersection point} for pairs that
    cross in 2D, share no node and have road layer < bridge layer."""
    idx = GridIndex(cell)
    bcoords = {k: coords_of(b) for k, b in bridges.items()}
    for k, c in bcoords.items():
        idx.add_way(k, c)
    node_sets = {}
    result = {}
    for rk, r in roads.items():
        rc = coords_of(r)
        rnodes = None
        for i in range(len(rc) - 1):
            for bk, j in idx.candidates(rc[i], rc[i + 1]):
                if (bk, rk) in result:
                    continue
                b = bridges[bk]
                if not layer_ok(b["layer"], r["layer"]):
                    continue
                p = segment_intersection(rc[i], rc[i + 1], bcoords[bk][j], bcoords[bk][j + 1])
                if p is None:
                    continue
                if rnodes is None:
                    rnodes = set(r["nodes"])
                bn = node_sets.get(bk)
                if bn is None:
                    bn = node_sets[bk] = set(b["nodes"])
                if rnodes & bn:
                    continue  # connected, not passing under
                result[(bk, rk)] = p
    return result


def nearby_heights(point, height_nodes, radius_m=NODE_RADIUS_M):
    """height_nodes: list of ((lon,lat), metres-or-None). Values within radius."""
    return [h for loc, h in height_nodes if haversine_m(point, loc) <= radius_m]


# ---------------------------------------------------------------- osmium part
def _make_handler():
    import osmium

    class H(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ts = 0
            self.mh_nodes = {}  # node id -> raw value
            self.bridges = {}
            self.roads = {}

        def _ts(self, o):
            t = int(o.timestamp.timestamp()) if o.timestamp else 0
            if t > self.ts:
                self.ts = t

        def node(self, n):
            self._ts(n)
            if len(n.tags) == 0:
                return
            for t in HEIGHT_TAGS:
                v = n.tags.get(t)
                if v:
                    self.mh_nodes[n.id] = v
                    break

        def way(self, w):
            self._ts(w)
            tags = w.tags
            hw = tags.get("highway")
            rw = tags.get("railway")
            br = tags.get("bridge")
            is_bridge = br is not None and br != "no"
            if hw is None and rw is None:
                return
            if hw in EXCLUDED and not (rw and is_bridge):
                return
            try:
                coords = [(n.lon, n.lat) for n in w.nodes]
            except Exception:  # missing locations at extract border
                return
            nodes = [n.ref for n in w.nodes]
            if len(coords) < 2:
                return
            if is_bridge:
                if hw is not None:
                    kind = "road"
                elif rw is not None and br == "yes":
                    kind = "rail"
                else:
                    return
                self.bridges[w.id] = {"coords": coords, "nodes": nodes, "kind": kind,
                                      "layer": parse_layer(tags.get("layer"), 1)}
                return
            if hw is None or tags.get("tunnel", "no") != "no" or tags.get("covered") == "yes":
                return
            mh = None
            for t in HEIGHT_TAGS:
                if tags.get(t):
                    mh = tags.get(t)
                    break
            hn = [((n.lon, n.lat), self.mh_nodes[n.ref]) for n in w.nodes
                  if n.ref in self.mh_nodes]
            flat = array("d", [v for xy in coords for v in xy])
            self.roads[w.id] = {"flat": flat, "nodes": array("q", nodes), "class": hclass(hw),
                                "layer": parse_layer(tags.get("layer"), 0),
                                "mh": mh, "mh_nodes": hn, "ref": tags.get("ref")}

    return H()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    import datetime
    h = _make_handler()
    h.apply_file(args[0], locations=True, idx="flex_mem")

    crossings = find_crossings(h.bridges, h.roads)
    bridges_over = {"road": set(), "rail": set()}
    by_class = defaultdict(Counter)
    src = Counter()
    buckets = Counter()
    values = Counter()
    for (bk, rk), p in crossings.items():
        b, r = h.bridges[bk], h.roads[rk]
        bridges_over[b["kind"]].add(bk)
        c = by_class[r["class"]]
        c["underpasses"] += 1
        c[f"under_{b['kind']}_bridge"] += 1
        raw = r["mh"]
        if raw:
            src["way_tag"] += 1
        else:
            near = [v for loc, v in r["mh_nodes"] if haversine_m(p, loc) <= NODE_RADIUS_M]
            raw = near[0] if near else None
            if raw:
                src["node_within_30m"] += 1
        if raw:
            c["with_clearance"] += 1
            m = parse_height(raw)
            buckets[height_bucket(m)] += 1
            values[f"{m:.2f}" if m is not None else raw] += 1

    total = len(crossings)
    with_cl = sum(c["with_clearance"] for c in by_class.values())
    out = {
        "max_object_timestamp_utc": datetime.datetime.fromtimestamp(
            h.ts, datetime.timezone.utc).isoformat(),
        "bridge_ways_collected": Counter(b["kind"] for b in h.bridges.values()),
        "bridges_over_roads": {k: len(v) for k, v in bridges_over.items()},
        "underpasses_total": total,
        "underpasses_with_clearance": with_cl,
        "underpasses_with_clearance_pct": round(100.0 * with_cl / total, 1) if total else None,
        "clearance_source": dict(src),
        "by_road_class_below": {k: dict(v) for k, v in sorted(by_class.items())},
        "clearance_buckets_m": dict(buckets),
        "clearance_top_values_m": dict(values.most_common(15)),
        "maxheight_nodes_total": len(h.mh_nodes),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=dict))


if __name__ == "__main__":
    main()
