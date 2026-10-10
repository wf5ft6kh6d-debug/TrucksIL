# Stage 2 — cartographic source investigation

Investigation date: 2026-10-09 (UTC). Agent: cartographer.
Baseline read: `docs/ARCHITECTURE.md`, `docs/DATA_VERIFICATION.md`,
`docs/PRODUCT_REQUIREMENTS.md`, `docs/README.md`. These label the architecture and
verification rules as drafts; this report implements the stage-2 data investigation
without claiming an additional approved plan exists in the repository.

## Actual result and safety boundary

Primary-source discovery and license-page inspection completed. **No road graph,
national inventory, bridge clearance, tunnel clearance or truck restriction was
downloaded or verified by this investigation.** Source discovery is not feature
verification. All territory-wide coverage remains unknown. Navigation remains gated.

## Source ledger

All URLs below were investigated on 2026-10-09. `opened` means page text was returned
by the web retrieval tool, not an authenticated download of its underlying data.
`indexed` means a search engine returned an official-domain excerpt; dataset schema,
feature count, freshness and precise reuse terms still require resource retrieval.

| ID | Primary source and evidence | Intended use | Access/license and limitations |
| --- | --- | --- | --- |
| CART-01 | [Geofabrik Israel and Palestine](https://download.geofabrik.de/asia/israel-and-palestine.html), opened; lists PBF, SHP, GeoPackage, polygon boundary and change files. PBF listing stated data through `2026-10-08T20:21:06Z`. | Candidate base road graph and infrastructure discovery. Prefer PBF to preserve source objects and relationships. | Dataset itself not acquired. Extract spans Israel and Palestine: it is not a validated operational service boundary. OSM is community data, not official government confirmation. |
| CART-02 | [OSM copyright](https://www.openstreetmap.org/copyright), opened. | License basis for CART-01. | ODbL, attribution and applicable share-alike obligations. Source licenses must remain distinct when joining government data. Public map/API/tile services have separate policies. Do not scrape map tiles as a road database. |
| CART-03 | [MOT national road numbers](https://data.gov.il/he/datasets/ministry_of_transport/roadnumbers), indexed; direct open returned only a loading shell. | Road identifier reconciliation; catalog describes segments assigned national road numbers. | Not established as a complete routable network. Individual resource and license not retrieved. |
| CART-04 | [MOT tunnel metadata](https://data.gov.il/he/datasets/ministry_of_transport/tunnels/3fe6e54c-88ef-449d-a77e-5904062a17b4), indexed. | Candidate tunnel inventory; inspect actual resource and metadata before treating objects as road tunnels. | No feature count, extent, dimensions or current operational state verified. Do not substitute rail-tunnel layers. |
| CART-05 | [MOT rail/road grade separations](https://data.gov.il/he/datasets/ministry_of_transport/levelseparation), indexed; description names location, separation name and maintaining body. | Candidate crossing/bridge objects and responsible-operator linkage. | Covers this class of crossing, not all bridges. Does not establish vertical clearance or load capacity. Resource/license pending. |
| CART-06 | [MOT traffic-light junctions](https://data.gov.il/he/datasets/ministry_of_transport/traffic_light_junction), indexed. | Junction cross-check and topology QA leads. | Signals alone neither define permitted turns nor prove truck turning feasibility. Resource/license pending. |
| CART-07 | [MOT junction/interchange names](https://data.gov.il/he/datasets/ministry_of_transport/zmt_names), indexed; catalog describes sign names using a 2025 edition. | Name matching and identity disambiguation. | Limited sign-name inventory, not all junctions or interchange ramp geometry. Resource/license pending. |
| CART-08 | [MOT interchange-area metadata PDF](https://data.gov.il/dataset/interchange_areas/resource/119b95b8-f62e-465c-9056-e819b9494d9f/download/interchange_areas.pdf), opened. | Planning context only: areas enclosed by interchange ramps. | Metadata states Israel_TM_Grid and Creative Commons Attribution; exact license version and attachment applicability need confirmation. These polygons are not a drivable network. |
| CART-09 | [MOT GIS portal](https://geo.mot.gov.il/), indexed. | Official discovery interface for transport layers and metadata. | Viewer availability does not authorize unrestricted extraction, redistribution or route-safety certification. |
| CART-10 | [Data.gov.il terms](https://data.gov.il/he/terms-of-use), opened; displayed update 2025-08-30. | Default licensing review for government catalog datasets. | Permits commercial reuse subject to conditions; attached dataset licenses take priority. Attribution, excluded rights and acquisition-time terms must be checked. No blanket approval for all government map products. |

Evidence limits: source HTML and binary datasets were not archived. Reproduce the
investigation by opening these exact URLs and recording retrieval time, content hash,
response status, publisher, resource ID and resource-specific license before import.
Search excerpts may be stale. A successful catalog lookup does not demonstrate an
accessible or complete download.

## Acquisition and graph construction work package

1. Record the actual downloaded PBF URL, server/data timestamp, SHA-256, byte count,
   extraction polygon, attribution and license URL in an acquisition manifest. Store
   raw bytes outside Git; commit the manifest and reproducible acquisition script.
2. Keep the original extract intact. Add an explicit versioned operational-area
   polygon and jurisdiction review; a rectangular bounding box or provider filename
   must not silently define where the application may guide drivers. Outside-scope
   edges stay excluded or unknown, never implicitly authorized.
3. Preserve source way/node/relation IDs, versions where available, raw tags and
   directed segment identity. Maintain a graph-build version so restrictions can be
   re-linked or quarantined when geometry changes. A source update timestamp is not
   a field-observation or restriction-verification timestamp.
4. Split roads at true connections; preserve grade separation, ramps, one-way
   direction, turn relations and carriageways. Crossing lines are not automatically
   connected. Bridge/tunnel labels describe infrastructure, not clearance.
5. Fetch official resources through documented downloads after dataset-specific
   licensing review. Preserve their declared CRS and original geometry; transform
   explicitly into the repository's selected canonical CRS. Do not infer CRS from
   the appearance of coordinate numbers alone.
6. Match infrastructure to the directed road and structure it actually affects.
   An overbridge weight limit concerns its deck; an underpass height limit concerns
   the road below it. Nearest-road snapping alone cannot decide this relationship.
7. Put ambiguous matches in a review queue. Keep original identities and all
   candidate matches; never overwrite contradictory geometry silently.

These are proposed acquisition steps, not a claim that an importer or graph exists.

## Coverage and acceptance criteria

For every region, road authority and road class, publish a denominator and measured
counts for graph edges, bridges, tunnels, junctions and each restriction family.
Until an authoritative denominator is obtained, report **unknown completeness**;
do not convert a mapped-feature count into a percent of national coverage.

Acceptance requires:

- Reproducible raw-file manifest, successful parse and CRS checks; license decision
  and required attribution attached to each acquired dataset.
- Separate current, planned, under-construction and closed road states; planned
  layers cannot enter an operational graph merely because they contain geometry.
- Auditable topology tests: false bridge intersections, dangling ramps, unexpected
  disconnected components, duplicate carriageways, impossible turn connections,
  border clipping and stale source-to-edge associations.
- Human-reviewed samples for each road class/region and every ambiguous structural
  crossing, with an explicit sampling method and unresolved-error inventory.
- Restriction coverage tracked independently of road geometry coverage. Missing
  height/weight/access evidence remains unknown even on a connected mapped road.
- No positive route-safety verdict from this research or from OSM-only tags.

## Open problems / next tasks

| Issue | Severity | Required next evidence |
| --- | --- | --- |
| No acquired road graph or measured national coverage | Blocking | Licensed, hashed extract; graph build and explicit scope review |
| No complete authoritative bridge/road-tunnel inventory established | Blocking | Operator inventories and declared completeness, including local roads |
| Official catalog descriptions not equivalent to downloaded resources | Blocking | Resource bytes, metadata, source date and license snapshots |
| Height, width, weight and turning feasibility not implied by infrastructure | Blocking | Applicable current restriction evidence linked to direction/structure |
| Road ownership and jurisdiction gaps | Blocking | Reviewed authority boundaries and responsible-body mapping |
| Government/OSM combined-database licensing unresolved | Blocks redistribution | Dataset-specific compatibility decision before publishing merged data |
| Temporary works, closures and changed layouts not covered by static extracts | Blocking for guidance | Authenticated current notices and expiry/update workflow |

Task log: read four existing documents; searched government/OSM primary sources;
opened Geofabrik, OSM licensing, Data.gov.il licensing and interchange metadata;
recorded source-access limits; produced this report. No provider was contacted,
no paid service was activated, and no application was deployed.
