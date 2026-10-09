# Independent stage 2 audit

Audit date: 2026-10-09. Baseline inspected: `d7ba83c`.

## Scope and verdict

**Stage 2 is incomplete; nationwide data coverage and safe truck routing are NOT established. No deployment or route certification is authorized by this review.**

The repository baseline contains draft requirements, a proposed phased architecture, a verification policy and a preliminary restriction schema. It does not contain an operational road graph or verified national restriction inventory. The phase 2 scope follows the existing architecture: geospatial database, road graph, restriction ingestion, provenance and review workflow.

## Baseline findings

| Severity | Finding | Acceptance gate |
| --- | --- | --- |
| Critical | No verified nationwide road/restriction coverage exists in the baseline. | Coverage must be explicit per segment, restriction dimension and review period; unknown coverage cannot establish suitability. |
| High | Draft schema permits `verified` without verifier identity or review deadline. | Require provenance, reviewer, verification time and current review deadline; fail closed on expired or disputed records. |
| High | Draft schema does not constrain unit by restriction type; numeric zero is permitted. | Reject incompatible dimensions and nonpositive physical limits; represent prohibitions and hazmat conditions without invented numeric limits. |
| High | Draft schema lacks source license and official/user attribution. | Record provenance and license decision; user reports must remain nonofficial and unsupported licensing must block production use. |
| High | A road-segment string alone does not prove a geospatial match. | Validate against the graph, coordinate system, direction and applicable segment extent; ambiguous matches remain quarantined. |

## Release gates beyond this initial change

1. Obtain legally reusable data and authenticated authoritative evidence for road restrictions; source discovery alone is insufficient.
2. Execute and record imports into an actual geospatial database, validate geometries and graph references, and reconcile conflicting sources.
3. Establish road coverage and current restriction coverage independently; count missing roads, dimensions and stale records.
4. Verify directional, conditional, temporal, vehicle-class, hazmat and dimensional restrictions before supporting routing.
5. Exercise real database constraints and integration tests, adverse routing scenarios and external safety review before any guidance to drivers.
6. Preserve source observations and review decisions in an auditable history. A reviewed schema or passing synthetic test suite does not verify a road.

## Execution record

- Read baseline `docs/ARCHITECTURE.md`, `docs/PRODUCT_REQUIREMENTS.md`, `docs/DATA_VERIFICATION.md` and `data/restrictions.schema.json`.
- Shared baseline defects with the coordinator and data engineer; requested independent test results.
- Reviewed `CARTOGRAPHY.md`, `RESTRICTIONS.md`, `EXECUTION_PLAN_RU.md`, `source-candidates.json` and QA baseline. They separate source discovery from acquired road data, record unresolved licenses and do not claim nationwide completion.
- Independently opened [OSM copyright](https://www.openstreetmap.org/copyright) and [Data.gov.il terms](https://data.gov.il/he/terms-of-use) on the audit date. ODbL/attribution and dataset-specific license precedence agree with the research reports. This is not approval of any particular import or joined-database redistribution.
- Executed direct timestamp probes: invalid offsets `+01:99` and `-00:99` were normalized and accepted. Reported to engineer and tester as a medium-severity provenance-validation defect.
- Executed custom-validator probes: an unsupported schema keyword under `anyOf` or `if` could be swallowed as a normal validation mismatch. Reported as a medium-severity future-schema fail-closed defect; the current schema does not use these unsupported assertions.
- Final fix verification and database-design review remain pending in this intermediate audit record.

## Coordinator addendum — not independent sign-off

After the auditor reached an agent usage limit, the coordinator corrected both reported code defects and ran all 16 tests successfully. The independent auditor did not re-review the fixes or completed SQL design. Therefore final independent acceptance remains **PENDING**; preserve this as a draft PR and do not merge/deploy on the basis of this report. SQL has not been executed against PostGIS.
