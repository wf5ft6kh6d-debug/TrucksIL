#!/usr/bin/env python3
"""Import truck POIs from OSM into the local `truck_poi` table (migration 005, ADR-0017).

Usage:
  python3 scripts/import_osm_truck_poi.py <extract.osm.pbf> [DATABASE_URL]
  python3 scripts/import_osm_truck_poi.py <extract.osm.pbf> --sql > truck_poi.sql
  python3 scripts/import_osm_truck_poi.py <extract.osm.pbf> --jsonl   # records only, no SQL

Kinds (nodes and ways; a way becomes the mean of its node positions; relations are not read):
  parking    amenity=parking + hgv=yes|designated
  rest_area  highway=rest_area
  fuel_hgv   amenity=fuel + hgv=yes|designated
Every row is status 'unverified' and is shown as "OSM, unverified": display only, never used for
routing. Output is one psql transaction: DELETE FROM truck_poi; COPY; INSERT (re-runnable; the table
holds only OSM rows). Data is ODbL-derived (OpenStreetMap contributors): local DB only, never commit.
Needs `pip install osmium` for reading the extract; the helpers below are pure Python.
"""
import datetime
import json
import os
import subprocess
import sys
from collections import Counter

HGV_OK = ("yes", "designated")
STAGE_COLUMNS = ("id", "osm_type", "osm_id", "kind", "name", "lon", "lat", "tags", "source_extract_date")


def classify(tags):
    """List of kinds for a tag dict (an object can be e.g. a rest area with HGV parking)."""
    kinds = []
    hgv = tags.get("hgv") in HGV_OK
    if tags.get("amenity") == "parking" and hgv:
        kinds.append("parking")
    if tags.get("highway") == "rest_area":
        kinds.append("rest_area")
    if tags.get("amenity") == "fuel" and hgv:
        kinds.append("fuel_hgv")
    return kinds


def centroid(coords):
    """Mean of way node positions (closing node of a closed way counted once); None if empty."""
    pts = list(coords)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def make_records(objects, extract_iso):
    """objects: iterable of (osm_type, osm_id, tags, (lon, lat) | None). Returns (records, stats)."""
    stats = Counter()
    records = []
    for osm_type, osm_id, tags, loc in sorted(objects, key=lambda o: (o[0], o[1])):
        kinds = classify(tags)
        if not kinds:
            continue
        if loc is None:
            stats["skipped_no_geometry"] += 1
            continue
        for kind in kinds:
            records.append({
                "id": "osm-poi-%s%d-%s" % (osm_type, osm_id, kind),
                "osmType": osm_type, "osmId": osm_id, "kind": kind,
                "name": tags.get("name") or tags.get("name:he") or tags.get("name:en") or None,
                "position": [round(loc[0], 7), round(loc[1], 7)],
                "tags": tags, "status": "unverified", "sourceExtractDate": extract_iso,
            })
            stats[kind] += 1
    stats["records"] = len(records)
    return records, stats


def _copy_value(v):
    if v is None:
        return r"\N"
    s = str(v)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def to_psql_script(records):
    out = [
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        "CREATE TEMP TABLE truck_poi_stage (id text, osm_type text, osm_id bigint, kind text, name text,"
        " lon double precision, lat double precision, tags jsonb, source_extract_date timestamptz) ON COMMIT DROP;",
        "COPY truck_poi_stage (%s) FROM STDIN;" % ", ".join(STAGE_COLUMNS),
    ]
    for r in records:
        row = (r["id"], r["osmType"], r["osmId"], r["kind"], r["name"], r["position"][0], r["position"][1],
               json.dumps(r["tags"], ensure_ascii=False, separators=(",", ":"), sort_keys=True), r["sourceExtractDate"])
        out.append("\t".join(_copy_value(v) for v in row))
    out += [
        "\\.",
        "DELETE FROM truck_poi;",
        "INSERT INTO truck_poi (id, osm_type, osm_id, kind, name, geom, tags, status, source_extract_date)",
        "SELECT id, osm_type, osm_id, kind, name, ST_SetSRID(ST_MakePoint(lon, lat), 4326), tags, 'unverified',"
        " source_extract_date FROM truck_poi_stage;",
        "COMMIT;",
        "",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------- osmium part
def load(pbf):
    import osmium

    class H(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ts = 0
            self.objects = []

        def _ts(self, o):
            t = int(o.timestamp.timestamp()) if o.timestamp else 0
            self.ts = max(self.ts, t)

        def node(self, n):
            self._ts(n)
            tags = {k.k: k.v for k in n.tags}
            if classify(tags) and n.location.valid():
                self.objects.append(("node", n.id, tags, (n.location.lon, n.location.lat)))

        def way(self, w):
            self._ts(w)
            tags = {k.k: k.v for k in w.tags}
            if not classify(tags):
                return
            try:
                loc = centroid([(nr.lon, nr.lat) for nr in w.nodes])
            except Exception:  # missing locations at extract border
                loc = None
            self.objects.append(("way", w.id, tags, loc))

    h = H()
    h.apply_file(pbf, locations=True, idx="flex_mem")
    if not h.ts:
        sys.exit("extract has no timestamps")
    extract = datetime.datetime.fromtimestamp(h.ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return make_records(h.objects, extract)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    as_sql, as_jsonl = "--sql" in argv, "--jsonl" in argv
    db_url = args[1] if len(args) > 1 else os.environ.get("DATABASE_URL")
    if not (as_sql or as_jsonl) and not db_url:
        sys.exit("DATABASE_URL (argument or env), --sql or --jsonl is required")
    records, stats = load(args[0])
    print("osm truck poi: %s" % json.dumps(dict(sorted(stats.items()))), file=sys.stderr)
    if as_jsonl:
        sys.stdout.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        return
    script = to_psql_script(records)
    if as_sql:
        sys.stdout.write(script)
        return
    subprocess.run(["psql", "-q", db_url], input=script, text=True, check=True)
    print("osm truck poi: loaded %d records" % len(records), file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
