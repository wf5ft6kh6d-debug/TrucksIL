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
