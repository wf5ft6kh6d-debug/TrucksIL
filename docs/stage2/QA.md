# Stage 2 quality assurance

## Baseline inspection (2026-10-09)

The starter repository contains draft policy and a draft restriction schema, but no road data, import pipeline, road graph, automated tests or operational routing engine. No Israeli road coverage or route safety has been established.

The original schema allowed a `verified` label without a verifier, verification timestamp or review deadline, did not link measurement units to restriction types, accepted empty segment identifiers, and did not represent licensing or official-channel authentication. JSON Schema `format` annotations alone do not establish timestamp validity unless the caller enables format checking.

## Scope

Synthetic adversarial importer tests validate processing rules only. They do not validate a real restriction, government source, licence, nationwide coverage or route. Synthetic identifiers and reserved example domains must never enter an operational dataset.

## Executed results (2026-10-09)

Command: `python -m unittest discover -s tests -v`

Result before the added timezone regressions: **15 tests passed**, with additional adversarial subcases, against the stage-2 importer. Validation time is pinned to `2026-10-09T08:00:00Z` for deterministic expiry boundaries.

The suite exercises required provenance, independent reviewer separation, verification and licence expiry at the exact deadline, invalid unit/value combinations, official/user attribution separation, invalid/missing locations, invalid/future timestamps, NaN/Infinity, duplicate JSON keys and record IDs, malformed input, unexpected fields, JSON and JSONL input, and atomic batch rejection preserving an existing output file. Empty, unverified and structurally verified batches all retain `routeSafetyCertified=false`, `routeSuitability=unknown`, and `coverageStatus=unknown`.

An initial JSONL test used an incorrect `.json` fixture filename; the harness was corrected to use `.jsonl`. Verified fixtures were updated after the independent-review gate was added. That run passed. A subsequent independent-audit regression exposed accepted invalid `-00:99` and unknown `-00:00` timestamp offsets; the coordinator reproduced two failing subcases before correcting the parser.

These are black-box CLI and repository-schema-backed checks. A separate Draft 2020-12 validator is not installed, so independent full JSON Schema conformance is **not claimed**. Source authentication, evidence truth and reviewer identity are attestations, not externally authenticated by this tool. Numeric coordinate bounds do not prove a location is in Israel or on a road; segment identifiers are not resolved against a graph. No actual road restriction, geographic coverage, routing behavior, live database or legal reuse decision was verified.

## Outstanding safety validation

- Independently authenticate every source and its authority for each claimed fact.
- Validate licences and permitted reuse before any external-data ingestion.
- Reconcile actual official restrictions with geometry, direction, time windows and vehicle applicability.
- Measure coverage against a complete, licensed road graph; unknown coverage remains unknown.
- Exercise a future routing engine against missing, conflicting, expired and temporary restrictions.
- Validate PostGIS import and geospatial integrity when a database is actually available.
- Conduct independent and field review before driver-facing guidance.

## Coordinator completion after agent interruption

The tester, data engineer and independent auditor stopped due to an agent usage limit before final sign-off. The coordinator fixed the timezone parser (invalid offset components and unknown `-00:00` rejected) and added a recursive schema preflight so unsupported assertions in conditional/alternative branches cannot be swallowed as ordinary data mismatches.

Final executed command: `python -m unittest discover -s tests -v`. **16 tests passed** on 2026-10-09, including both audit regressions. This is coordinator verification, not a completed independent re-audit. PostGIS and a separate JSON Schema engine remain untested.

## Resumed tester verification

On 2026-10-09 the tester independently reran `python -m unittest discover -s tests -v` at commit `3516469`: **16 tests passed**. This includes the invalid/unknown timezone-offset and unsupported-schema-keyword regressions corrected by the coordinator. Both the default Python and the provided primary-runtime Python were checked; neither has a separate `jsonschema` package installed. No external package installation was attempted. This rerun verifies the executed importer tests, not data correctness or completion of the entire stage.

## 2026-10-10 validator fixes and candidate database guard

Baseline: 779849598bc23716c603068f3b437ec76e3d9452. Working branch unchanged.
Executed:
- `python -m unittest discover -s tests -v`: **23 tests PASS**, consisting of
  the original 16, five JSON-policy regressions and two offline migration-runner
  tests. Subcases are not counted as separate tests.
- The enum/const and minLength regression methods were also run against baseline
  source loaded with `git show 7798495:src/ingest_restrictions.py`: expected
  16 failed boolean/number subcases and one whitespace minLength error. This
  confirms the new cases detect the original defects.
- `python scripts/compare_schema_engine.py`: exit 2, **NOT RUN**, jsonschema absent.
- `python scripts/migrate_stage2.py --database trucksil_stage2_test_local > /tmp/trucksil-migration-plan.sql`:
  exit 0, SQL generated ONLY, no database connection.
- `git diff --check`: exit 0.

Environment: default and primary Python lacked jsonschema; previous Ajv lookup
also found no engine. psql/postgres/initdb/docker/podman absent. Package-download
hosts are outside the execution allowlist; no installation attempted. No full
Draft 2020-12 compatibility, database correctness or migration acceptance claimed.

Pending executable SQL corpus: db/test_stage2_hardening.sql checks closed direct
restriction writes, audit mutation denial, endpoint/revision mismatch rejection,
source before/after audit, full coverage key/deletion audit and unknown safety.
It is NOT RUN; offline runner tests do not substitute for SQL integration.
