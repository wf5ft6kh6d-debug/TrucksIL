#!/usr/bin/env node
'use strict';
// Explains which TrucksIL restrictions a route avoids and why (ADR-0016), using POST /v1/route?debug=1.
// Usage: node scripts/explain_route.js <fromLon,fromLat> <toLon,toLat> [heightM] [grossWeightT]
//   API_URL (default http://localhost:8080). Example (Tel Aviv -> Jerusalem, 4.0 m / 40 t):
//   node scripts/explain_route.js 34.7818,32.0853 35.2137,31.7683 4.0 40
const API_URL = process.env.API_URL || 'http://localhost:8080';

function osmLink(c) {
  if (c.sourceUrl) return c.sourceUrl;
  const m = /^osm:way:(\d+)$/.exec(c.roadSegmentId || '');
  return m ? `https://www.openstreetmap.org/way/${m[1]}` : '-';
}

async function main() {
  const [from, to, h = '4.0', w = '40'] = process.argv.slice(2);
  if (!from || !to) { console.error('usage: explain_route.js <fromLon,fromLat> <toLon,toLat> [heightM] [grossWeightT]'); process.exit(2); }
  const pt = (s) => s.split(',').map(Number);
  const vehicle = { profileName: 'explain', heightM: Number(h), widthM: 2.55, lengthM: 16.5, grossWeightT: Number(w), axleLoadT: 11.5 };
  const r = await fetch(`${API_URL}/v1/route?debug=1`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ from: pt(from), to: pt(to), vehicle }), signal: AbortSignal.timeout(120000),
  });
  const body = await r.json();
  const t = body.trucksil && body.trucksil.debug ? body.trucksil : body;
  const dbg = t.debug || {};
  console.log(`HTTP ${r.status}${body.error ? ` - ${body.error}` : ''}; reroutes ${t.reroutes ?? '-'}`);
  if (dbg.config) console.log(`config: ${JSON.stringify(dbg.config)}`);
  for (const it of dbg.iterations || []) {
    console.log(`\n#${it.attempt}: ${it.exclusions} exclusion(s) + ${it.preExclusions} pre, ${it.rings} ring(s), perimeter ${it.perimeterM} m, way match ${it.wayMatch || '-'}${it.result ? `, ${it.result}` : ''}`);
    for (const c of it.conflicts || []) console.log(`  CONFLICT ${c.id}  ${c.type} ${c.value} ${c.unit || ''} [${c.status}] ${c.reason || ''}  ${c.sourceName || ''} ${osmLink(c)}`);
    if ((it.otherRoad || []).length) console.log(`  ignored (other road, not driven on): ${it.otherRoad.join(', ')}`);
    if ((it.preAdded || []).length) console.log(`  pre-excluded: ${it.preAdded.length}`);
  }
  if (dbg.preExclusionDropped) console.log(`\npre-exclusions dropped after Valhalla error: ${dbg.preExclusionDropped.ids.length}`);
  if (body.blockingCandidates) console.log(`\n422 blocking candidates (added in the last step): ${body.blockingCandidates.join(', ')}`);
  console.log(`\navoided (${(t.avoided || []).length}):`);
  for (const a of t.avoided || []) console.log(`  ${a.id}  ${a.restrictionType} ${a.value} [${a.status}] ${a.reason || ''}`);
  console.log(`onRoute: ${(t.onRoute || []).length}`);
}

main().catch((e) => { console.error(e.message); process.exit(1); });
