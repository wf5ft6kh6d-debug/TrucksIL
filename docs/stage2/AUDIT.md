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

## Resumed independent review — commit `3516469`

Review date: 2026-10-09. This section supersedes the pending *code re-review* state above; it does not close the stage 2 or database-integration gates.

Executed independently:

- `python -m unittest discover -s tests -v`: **16 tests passed**.
- Direct parser probes reject `+01:99`, `-00:99`, `-00:00` and `+24:00`; a known `+03:00` offset remains accepted. The earlier timestamp defect is **closed**.
- Direct validator probes reject unsupported assertions in `anyOf` and `if`, and an unsupported `format` in an unused property. Recursive schema preflight prevents their being swallowed as data mismatches. The earlier schema-branch defect is **closed**.
- Inspected the strengthened JSON schema, local importer, engineering documentation and `db/stage2.sql`. Source attribution, physical units, provenance fields, independent-review attestations, review deadlines and unconditional unknown/false output are represented. The importer verifies declared structure and chronology, not the truth of those declarations.
- Checked client availability: `psql` is absent. **No SQL execution, transaction, trigger, geometry or database-integration result is claimed.**

### Remaining findings / acceptance gates

| Severity and scope | Observation | Required resolution before operational use |
| --- | --- | --- |
| High — database integration | SQL is deliberately a partial staging model. Direct inserts can bypass importer-only checks; source/license currency, conditions and normalized columns versus `validated_record` are not enforced consistently. | Implement a controlled ingest adapter and database roles, define authoritative fields, and run adversarial integration tests. No direct SQL row may be treated as verified evidence merely because its status says `verified`. |
| High — evidence history | SQL mutation events record actor/time/table/key/action, but no old/new values or restriction revision. Updating a record does not preserve its prior evidence in these events. | Add immutable evidence/review revisions or protected before/after references with a retention policy before real mutable evidence is ingested. Current events are a mutation journal, not a reconstructable evidence history. |
| High — geographic integrity | Foreign keys and coordinate bounds do not prove endpoint connectivity, source revision alignment, correct deck/underpass linkage, jurisdiction or real segment identity. | Execute PostGIS checks and independent spatial reconciliation on acquired data; quarantine unmatched or ambiguous records. |
| High — source trust and licensing | `official`, `permitted` and reviewer names remain submitted attestations; no authenticated source/identity system is implemented. | Complete source-specific authentication and reuse reviews; do not infer legal approval or review independence from strings. |
| Blocking for driver guidance | No licensed national road graph, real verified restrictions, measured coverage, conflict adjudication, routing integration or field validation has been delivered by this change. | Complete the outstanding stage 2 acceptance criteria and subsequent routing/safety phases. |

**Independent disposition:** the two reported implementation defects are fixed and verified. The change is suitable to remain a **draft, non-operational foundation for review**, with its limitations explicit. This audit does not approve merging, deployment, completion of stage 2, any real restriction, or any truck route. PostgreSQL/PostGIS execution and all road-data acceptance gates remain open.

## 2026-10-10 remediation record — not independent database sign-off

Closed by code change and executed regressions: JSON enum/const boolean-vs-number
comparison (recursive objects/arrays); minLength now evaluates the original string.
The nonblank policy is explicit in the checked-in schema via pattern `\S`.
Original 16 tests plus seven new tests pass (23 total). Full independent-engine
comparison remains blocked; compare_schema_engine.py reports NOT RUN, exit 2.

Database remediation is a candidate, NOT accepted: direct restriction writes
are completely closed pending a controlled adapter; audit includes before/after,
full composite keys and transaction/session identity; endpoint source/revision
checks and immutable node identity are proposed; fresh-only checksummed migration
runner refuses unversioned existing schemas. No migrations applied.

Remaining HIGH gates: execute PostGIS tests (including roles/concurrency/migration
failure rollback), implement and review controlled ingest before opening writes,
protect evidence retention from privileged tampering, detect schema drift,
validate cross-source spatial reconciliation and actual source/reviewer trust.
No claim of completed SQL invariant protection is made without execution.
Overall stage 2 remains INCOMPLETE; PR must remain Draft; DO NOT MERGE/DEPLOY.
