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
