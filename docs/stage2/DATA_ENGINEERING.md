# Stage 2 geographic data foundation

Implemented against the existing `docs/ARCHITECTURE.md` stage 2 and
`docs/DATA_VERIFICATION.md`; existing verification status names are retained.
This is local staging infrastructure, not navigation and not a nationwide dataset.
No real restriction records were invented or imported by this work.

## Files and contracts

- `data/restrictions.schema.json`: JSON Schema 2020-12. Location is a nonempty
  road segment reference and/or WGS84 GeoJSON Point/LineString, longitude first.
  IDs must be resolved against a versioned road graph before spatial use; a
  structurally valid coordinate is not proof of location or jurisdiction.
- `src/ingest_restrictions.py`: Python 3.10+ standard-library-only batch validator.
  Supports the schema's exact keyword subset; unknown assertion keywords fail
  closed. JSON array or `.jsonl`, explicit units, provenance, timestamps, and
  required evidence references. Duplicate JSON keys, duplicate IDs, NaN,
  Infinity, zero physical limits and unit/type mismatches are rejected.
- `db/stage2.sql`: proposed PostGIS staging DDL for source/license records,
  graph nodes and segments, restrictions, dimension-specific coverage reviews,
  spatial indexes and automatic mutation audit events. **Not executed or
  PostgreSQL/PostGIS integration-tested**: no PostgreSQL client/server was
  available. It is not a production migration.

## Review and safety gates

All records require source name/reference/kind, authenticated-official flag,
license metadata/reviewer/check/review date, observation/check/review timestamps,
verifier and nonempty evidence references. `verified` additionally requires
known direction, verification time, current permitted license, current review,
non-user-report source and an approved independent review with a different
reviewer, timestamp and reference. Hazmat records require explicit condition
text; verified conditional records require reviewed interpretation.

Boolean restriction `value: 1` denotes a prohibition/restriction; `0` is
rejected so that this ingestion cannot turn a restriction record into permission.
Metres apply to dimensions and tonnes to gross/axle mass. Conditional or
hazmat semantics are not converted to route rules here.

The importer validates **attestations and structure**, not authenticity,
source truth, licensing legality, reviewer identity or independence in reality.
Strings saying `official`, `permitted`, `approved` or `verified` cannot themselves
prove those facts. Official-channel authentication, license scope (including
storage, derivatives and redistribution), evidence matching, physical location,
conflicts and independent review require the documented review process.
User reports remain attributed as user reports and cannot be marked verified.

An overdue verified record is rejected, never silently renewed. The importer
retains other submitted statuses rather than upgrading them. Review dates must
also be evaluated at each future use; a previous successful import is not a
permanent validity guarantee. `--as-of` is a reproducibility/testing clock,
**not an authorization to bypass the real current time in an operational gate**.

Output always has `routeSafetyCertified: false`, `routeSuitability: "unknown"`
and `coverageStatus: "unknown"`, including empty batches and all-verified
batches. Missing restrictions, graph elements or coverage rows never establish
suitability. Database safety view likewise returns unknown/false for every road.
No route engine consumes these files.

Pending/denied license records can be staged as **metadata/references only**;
this does not authorize downloading, storing or redistributing source payloads.
Never place protected data, credentials, personal reports or production data in
Git. Synthetic fixtures belong under tests and are never evidence inventory.

## Local commands

```sh
# Read-only validation; no output file and no database writes:
python src/ingest_restrictions.py /absolute/path/restrictions.json
# Reproducible test clock, local output only (parent folder must exist):
python src/ingest_restrictions.py /absolute/path/restrictions.jsonl \
  --as-of 2026-10-09T08:00:00Z --output /tmp/trucksil-staging.json
python -m unittest discover -s tests -v
```

Any invalid record rejects the whole batch before writing output (exit 1).
Valid batches exit 0; optional output is atomically replaced. Input cannot be
overwritten. Existing output survives invalid batches. Output is an envelope
with records and validation time, not another importer input; pass its `records`
array explicitly if revalidating. Default clock is current UTC.

`validate_record(record, as_of)` is available to tests and raises `ValueError`
on rejection. It returns the record on structural/temporal acceptance only.

## Database acceptance still outstanding

Run proposed DDL only in a separately authorized disposable local database with
PostGIS and least-privilege roles, then test rollback, foreign keys, audit triggers,
invalid geometries, revision reconciliation, coverage expiration and endpoint
connectivity. No SQL has been executed by this change. SQL is a staging proposal,
not a second full schema validator: use the importer before any future adapter,
then enforce source/license/time and normalized-column vs JSON consistency in
that adapter. Direct SQL inserts do not establish verified evidence. Audit events
are ordinary local tables, not a tamper-proof log; production roles and immutable
external audit storage require separate design/review.

No automatic ingest adapter, live feed, nationwide road import, redistribution
permission, coverage certification or deployment is claimed.

## Follow-up database execution check — 2026-10-09

The environment was checked for `psql`, `postgres`, `initdb`, `docker`, installed
PostgreSQL directories and cached Debian packages. None were available; apt had
no PostgreSQL/PostGIS package candidates in its local index. The advertised
network allowlist does not include Ubuntu package mirrors, so no installation
or network-bound package download was attempted. **PostGIS tests remain NOT RUN.**

`db/test_stage2.sql` now provides synthetic transactional checks for foreign
keys, unit/value restrictions including NaN/Infinity, absent/out-of-range
location, incomplete verified attestations, official-source label integrity,
incomplete coverage reviews, successful-write audit count and unknown route
suitability. All fixtures roll back. It refuses TCP and database names outside
`trucksil_stage2_test_*`. It does not test actual evidence, licensing truth or
nationwide coverage. It intentionally demonstrates only database staging
constraints, which are weaker than the full import contract.

Once PostgreSQL/PostGIS is available, a local operator can use a **new disposable
local database** (replace socket directory with that local instance's socket):

```sh
createdb --host=/var/run/postgresql trucksil_stage2_test_local
psql --host=/var/run/postgresql --dbname=trucksil_stage2_test_local \
  --set=ON_ERROR_STOP=1 --file=db/stage2.sql
psql --host=/var/run/postgresql --dbname=trucksil_stage2_test_local \
  --set=ON_ERROR_STOP=1 --file=db/test_stage2.sql
```

These commands were **not executed here**. Do not point them at an existing
application or production database. The fixture script rolls back test data;
the earlier DDL remains in the disposable database. End-to-end SQL execution,
PostGIS version compatibility and migration idempotency are still open gates.

Audit limitation: current events record table, entity ID, action, database actor
and timestamp only. They do **not** store old/new values or the application
reviewer's identity, so they cannot reconstruct a restriction's edit history.
An immutable revision log with authenticated actors and evidence lineage is an
open prerequisite before operational use; the current audit table is not a
complete chain of custody.
