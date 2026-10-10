# Stage 2 — official-source discovery and license review

Checked: 2026-10-09T08:59:32Z. Researcher: `ai-agent-official-sources`.
Baseline read: `docs/DATA_VERIFICATION.md`, `docs/PRODUCT_REQUIREMENTS.md`, `data/readme.md`.

This is an initial source-discovery result, not nationwide data collection. Eight candidates are recorded in `data/source-candidates.json`; **zero datasets acquired, zero restrictions verified, zero sources approved for import or route-safety confirmation**. Search-index snippets establish discovery leads only. They are not evidence that a restriction remains in force.

## Actual checks and results

| Candidate | Evidence actually available | Outstanding gate |
|---|---|---|
| [Data.gov.il license](https://data.gov.il/he/terms-of-use) | Full current page retrieved; page states update 2025-08-30 | Apply to each concrete dataset; check overrides and third-party rights |
| [MOT national road numbers](https://www.gov.il/he/pages/national-road-number-maps) | Official-domain search result; direct fetch returned 403 | Read publication, attachments, versions and licensing |
| [MOT map sheet 04](https://www.gov.il/BlobFolder/generalpage/national-road-number-maps/he/Roadnumbers_04_20260311.pdf) | Indexed PDF title/text identifies Emek Yizrael road-number sheet; direct fetch returned 403 | Acquire bytes, inspect legend/date/rights; do not infer date from filename |
| [Hatzav](https://geo.mot.gov.il/) | Official indexed MOT page links this portal; direct fetch timed out | Inventory actual layers, ownership, update dates and export rights |
| [Govmap](https://www.govmap.gov.il/) | Indexed official mapping portal; direct result contained no extractable text | Inspect layer-specific terms, metadata and geometry access |
| [Govmap API filter documentation](https://api.govmap.gov.il/docs/javascript-functions/filter-layers) | Indexed official documentation describes layer filtering; documentation root fetch returned 403 | Access/token conditions and reuse rights, independently of API existence |
| [Israel Police](https://www.gov.il/he/departments/israel_police) | Indexed official agency portal; direct fetch returned 403 | Authenticate feed, timestamps, correction/expiry semantics and reuse terms |
| [Netivei Israel](https://www.iroads.co.il/) | Indexed operator portal mentions traffic control; direct fetch returned 403 | Obtain bridge/road datasets, completeness statements and license |

The map and operator sources are not claimed to contain a complete truck restriction inventory. No live police closure has been copied into the restriction database. Search also surfaced a Telegram channel with a police-like name; it was excluded from the candidate registry because an authoritative linking/authentication chain was not checked. Messages must not be promoted to official notices on name or logo alone.

## License findings

The Data.gov.il terms reviewed above permit commercial and noncommercial reuse under conditions. A dataset's own license overrides the portal default. Terms applicable at acquisition time govern use. Attribution is required subject to stated exceptions; misleading presentation and implied state endorsement are prohibited. Third-party rights and certain other categories are excluded. Data is provided without fitness/completeness assurances; official written publications prevail on conflict. This policy is not a license for every government website, Govmap layer, PDF map, API or background basemap.

No bulk map download, copied map tiles, digitization, redistribution or production ingestion is authorized by this research. Before approving a dataset, preserve its exact resource identifier/version, owner, acquisition timestamp, applicable license URL/version and conditions. Record separately whether extraction, storage, transformation, redistribution and commercial routing are permitted. Unresolved rights keep import blocked.

## Acceptance criteria for next acquisition pass

1. Acquire a concrete resource through documented authorized access; retain acquisition log, content hash and format/CRS metadata, with evidence-retention rights checked.
2. Confirm publisher authority and scope for the specific road or restriction. Distinguish national agencies, road operators and municipal authority.
3. Determine spatial coverage, excluded roads, publication/effective dates, review/expiry rule, update mechanism and known incompleteness. Do not infer coverage from a national-sounding title.
4. Resolve dataset and embedded-layer rights before storing/redistributing raw data. A portal/API discovery is not dataset approval.
5. Restriction records require source, observation date, checked timestamp, verifier, location/segment, direction, applicable vehicle class, units, validity and confidence. Missing restrictions remain unknown.
6. Independent audit must review evidence and contradictions before a record can become verified. Fresh verified restrictions alone do not prove complete route safety.

## Problems and work log

- Read repository verification and product requirements; retained existing fail-closed policy.
- Searched primary official domains using Hebrew road/mapping/police/license queries.
- Opened license, MOT publication/PDF, Hatzav, Govmap, API documentation root, police and road operator URLs.
- Recorded 403 responses, timeout and empty-text result rather than claiming successful dataset access. These are tool-specific observations, not proof that sources are globally unavailable.
- Created machine-readable discovery registry with every `approved_for_import` and `may_support_route_safety` set to false.
- Nationwide coverage, municipal restrictions, bridge heights/load limits, tunnels, axle loads, hazardous-goods restrictions and closures all remain unverified in this pass.
- No application deployment, route certification, external contact, account registration or main-branch modification performed by this agent.
