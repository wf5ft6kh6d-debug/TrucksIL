#!/usr/bin/env python3
"""Reconcile MoT "road-rail grade separations" (rail over road) with OSM rail bridges.

Usage:  python3 scripts/rail_bridges_reconcile.py LEVELSEPARATION.csv israel.osm.pbf > rail_reconcile.json
Requires: pip install osmium   (only for the OSM part; parsing/matching is pure Python)

The MoT layer (LEVELSEPARATION.csv) has NO coordinates and NO heights, so matching
is by road number only. Output: JSON aggregates; from the MoT file only the row id
("מספר") and parsed road numbers are emitted (raw file must not be committed, ADR-0007).
OSM points are rounded and stay local (ODbL, do not commit the output).
"""
import csv
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osm_bridge_clearance import (  # noqa: E402
    EXCLUDED, HEIGHT_TAGS, NODE_RADIUS_M, find_crossings, haversine_m, parse_height, parse_layer)

COL_ID, COL_RAIL_OVER, COL_ROAD = "מספר", "האם רכבת מעל", "כביש"
YES = "כן"
SITE_CELL = 0.002  # ~200 m: merge carriageways / multi-way pairs into one "site"
MAX_POINTS = 20
ROAD_TOKEN = re.compile(r"\d+")


# ---------------------------------------------------------------- CSV side
def parse_roads(value):
    """'כביש 431' -> ['431']; 'כביש 6, כביש 444' -> ['6','444']; non-numeric -> []."""
    if not value:
        return []
    out = []
    for t in ROAD_TOKEN.findall(value):
        t = str(int(t))
        if t not in out:
            out.append(t)
    return out


def read_csv_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1255"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_csv_rows(text):
    """Rail-over-road rows as [{'id': str, 'roads': [str]}] plus total row count."""
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [(f or "").strip() for f in reader.fieldnames or []]
    missing = [c for c in (COL_ID, COL_RAIL_OVER, COL_ROAD) if c not in reader.fieldnames]
    if missing:
        raise ValueError(f"CSV columns missing: {missing}")
    rows, total = [], 0
    for r in reader:
        total += 1
        if (r.get(COL_RAIL_OVER) or "").strip() != YES:
            continue
        rows.append({"id": (r.get(COL_ID) or "").strip(), "roads": parse_roads(r.get(COL_ROAD))})
    return rows, total


# ---------------------------------------------------------------- OSM side
def parse_refs(ref):
    """OSM ref '40;431' -> ['40','431']; non-numeric parts dropped."""
    if not ref:
        return []
    out = []
    for part in re.split(r"[;,]", ref):
        part = part.strip()
        if part.isdigit():
            p = str(int(part))
            if p not in out:
                out.append(p)
    return out


def summarize_crossings(crossings, roads):
    """crossings: {(bridge_key, road_key): (lon,lat)}; roads: key -> {ref, name, mh, mh_nodes}.
    Returns list of {refs, name, lat, lon, clearance_m, clearance_raw}."""
    out = []
    for (_bk, rk), p in crossings.items():
        r = roads[rk]
        raw = r.get("mh")
        if not raw:
            near = [v for loc, v in r.get("mh_nodes", []) if haversine_m(p, loc) <= NODE_RADIUS_M]
            raw = near[0] if near else None
        out.append({"refs": parse_refs(r.get("ref")), "name": r.get("name"),
                    "lon": round(p[0], 5), "lat": round(p[1], 5),
                    "clearance_raw": raw, "clearance_m": parse_height(raw) if raw else None})
    return out


def _site(c):
    return (round(c["lon"] / SITE_CELL), round(c["lat"] / SITE_CELL))


# ---------------------------------------------------------------- matching
def reconcile(csv_rows, csv_total, osm_crossings):
    per = defaultdict(lambda: {"csv_rows": 0, "osm_crossings": 0, "osm_with_clearance": 0,
                               "osm_sites": set(), "osm_sites_with_clearance": set(),
                               "names": Counter(), "points_without_clearance": []})
    unparsed = []
    for row in csv_rows:
        if not row["roads"]:
            unparsed.append(row["id"])
        for rd in row["roads"]:
            per[rd]["csv_rows"] += 1
    no_ref = Counter()
    for c in osm_crossings:
        if not c["refs"]:
            no_ref["total"] += 1
            if c["clearance_raw"]:
                no_ref["with_clearance"] += 1
            continue
        for rd in c["refs"]:
            p = per[rd]
            p["osm_crossings"] += 1
            p["osm_sites"].add(_site(c))
            if c["name"]:
                p["names"][c["name"]] += 1
            if c["clearance_raw"]:
                p["osm_with_clearance"] += 1
                p["osm_sites_with_clearance"].add(_site(c))
            elif len(p["points_without_clearance"]) < MAX_POINTS:
                p["points_without_clearance"].append([c["lat"], c["lon"]])

    per_road = {}
    for rd, p in per.items():
        sites, sites_cl = len(p["osm_sites"]), len(p["osm_sites_with_clearance"])
        per_road[rd] = {
            "csv_rows": p["csv_rows"], "osm_crossings": p["osm_crossings"],
            "osm_with_clearance": p["osm_with_clearance"],
            "osm_sites": sites, "osm_sites_with_clearance": sites_cl,
            # expected rail-over crossings on this road (best of two sources) minus known clearances
            "gap_without_clearance": max(p["csv_rows"], sites) - sites_cl,
            "osm_name": p["names"].most_common(1)[0][0] if p["names"] else None,
        }

    def key(rd):
        return int(rd)

    csv_absent = [{"id": row["id"], "roads": row["roads"]} for row in csv_rows
                  if row["roads"] and all(per_road[r]["osm_crossings"] == 0 for r in row["roads"])]
    osm_absent = {rd: v["osm_crossings"] for rd, v in sorted(per_road.items(), key=lambda kv: key(kv[0]))
                  if v["csv_rows"] == 0 and v["osm_crossings"] > 0}
    prio = sorted((rd for rd, v in per_road.items() if v["gap_without_clearance"] > 0),
                  key=lambda rd: (-per_road[rd]["gap_without_clearance"],
                                  -per_road[rd]["csv_rows"], key(rd)))
    priority = [dict(road=rd, **{k: per_road[rd][k] for k in (
        "gap_without_clearance", "csv_rows", "osm_sites", "osm_sites_with_clearance", "osm_name")},
        osm_points_without_clearance=per[rd]["points_without_clearance"]) for rd in prio]

    total_osm = len(osm_crossings)
    with_cl = sum(1 for c in osm_crossings if c["clearance_raw"])
    roads_both = sum(1 for v in per_road.values() if v["csv_rows"] and v["osm_crossings"])
    return {
        "method": "match by road number only (MoT layer has no coordinates/heights); "
                  "osm_sites = crossings merged on a ~200 m grid",
        "csv": {"rows_total": csv_total, "rail_over_road_rows": len(csv_rows),
                "rows_unparsed_road": unparsed,
                "roads": len({r for row in csv_rows for r in row["roads"]})},
        "osm": {"rail_bridge_road_crossings": total_osm, "with_clearance": with_cl,
                "crossings_without_road_ref": dict(no_ref),
                "roads_with_ref": sum(1 for v in per_road.values() if v["osm_crossings"])},
        "roads_in_both": roads_both,
        "per_road": dict(sorted(per_road.items(), key=lambda kv: key(kv[0]))),
        "csv_rows_road_absent_in_osm": csv_absent,
        "osm_roads_absent_in_csv": osm_absent,
        "priority": priority,
    }


# ---------------------------------------------------------------- osmium part
def _make_handler():
    import osmium
    from array import array

    class H(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.mh_nodes, self.bridges, self.roads = {}, {}, {}

        def node(self, n):
            for t in HEIGHT_TAGS:
                v = n.tags.get(t)
                if v:
                    self.mh_nodes[n.id] = v
                    break

        def way(self, w):
            tags = w.tags
            hw, rw, br = tags.get("highway"), tags.get("railway"), tags.get("bridge")
            if rw == "rail" and br == "yes":
                kind = "rail"
            elif hw and hw not in EXCLUDED and (br is None or br == "no") \
                    and tags.get("tunnel", "no") == "no" and tags.get("covered") != "yes":
                kind = "road"
            else:
                return
            try:
                coords = [(n.lon, n.lat) for n in w.nodes]
            except Exception:
                return
            if len(coords) < 2:
                return
            nodes = array("q", [n.ref for n in w.nodes])
            flat = array("d", [v for xy in coords for v in xy])
            if kind == "rail":
                self.bridges[w.id] = {"flat": flat, "nodes": nodes,
                                      "layer": parse_layer(tags.get("layer"), 1)}
                return
            mh = next((tags.get(t) for t in HEIGHT_TAGS if tags.get(t)), None)
            self.roads[w.id] = {
                "flat": flat, "nodes": nodes, "layer": parse_layer(tags.get("layer"), 0),
                "ref": tags.get("ref"), "name": tags.get("name:he") or tags.get("name"), "mh": mh,
                "mh_nodes": [((n.lon, n.lat), self.mh_nodes[n.ref]) for n in w.nodes
                             if n.ref in self.mh_nodes]}

    return H()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    rows, total = load_csv_rows(read_csv_text(args[0]))
    h = _make_handler()
    h.apply_file(args[1], locations=True, idx="flex_mem")
    crossings = summarize_crossings(find_crossings(h.bridges, h.roads), h.roads)
    print(json.dumps(reconcile(rows, total, crossings), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
