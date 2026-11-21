#!/usr/bin/env python3
"""Import OSM height limits (maxheight) into TrucksIL `restrictions` as UNVERIFIED candidates (ADR-0006).

Usage:
  python3 scripts/import_osm_maxheight.py <extract.osm.pbf> [DATABASE_URL]
  python3 scripts/import_osm_maxheight.py <extract.osm.pbf> --sql > osm_maxheight.sql
  python3 scripts/import_osm_maxheight.py <extract.osm.pbf> --jsonl   # records only, no SQL

Sources (needs `pip install osmium`; crossings reuse scripts/osm_bridge_clearance.py):
  (a) crossing: a road passing UNDER a bridge whose WAY carries a height tag -> Point at the
      crossing (id osm-maxheight-way<road>-crossing<bridge>). Such a way gets no LineString, so the
      route avoids the passage, not the whole (possibly km-long) way.
  (b) way: other highway ways with a height tag that are not bridges (tunnels, covered, plain
      roads) -> LineString of the way (id osm-maxheight-way<id>); direction from oneway.
  (c) node: nodes with a height tag that belong to a highway way -> Point (id osm-maxheight-node<id>).
      Height nodes near a crossing are covered by (c), not duplicated as (a).
Values: maxheight preferred, else maxheight:physical (only one is stored). Metres, "4.2 m",
feet/inches -> metres. Non-numeric (default, none, below_default...) and outliers (< 2 m, > 7 m)
are skipped and counted (stats on stderr). Parking aisles, driveways and drive-throughs
(highway=service + service=parking_aisle|driveway|drive-through) are skipped with their crossings,
and so are nodes that lie only on such ways (skipped_service_parking): underground car parks are not
on truck routes and only caused false detours (ADR-0016). valueSource: posted_sign if source:maxheight=sign or
maxheight:signed=yes, measured if maxheight:physical was used, else unknown. status: unverified.

Every record is validated against data/restrictions.schema.json with Ajv via
`node scripts/validate_restrictions.js` (same validator as `npm test`); any invalid record aborts.
SQL output: one transaction that deletes ONLY rows with id LIKE 'osm-maxheight-%' and inserts the
new set (re-runnable; manual / MoT / dev rows are never touched). The audit trigger logs one event
per deleted and inserted row (~2 x N rows in restriction_events per re-import).
Data is ODbL-derived (OpenStreetMap contributors): keep it in the local DB only, never commit it.
"""
import datetime
import json
import os
import subprocess
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import osm_bridge_clearance as obc  # noqa: E402

ID_PREFIX = "osm-maxheight-"
MIN_M, MAX_M = 2.0, 7.0
STAGE_COLUMNS = ("id", "road_segment_id", "geom_json", "value_source", "direction",
                 "value_numeric", "source", "observed_at")
PARKING_SERVICE = ("parking_aisle", "driveway", "drive-through")
HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- pure helpers
def choose_height(tags, stats=None):
    """(metres, valueSource, tag_used) from a tag dict, or None (reason counted in stats)."""
    stats = stats if stats is not None else Counter()
    candidates = [("maxheight", tags.get("maxheight")), ("maxheight:physical", tags.get("maxheight:physical"))]
    reason = None
    for tag, raw in candidates:
        if not raw:
            continue
        m = obc.parse_height(raw.strip())
        if m is None:
            reason = reason or "non_numeric"
            continue
        if m < MIN_M:
            reason = reason or "outlier_low"
            continue
        if m > MAX_M:
            reason = reason or "outlier_high"
            continue
        if tag == "maxheight":
            signed = tags.get("source:maxheight") == "sign" or tags.get("maxheight:signed") == "yes"
            vs = "posted_sign" if signed else "unknown"
        else:
            vs = "measured"
        return round(m, 2), vs, tag
    if reason:
        stats["skipped_" + reason] += 1
    return None


def is_service_parking(tags):
    """highway=service way that is a parking aisle, driveway or drive-through."""
    return tags.get("highway") == "service" and tags.get("service") in PARKING_SERVICE


def direction_of(tags):
    ow = tags.get("oneway")
    if ow in ("yes", "true", "1"):
        return "forward"
    if ow in ("-1", "reverse"):
        return "backward"
    return "both"


def _date(extract_iso):
    return extract_iso[:10] if extract_iso else "unknown"


def make_record(osm_type, osm_id, road_way_id, geometry, height, direction, extract_iso, suffix=""):
    metres, value_source, _ = height
    return {
        "id": "%s%s%d%s" % (ID_PREFIX, osm_type, osm_id, suffix),
        "roadSegmentId": "osm:way:%d" % road_way_id,
        "geometry": geometry,
        "valueSource": value_source,
        "direction": direction,
        "restrictionType": "max_height",
        "value": metres,
        "unit": "m",
        "status": "unverified",
        "source": {
            "name": "OpenStreetMap contributors",
            "reference": "osm:%s/%d@%s" % (osm_type, osm_id, _date(extract_iso)),
            "url": "https://www.openstreetmap.org/%s/%d" % (osm_type, osm_id),
            "license": "ODbL-1.0",
        },
        "observedAt": extract_iso,
    }


def _pt(p):
    return {"type": "Point", "coordinates": [round(p[0], 7), round(p[1], 7)]}


def build_records(ways, nodes, crossings, extract_iso, parking_way_ids=()):
    """ways: {id: {"tags", "coords", "bridge": bool}} highway ways carrying a height tag.
    nodes: {id: {"tags", "loc", "way_ids": [highway way ids]}} nodes carrying a height tag.
    crossings: {(bridge_id, road_id): (lon, lat)} from obc.find_crossings.
    parking_way_ids: ids of ALL highway ways that are parking aisles/driveways/drive-throughs
    (a node lying only on such ways is skipped; height-tagged ways are also checked by their tags).
    Returns (records, stats)."""
    stats = Counter()
    records = []
    parking = set(parking_way_ids)
    crossing_by_road = {}
    for (bk, rk), p in crossings.items():
        crossing_by_road.setdefault(rk, []).append((bk, p))
    for wid in sorted(ways):
        w = ways[wid]
        if w.get("bridge"):
            stats["skipped_bridge_way"] += 1
            continue
        if is_service_parking(w["tags"]):
            stats["skipped_service_parking"] += 1
            continue
        h = choose_height(w["tags"], stats)
        if h is None:
            continue
        if wid in crossing_by_road:
            for bk, p in sorted(crossing_by_road[wid]):
                records.append(make_record("way", wid, wid, _pt(p), h, "both", extract_iso, "-crossing%d" % bk))
                stats["crossing"] += 1
            continue
        coords = [[round(x, 7), round(y, 7)] for x, y in w["coords"]]
        if len(coords) < 2:
            stats["skipped_no_geometry"] += 1
            continue
        records.append(make_record("way", wid, wid, {"type": "LineString", "coordinates": coords}, h,
                                   direction_of(w["tags"]), extract_iso))
        stats["way"] += 1
    for nid in sorted(nodes):
        n = nodes[nid]
        if not n.get("way_ids"):
            stats["skipped_node_not_on_highway"] += 1
            continue
        if parking and all(x in parking for x in n["way_ids"]):
            stats["skipped_service_parking"] += 1
            continue
        h = choose_height(n["tags"], stats)
        if h is None:
            continue
        records.append(make_record("node", nid, min(n["way_ids"]), _pt(n["loc"]), h, "both", extract_iso))
        stats["node"] += 1
    stats["records"] = len(records)
    return records, stats


def validate(records):
    """Ajv validation via node (scripts/validate_restrictions.js). Raises on any invalid record."""
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    p = subprocess.run(["node", os.path.join(HERE, "validate_restrictions.js")], input=payload,
                       text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("schema validation failed: %s %s" % (p.stdout.strip(), p.stderr.strip()))
    return json.loads(p.stdout)


def _copy_value(v):
    if v is None:
        return r"\N"
    s = str(v)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def stage_row(r):
    return {
        "id": r["id"], "road_segment_id": r["roadSegmentId"],
        "geom_json": json.dumps(r["geometry"], separators=(",", ":")),
        "value_source": r["valueSource"], "direction": r["direction"], "value_numeric": r["value"],
        "source": json.dumps(r["source"], ensure_ascii=False, separators=(",", ":")),
        "observed_at": r["observedAt"],
    }


def to_psql_script(records):
    out = [
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        "SET LOCAL trucksil.actor = 'import_osm_maxheight';",
        "CREATE TEMP TABLE osm_maxheight_stage (id text, road_segment_id text, geom_json text, value_source text,"
        " direction text, value_numeric double precision, source jsonb, observed_at timestamptz) ON COMMIT DROP;",
        "COPY osm_maxheight_stage (%s) FROM STDIN;" % ", ".join(STAGE_COLUMNS),
    ]
    for r in records:
        s = stage_row(r)
        out.append("\t".join(_copy_value(s[c]) for c in STAGE_COLUMNS))
    out += [
        "\\.",
        "DELETE FROM restrictions WHERE id LIKE '%s%%';" % ID_PREFIX,
        "INSERT INTO restrictions (id, road_segment_id, geometry, value_source, direction, restriction_type,"
        " value_numeric, unit, status, source, observed_at)",
        "SELECT id, road_segment_id, ST_SetSRID(ST_GeomFromGeoJSON(geom_json), 4326), value_source, direction,"
        " 'max_height', value_numeric, 'm', 'unverified', source, observed_at FROM osm_maxheight_stage"
        " WHERE id LIKE '%s%%';" % ID_PREFIX,
        "COMMIT;",
        "",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------- osmium part
def _make_handler():
    import osmium

    class H(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ts = 0
            self.nodes = {}
            self.ways = {}
            self.parking_way_ids = set()

        def _ts(self, o):
            t = int(o.timestamp.timestamp()) if o.timestamp else 0
            if t > self.ts:
                self.ts = t

        def node(self, n):
            self._ts(n)
            if any(n.tags.get(t) for t in obc.HEIGHT_TAGS) and n.location.valid():
                self.nodes[n.id] = {"tags": {k.k: k.v for k in n.tags}, "loc": (n.location.lon, n.location.lat),
                                    "way_ids": []}

        def way(self, w):
            self._ts(w)
            hw = w.tags.get("highway")
            if hw is None or hw in obc.EXCLUDED:
                return
            if is_service_parking(w.tags):
                self.parking_way_ids.add(w.id)
            for nr in w.nodes:
                if nr.ref in self.nodes:
                    self.nodes[nr.ref]["way_ids"].append(w.id)
            if not any(w.tags.get(t) for t in obc.HEIGHT_TAGS):
                return
            try:
                coords = [(nr.lon, nr.lat) for nr in w.nodes]
            except Exception:  # missing locations at extract border
                coords = []
            br = w.tags.get("bridge")
            self.ways[w.id] = {"tags": {k.k: k.v for k in w.tags}, "coords": coords,
                               "bridge": br is not None and br != "no"}

    return H()


def load(pbf):
    h = _make_handler()
    h.apply_file(pbf, locations=True, idx="flex_mem")
    b = obc._make_handler()
    b.apply_file(pbf, locations=True, idx="flex_mem")
    crossings = obc.find_crossings(b.bridges, b.roads)
    ts = max(h.ts, b.ts)
    extract = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None
    if not extract:
        sys.exit("extract has no timestamps; observedAt cannot be set")
    return build_records(h.ways, h.nodes, crossings, extract, h.parking_way_ids)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    as_sql, as_jsonl = "--sql" in argv, "--jsonl" in argv
    db_url = args[1] if len(args) > 1 else os.environ.get("DATABASE_URL")
    if not (as_sql or as_jsonl) and not db_url:
        sys.exit("DATABASE_URL (argument or env), --sql or --jsonl is required")
    records, stats = load(args[0])
    print("osm maxheight: %s" % json.dumps(dict(sorted(stats.items()))), file=sys.stderr)
    if as_jsonl:
        sys.stdout.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        return
    print("osm maxheight: schema %s" % json.dumps(validate(records)), file=sys.stderr)
    script = to_psql_script(records)
    if as_sql:
        sys.stdout.write(script)
        return
    subprocess.run(["psql", "-q", db_url], input=script, text=True, check=True)
    print("osm maxheight: loaded %d records" % len(records), file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
