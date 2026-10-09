# Stage 2 — truck restriction evidence specification

Research checkpoint: 2026-10-09 (Asia/Jerusalem). Author role: truck restriction specialist. Based on existing `docs/DATA_VERIFICATION.md` and `docs/PRODUCT_REQUIREMENTS.md`; this extends their draft policy, not a replacement project plan.

**Outcome:** official reference sources identified; zero road-specific restrictions verified or imported by this task. Nationwide coverage remains unknown. This document is a research specification, not navigation or legal clearance.

## Separate three kinds of evidence

1. Vehicle/load legality: national rules, vehicle registration conditions, dimensions of the loaded combination, actual and permitted mass, axle configuration and applicable permits.
2. Road restriction: an authenticated order or sign applying to a precisely identified road segment, carriageway, lane or manoeuvre during a specified period.
3. Physical infrastructure: measured clearance, structural capacity and geometry. A design guideline or planned clearance does not establish present as-built clearance. A tunnel/bridge inventory is not a clearance inventory.

Passing a national vehicle limit does not establish that any road is suitable. A permit is applicable only to its vehicle, load, route, date and conditions; it cannot be converted into general road permission. User reports and community map tags remain separately attributed evidence and are never described as official.

## Official sources actually checked

All access observations below were made on 2026-10-09. Access date is not publication date or verification of current legal force. No numeric road limits were inferred from these sources. No documents were redistributed; source-specific reuse permission remains pending.

| Reference | Source and URL | Actual observation | Acceptance / remaining gap |
|---|---|---|---|
| R-01 | Israel Police, procedure 02.240.11, [oversize cargo permits](https://www.police.gov.il/menifa/07.02.240.11_2.pdf) | Opened 22-page PDF; cover identifies version 2, publication and commencement 2024-03-05. Procedure concerns oversize movement, permit handling and route assessment. | Authentic official-host document retrieved. Supersession check and full legal review outstanding. General procedure, not a nationwide road-restriction dataset. |
| R-02 | Ministry of Transport, [imported dangerous goods and lithium battery transport permits](https://www.gov.il/he/service/permit-transporting-materials-imported-from-abroad) | Service page opened. It describes vehicle/driver permit requirements and route documentation; additional approvals depend on load circumstances. Publication/update date not established. | Its imported-cargo service scope must be preserved. Does not prove a general tunnel ban or permission for any cargo class. Current permit conditions and road-specific orders still needed. |
| R-03 | National Road Safety Authority, [commercial vehicle legislation](https://www.gov.il/he/pages/legislations_truck) | Found in search; direct fetch returned HTTP 403. | Discovery lead only. No current numeric rule accepted from search excerpts. Obtain readable official text and confirm amendments. |
| R-04 | Ministry of Transport, [traffic sign regulations / placement guidance PDF](https://www.gov.il/BlobFolder/policy/2020_tamrur_0/he/%D7%AA%D7%A7%D7%A0%D7%95%D7%AA%20%D7%95%D7%94%D7%A0%D7%97%D7%99%D7%95%D7%AA%20%D7%9C%D7%94%D7%A6%D7%91%D7%AA%20%D7%AA%D7%9E%D7%A8%D7%95%D7%A8%D7%99%D7%9D%202024.pdf) | Search result title says 2022, URL filename says 2024. PDF not opened in this task. | Discovery lead with edition ambiguity; inspect cover and amendments before mapping sign semantics. It supplies no proof a sign is installed at a particular location. |

## Required restriction families

| Family | Evidence and applicability to preserve | Unsafe shortcut to reject |
|---|---|---|
| Height | Posted limit versus measured clearance; loaded vehicle including equipment; lane and direction; measurement method/uncertainty and resurfacing date where available | Using general permitted vehicle height as bridge clearance |
| Width | Posted width versus usable physical width; vehicle/load scope, lane, temporary works and escorts | Deriving width permission from mapped lane count |
| Length | Whole combination versus individual vehicle/load; articulated configuration; turn-specific applicability | Assuming permitted length implies a feasible turning path |
| Mass | Actual gross versus maximum authorized mass, combination versus vehicle; bridge/road scope and exceptions | Comparing empty weight against a gross-mass restriction |
| Axle load | Per-axle versus axle-group threshold, spacing/configuration and relevant vehicle/manufacturer conditions | Dividing gross weight by axle count to claim compliance |
| Dangerous goods | Exact official classification, UN/class where stated, quantity/packaging, vehicle/driver permit, route and tunnel conditions | Importing foreign tunnel classifications without Israeli authority evidence |
| Truck access | Vehicle class and threshold basis; through traffic versus deliveries; permits, zone boundary, direction and operating calendar | Treating an exception for deliveries as universal access |
| Temporary / emergency | Issuer, order identifier, exact start/end, cancellation/supersession, works/closure and approach affected | Treating an old announcement or absent end date as current road clearance |

## Acceptance criteria for each evidence record

- Preserve source issuer, exact URL/document identifier, official/community classification, pinpoint page/section, publication date if available, observation date, access date, verifier identity/time, review deadline, and license/reuse decision. Unknown dates must be explicit, never replaced by retrieval time.
- Preserve original Hebrew wording and a reviewed translation; record extraction/OCR uncertainty. A search snippet is insufficient for verification. Keep an authorized snapshot/hash where licensing permits reproducible evidence retention.
- Retain original quantity/unit and normalized quantity/unit (metres, kilograms, or tonnes with explicit conversion). Require threshold operator and weight basis. Never silently round clearance upward or mass thresholds upward.
- Identify source geometry CRS, normalized coordinates or stable road segment IDs, graph version, endpoints, carriageway/direction, lane and spatial uncertainty. A sign coordinate alone does not define restriction extent. Do not snap an overpass sign to the road below.
- Preserve valid-from/valid-to, recurring calendar, Asia/Jerusalem time zone, holidays and exceptions. Unknown time applicability cannot be interpreted as unrestricted.
- Preserve vehicle type/configuration, actual and authorized mass where needed, axle grouping, loaded dimensions, cargo classification and permit scope. Missing decision-relevant profile fields mean unknown applicability.
- Use existing statuses `unverified`, `verified`, `disputed`, `expired`. Authentication of a website alone is not verification of a restriction. Require a complete record, current applicable evidence, justified spatial match and independent review before promotion.
- Preserve contradictory evidence instead of overwriting it. Put affected decisions on hold pending review; choosing the smaller number does not resolve different lane, class, time or mass-basis semantics.
- Unknown or expired evidence must never support a positive suitability claim. A suspected hazard may justify a provisional exclusion with its provenance disclosed; it must not become an official restriction merely because it is conservative.
- Permit exceptions require explicit, current scope matching. Do not store personal permit documents or identifying driver data in the public repository.

## Execution backlog and acceptance gates

| Task | Required output / acceptance | Current result |
|---|---|---|
| TR-01 National legality baseline | Current official consolidated vehicle/load rules and amendments; dimension/mass/axle interpretation reviewed, distinct from road dataset | Open: R-01/R-02 useful process evidence; R-03 inaccessible |
| TR-02 Sign semantics | Confirm R-04 edition and official sign identifiers; supplementary plates, operators, classes and directions covered | Open: edition conflict logged |
| TR-03 Road restriction acquisition | Licensed authority records for bridges, tunnels, national and municipal roads, with segment scope and validity | Open: no verified road records obtained |
| TR-04 Hazmat and exceptions | Applicable official classes and route/tunnel conditions, current orders and permit exception model | Open: R-02 is a scoped service reference only |
| TR-05 Temporal bans | Authority-backed daily/weekly/holiday restrictions and live closure expiry/cancellation process | Open: no current countrywide feed verified |
| TR-06 Independent adjudication | Independent review of each proposed verified record and meaningful tests for unit, scope, direction, calendar, conflict and missing-data failures | Pending evidence acquisition; this report has no routing-ready records |

## Work log and limitations

### Continuation: actual road-specific acquisition attempt

Checkpoint `2026-10-09T09:22:33Z` (host clock normalized to UTC). Search/review occurred before this checkpoint; individual request timestamps were not retained. Acquisition results are logged in `data/acquisition/restriction-discovery-20261009.json`; these are **discovery/rights-review records, not routing restriction records**.

- Carmel Tunnels: located the operator's safety page, then opened its terms. Clause 7 restricts use to private purposes and requires prior written permission for copying, publication and commercial use. Consequently no numeric restriction, geometry, closure schedule, source snapshot or operational record was imported. Operator material must be distinguished from a government traffic order. Permission and current authoritative spatial/temporal applicability are unresolved.
- Route 1: Ministry of Transport `nativ-plus-harel` page surfaced as a potentially relevant truck-access source, but direct retrieval returned HTTP 403. General gov.il terms retrieval also returned 403. Search excerpts were not promoted into facts or route records. Exact restriction extent, weight basis, exceptions, calendar and current force remain unverified.
- Older official material surfaced, including a 2008 Knesset study and a 2020 government report. Historical reports are not current traffic orders; no thresholds were accepted. Police incident notices lacked established current validity in this pass and were not converted into live closures.
- Searches found no acceptable current road-specific length, gross-mass or axle-load record in this pass. This is a research outcome, not evidence that such restrictions do not exist.

Next acquisition gate: obtain an explicitly reusable authority dataset/order or written operator permission; then retain the source revision, current applicability and exact segment/direction before independent verification. No permission request was sent externally. **Verified road restriction count from this task remains zero.**

2026-10-09: read existing verification/product requirements; searched official government, police and municipal domains; retrieved R-01 and R-02; documented blocked R-03 and unresolved edition R-04. Secondary legal websites and historical/proposed municipal material were excluded as a basis for current restrictions. No coverage percentage can be computed without a known denominator and authority inventories. No deployment, main-branch change, route-safety certification or background monitoring performed by this task.
