#!/usr/bin/env node
'use strict';
// Reference route scenarios against a running stack (db + api + Valhalla). DEV ONLY.
//   DATABASE_URL=postgres://trucksil:<password>@localhost:5432/trucksil npm run test:e2e
//   API_URL (default http://localhost:8080), E2E_ONLY=S02,S03 to run a subset.
// For each scenario: baseline route via the API -> seed FICTIONAL restrictions (ids 'e2e-*', source
// 'e2e-fictional') -> POST /v1/route -> check expectations -> ALWAYS delete the seeded rows.
// Scenarios marked "mockOnly" in test/scenarios/routes.json are skipped (they need a mock Valhalla).
const { Pool } = require('pg');
const S = require('../test/scenarios/lib');

const API_URL = (process.env.API_URL || 'http://localhost:8080').replace(/\/+$/, '');
const ACTOR = 'e2e_routes';
// E2E_STRICT=1: absolute expectations (reroutes ranges, baseline failure = FAIL) as before ADR-0016.
const STRICT = process.env.E2E_STRICT === '1';

async function postRoute(s) {
  const r = await fetch(`${API_URL}/v1/route`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ from: s.from, to: s.to, vehicle: s.vehicle }),
    signal: AbortSignal.timeout(60000),
  });
  let body;
  try { body = await r.json(); } catch { body = {}; }
  return { status: r.status, body };
}

async function deleteSeeded(db, ids) {
  if (!ids.length) return 0;
  await db.query("SELECT set_config('trucksil.actor', $1, false)", [ACTOR]);
  return (await db.query('DELETE FROM restrictions WHERE id = ANY($1::text[])', [ids])).rowCount;
}

async function seed(db, r, geometry) {
  const bool = r.unit === 'boolean';
  const text = r.unit === 'adr_tunnel_category';
  const verified = r.status === 'verified';
  await db.query("SELECT set_config('trucksil.actor', $1, false)", [ACTOR]);
  await db.query(`
    INSERT INTO restrictions (id, road_segment_id, geometry, value_source, restriction_type, value_numeric, value_boolean,
                              value_text, unit, time_windows, status, source, observed_at, verified_by, verified_at, direction)
    VALUES ($1, 'e2e-fictional', ST_SetSRID(ST_GeomFromGeoJSON($2), 4326), $3, $4, $5, $6, $13, $7, $8::jsonb, $9,
            '{"name":"e2e-fictional","reference":"FICTIONAL test data, scripts/e2e_routes.js"}', now(), $10, $11, $12)`,
  [r.id, JSON.stringify(geometry), r.valueSource ?? null, r.type, bool || text ? null : r.value, bool ? r.value : null, r.unit,
    r.timeWindows ? JSON.stringify(r.timeWindows) : null, r.status, verified ? 'e2e-fictional' : null, verified ? new Date() : null, r.direction ?? 'both', text ? r.value : null]);
}

async function runScenario(db, s) {
  const ids = s.restrictions.map((r) => r.id);
  try {
    await deleteSeeded(db, ids); // leftovers from an interrupted run
    const base = await postRoute({ ...s });
    if (base.status !== 200) {
      const ev = S.evaluateRelative(s, base, null, { strict: STRICT });
      return { skip: ev.result === 'SKIP', fails: ev.fails, notes: ev.notes };
    }
    const shape = S.routeShape(base.body);
    if (!shape.length) return { fails: ['baseline route has no shape'] };
    for (const r of s.restrictions) await seed(db, r, S.resolveGeometry(r.where, shape));
    const res = await postRoute(s);
    const ev = S.evaluateRelative(s, base, res, { strict: STRICT });
    const t = res.body.trucksil || {};
    return { fails: ev.fails, notes: ev.notes, status: res.status, reroutes: t.reroutes };
  } finally {
    await deleteSeeded(db, ids);
  }
}

async function main() {
  if (!process.env.DATABASE_URL) { console.error('DATABASE_URL is not set (see .env / docs/DEV_SETUP.md)'); process.exit(2); }
  const only = process.env.E2E_ONLY ? new Set(process.env.E2E_ONLY.split(',').map((x) => x.trim())) : null;
  const db = new Pool({ connectionString: process.env.DATABASE_URL, max: 1 });
  const rows = [];
  try {
    const h = await fetch(`${API_URL}/health`).then((r) => r.json()).catch((e) => ({ error: e.message }));
    console.log(`mode: ${STRICT ? 'STRICT (absolute)' : 'relative to baseline (E2E_STRICT=1 for absolute)'}`);
    console.log(`API ${API_URL} health: ${JSON.stringify(h)}`);
    for (const s of S.loadScenarios()) {
      if (only && !only.has(s.id)) continue;
      if (s.mockOnly) { rows.push({ id: s.id, result: 'SKIP', detail: 'mock-only (covered by npm test)' }); continue; }
      let r;
      try { r = await runScenario(db, s); } catch (e) { r = { fails: [`error: ${e.message}`] }; }
      const extra = [r.status !== undefined ? `HTTP ${r.status}` : null, r.reroutes !== undefined ? `reroutes ${r.reroutes}` : null, ...(r.notes || [])].filter(Boolean);
      rows.push({ id: s.id, result: r.skip ? 'SKIP' : r.fails.length ? 'FAIL' : 'PASS', detail: [...r.fails, ...extra].join('; '), description: s.description });
    }
    const left = await db.query("SELECT count(*)::int AS n FROM restrictions WHERE id LIKE 'e2e-%'");
    if (left.rows[0].n) rows.push({ id: 'cleanup', result: 'FAIL', detail: `${left.rows[0].n} e2e-* row(s) left in restrictions` });
  } finally {
    await db.end();
  }
  console.log('');
  console.log(`${'ID'.padEnd(8)} ${'RESULT'.padEnd(6)} DETAIL`);
  for (const r of rows) console.log(`${r.id.padEnd(8)} ${r.result.padEnd(6)} ${r.detail}${r.result === 'FAIL' && r.description ? `  [${r.description}]` : ''}`);
  const failed = rows.filter((r) => r.result === 'FAIL').length;
  const passed = rows.filter((r) => r.result === 'PASS').length;
  console.log(`\n${passed} passed, ${failed} failed, ${rows.filter((r) => r.result === 'SKIP').length} skipped`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e.stack || e.message); process.exit(1); });
