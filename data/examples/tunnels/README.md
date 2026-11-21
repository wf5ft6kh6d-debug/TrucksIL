# ADR tunnel categories — template (FICTIONAL data only)

`tunnel-template.fictional.json` shows how one tunnel's ADR category is stored as a TrucksIL
restriction (`restrictionType: "adr_tunnel"`, `unit: "adr_tunnel_category"`, `value`: `"B"`..`"E"`).
The coordinates and category are **invented**; this is not a real Israeli tunnel. See ADR-0013.

Rules for real records (ADR-0002, `docs/DATA_VERIFICATION.md`):

- Only enter a category that is **sourced** (official sign photo, Ministry of Transport /
  operator regulation). Put the document in `source.reference`/`source.url`, `valueSource: "regulation"`
  or `"posted_sign"`.
- Use a `LineString` covering the tunnel bore (one record per bore if directions differ, with `direction`).
- Category A (no restriction) is not stored. Unknown category → do not invent one; leave the tunnel out
  (and remember: absence of a record does not mean the tunnel is open to dangerous goods).
- New records start as `unverified`; `verified` needs `verifiedBy` / `verifiedAt`.

Known Israeli road tunnels to research — **names only, categories NOT verified, none assumed**
(TO VERIFY: existence of an ADR/dangerous-goods restriction, category, exact geometry, source):

- Carmel Tunnels (מנהרות הכרמל), Haifa
- Har HaTsofim / Mount Scopus tunnels (Route 1, Jerusalem)
- Begin Boulevard / Route 50 tunnels, Jerusalem (TO VERIFY names)
- Tunnels road (כביש המנהרות, Route 60, south of Jerusalem)
- Route 6 tunnels (e.g. near Ein Tut / northern section — TO VERIFY)
- Route 1 Har HaRuach / Motza area tunnels (TO VERIFY)
