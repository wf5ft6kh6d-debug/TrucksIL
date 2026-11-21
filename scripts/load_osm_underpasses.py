#!/usr/bin/env python3
"""Load roads passing under bridges (osm_underpasses, migration 004) from an OSM .pbf.

Usage:
  python3 scripts/load_osm_underpasses.py <extract.osm.pbf> [DATABASE_URL]
  python3 scripts/load_osm_underpasses.py <extract.osm.pbf> --sql > underpasses.sql

Crossings are computed with the helpers of scripts/osm_bridge_clearance.py (imported, not copied;
needs `pip install osmium`). The output is a single psql script: BEGIN; TRUNCATE; COPY ... FROM
STDIN; COMMIT; so a reload is idempotent and atomic. No Python DB driver is needed:
  * with DATABASE_URL and `psql` on PATH the script is piped into `psql DATABASE_URL`;
  * with --sql it is written to stdout, e.g. for
      ... --sql | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
Data is ODbL-derived (OpenStreetMap contributors): keep it in the local DB only, never commit it.
OSM maxheight is stored as an "OSM candidate" for display only, never for routing decisions.
"""
import datetime
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import osm_bridge_clearance as obc  # noqa: E402

COLUMNS = ("osm_road_way_id", "osm_bridge_way_id", "bridge_kind", "geom", "road_ref",
           "road_class", "osm_maxheight_text", "osm_maxheight_m", "source_extract_date")


def maxheight_for(road, point):
    """Raw OSM maxheight for a crossing: way tag, else a maxheight node within NODE_RADIUS_M."""
    if road.get("mh"):
        return road["mh"]
    near = [v for loc, v in road.get("mh_nodes") or [] if obc.haversine_m(point, loc) <= obc.NODE_RADIUS_M]
    return near[0] if near else None


def build_rows(bridges, roads, crossings, extract_date=None):
    """crossings: {(bridge_key, road_key): (lon, lat)} from obc.find_crossings."""
    rows = []
    for (bk, rk), p in sorted(crossings.items()):
        b, r = bridges[bk], roads[rk]
        raw = maxheight_for(r, p)
        m = obc.parse_height(raw) if raw else None
        rows.append({
            "osm_road_way_id": int(rk), "osm_bridge_way_id": int(bk), "bridge_kind": b["kind"],
            "geom": "SRID=4326;POINT(%.7f %.7f)" % (p[0], p[1]),
            "road_ref": r.get("ref"), "road_class": r.get("class"),
            "osm_maxheight_text": raw, "osm_maxheight_m": None if m is None else round(m, 2),
            "source_extract_date": extract_date,
        })
    return rows


def _copy_value(v):
    if v is None:
        return r"\N"
    s = str(v)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def to_psql_script(rows):
    out = ["\\set ON_ERROR_STOP on", "BEGIN;", "TRUNCATE osm_underpasses RESTART IDENTITY;",
           "COPY osm_underpasses (%s) FROM STDIN;" % ", ".join(COLUMNS)]
    for r in rows:
        out.append("\t".join(_copy_value(r[c]) for c in COLUMNS))
    out += ["\\.", "COMMIT;", ""]
    return "\n".join(out)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    as_sql = "--sql" in argv
    db_url = args[1] if len(args) > 1 else os.environ.get("DATABASE_URL")
    if not as_sql and not db_url:
        sys.exit("DATABASE_URL (argument or env) or --sql is required")
    h = obc._make_handler()
    h.apply_file(args[0], locations=True, idx="flex_mem")
    crossings = obc.find_crossings(h.bridges, h.roads)
    extract = datetime.datetime.fromtimestamp(h.ts, datetime.timezone.utc).isoformat() if h.ts else None
    script = to_psql_script(build_rows(h.bridges, h.roads, crossings, extract))
    print("underpasses: %d crossings" % len(crossings), file=sys.stderr)
    if as_sql:
        sys.stdout.write(script)
        return
    subprocess.run(["psql", "-q", db_url], input=script, text=True, check=True)
    print("underpasses: loaded", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
