'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createServer } = require('../../api/src/app');
const { encodePolyline } = require('../../api/src/polyline');
const R = require('../../api/src/reports');

const SALT = 'test-salt';
const CID = 'client-aaaaaaaaaaaaaaaa';
const CID2 = 'client-bbbbbbbbbbbbbbbb';
const T0 = new Date('2026-11-15T10:00:00Z');

/** In-memory fake of createReportsRepo (same contract). */
function fakeRepo() {
  const rows = new Map(); const votes = new Set(); const audit = []; const calls = [];
  let n = 0;
  return {
    rows, audit, calls,
    async insert(r) {
      const id = `00000000-0000-4000-8000-${String(++n).padStart(12, '0')}`;
      const row = { id, type: r.type, lon: r.position[0], lat: r.position[1], note: r.note, created_at: r.createdAt, expires_at: r.expiresAt, status: 'visible', confirmations: 0, rejections: 0, reporter_hash: r.reporterHash };
      rows.set(id, row); return row;
    },
    async listBbox(b, now) { calls.push(['bbox', b, now]); return [...rows.values()].filter((r) => r.status === 'visible' && r.expires_at > now); },
    async nearRoute(coords, now, m) { calls.push(['near', coords, now, m]); return [...rows.values()].filter((r) => r.status === 'visible' && r.expires_at > now); },
    async get(id) { return rows.get(id) || null; },
    async vote(id, h, v) {
      const k = `${id}|${h}`; if (votes.has(k)) return null; votes.add(k);
      const r = rows.get(id); if (v === 'confirm') r.confirmations++; else r.rejections++; return { ...r };
    },
    async setStatus(id, status, a) { const r = rows.get(id); if (!r) return null; r.status = status; audit.push({ id, ...a }); return { ...r }; },
  };
}

async function withServer(deps, fn) {
  const server = createServer(deps);
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try { return await fn(base); } finally { await new Promise((r) => server.close(r)); }
}
async function call(base, path, { method = 'GET', body, headers = {} } = {}) {
  const r = await fetch(base + path, { method, headers: { 'content-type': 'application/json', ...headers }, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
}
const asClient = (cid = CID) => ({ [R.CLIENT_HEADER]: cid });
const report = (o = {}) => ({ type: 'hazard', position: [34.78, 32.08], note: 'oil on road', ...o });

function deps(extra = {}) {
  let now = T0;
  const repo = fakeRepo();
  return { repo, setNow: (d) => { now = d; }, deps: { db: null, reportsRepo: repo, reports: { salt: SALT, now: () => now, ...extra } } };
}

test('validateReport: type, Israel bbox, note length', () => {
  assert.equal(R.validateReport(report()).ok, true);
  assert.equal(R.validateReport(report({ type: 'police' })).ok, false);
  assert.equal(R.validateReport(report({ position: [2.35, 48.85] })).ok, false); // Paris
  assert.equal(R.validateReport(report({ position: [34.78] })).ok, false);
  assert.equal(R.validateReport(report({ note: 'x'.repeat(280) })).ok, true);
  assert.equal(R.validateReport(report({ note: 'x'.repeat(281) })).ok, false);
  assert.equal(R.validateReport(report({ note: 'א'.repeat(280) })).ok, true);
  assert.equal(R.validateReport(report({ note: 5 })).ok, false);
  assert.equal(R.validateReport(report({ note: '   ' })).value.note, null);
  assert.equal(R.validateReport([]).ok, false);
});

test('TTL by type', () => {
  const h = 3600e3;
  assert.deepEqual(Object.fromEntries(R.REPORT_TYPES.map((t) => [t, R.ttlFor(t) / h])), { traffic: 1, accident: 3, hazard: 12, camera: 720, low_clearance: 720, other: 6 });
  assert.equal(R.expiresAt('accident', T0).toISOString(), '2026-11-15T13:00:00.000Z');
});

test('client id hashing: salted, no raw id; invalid ids rejected', () => {
  assert.equal(R.validClientId(CID), true);
  assert.equal(R.validClientId('short'), false);
  assert.equal(R.validClientId('bad id with spaces!!!!'), false);
  const h = R.hashClient(CID, SALT);
  assert.match(h, /^[0-9a-f]{64}$/);
  assert.notEqual(h, R.hashClient(CID, 'other'));
  assert.ok(!h.includes(CID));
});

test('rate limiter: 5 per 10 minutes per key', () => {
  const l = R.createRateLimiter();
  for (let i = 0; i < 5; i++) assert.equal(l.take('a', i * 1000).ok, true);
  const r = l.take('a', 6000);
  assert.equal(r.ok, false);
  assert.ok(r.retryAfterS > 0);
  assert.equal(l.take('b', 6000).ok, true);
  assert.equal(l.take('a', 10 * 60 * 1000 + 1).ok, true);
});

test('shouldAutoHide: rejections >= 3 and > confirmations', () => {
  assert.equal(R.shouldAutoHide({ confirmations: 0, rejections: 2 }), false);
  assert.equal(R.shouldAutoHide({ confirmations: 0, rejections: 3 }), true);
  assert.equal(R.shouldAutoHide({ confirmations: 3, rejections: 3 }), false);
  assert.equal(R.shouldAutoHide({ confirmations: 3, rejections: 4 }), true);
});

test('POST /v1/reports: validation, client header, hashing, TTL, unverified label', async () => {
  const { repo, deps: d } = deps();
  await withServer(d, async (base) => {
    assert.equal((await call(base, '/v1/reports', { method: 'POST', body: report() })).status, 400); // no client id
    const bad = await call(base, '/v1/reports', { method: 'POST', body: report({ type: 'x' }), headers: asClient() });
    assert.equal(bad.status, 400);
    assert.ok(bad.body.details.length);
    const r = await call(base, '/v1/reports', { method: 'POST', body: report(), headers: asClient() });
    assert.equal(r.status, 201);
    assert.ok(r.body.id);
    assert.equal(r.body.report.verified, false);
    assert.equal(r.body.report.label, 'unverified driver report');
    assert.equal(r.body.report.expiresAt, '2026-11-15T22:00:00.000Z');
    assert.equal('reporter_hash' in r.body.report, false);
    const row = repo.rows.get(r.body.id);
    assert.equal(row.reporter_hash, R.hashClient(CID, SALT));
  });
});

test('POST /v1/reports: rate limit 429 after 5 reports', async () => {
  const { deps: d } = deps();
  await withServer(d, async (base) => {
    for (let i = 0; i < 5; i++) assert.equal((await call(base, '/v1/reports', { method: 'POST', body: report(), headers: asClient() })).status, 201);
    const r = await call(base, '/v1/reports', { method: 'POST', body: report(), headers: asClient() });
    assert.equal(r.status, 429);
    assert.equal((await call(base, '/v1/reports', { method: 'POST', body: report(), headers: asClient(CID2) })).status, 201);
  });
});

test('GET /v1/reports: bbox required, expired and hidden excluded', async () => {
  const { repo, setNow, deps: d } = deps();
  await withServer(d, async (base) => {
    assert.equal((await call(base, '/v1/reports')).status, 400);
    await call(base, '/v1/reports', { method: 'POST', body: report({ type: 'traffic' }), headers: asClient() });
    const h = await call(base, '/v1/reports', { method: 'POST', body: report(), headers: asClient() });
    let r = await call(base, '/v1/reports?bbox=34.7,32.0,34.9,32.2');
    assert.equal(r.body.reports.length, 2);
    assert.deepEqual(repo.calls.at(-1)[1], { minLon: 34.7, minLat: 32.0, maxLon: 34.9, maxLat: 32.2 });
    setNow(new Date(T0.getTime() + 2 * 3600e3)); // traffic (1h) expired, hazard (12h) live
    r = await call(base, '/v1/reports?bbox=34.7,32.0,34.9,32.2');
    assert.deepEqual(r.body.reports.map((x) => x.type), ['hazard']);
    assert.equal(r.body.reports[0].ageMinutes, 120);
    repo.rows.get(h.body.id).status = 'hidden';
    r = await call(base, '/v1/reports?bbox=34.7,32.0,34.9,32.2');
    assert.equal(r.body.reports.length, 0);
  });
});

test('vote: one per reporter, auto-hide at 3 rejections > confirmations, audited', async () => {
  const { repo, deps: d } = deps();
  await withServer(d, async (base) => {
    const { body: { id } } = await call(base, '/v1/reports', { method: 'POST', body: report(), headers: asClient() });
    const vote = (cid, v) => call(base, `/v1/reports/${id}/vote`, { method: 'POST', body: { vote: v }, headers: asClient(cid) });
    assert.equal((await vote('voter-000000000000001', 'maybe')).status, 400);
    assert.equal((await vote('voter-000000000000001', 'confirm')).status, 200);
    assert.equal((await vote('voter-000000000000001', 'reject')).status, 409);
    assert.equal((await vote('voter-000000000000002', 'reject')).body.status, 'visible');
    assert.equal((await vote('voter-000000000000003', 'reject')).body.status, 'visible');
    const last = await vote('voter-000000000000004', 'reject');
    assert.equal(last.status, 200);
    assert.equal(last.body.status, 'hidden');
    assert.deepEqual(repo.audit.map((a) => [a.action, a.actor]), [['auto_hide', 'system']]);
    assert.equal((await vote('voter-000000000000005', 'confirm')).status, 404); // hidden: no more votes
    assert.equal((await call(base, '/v1/reports/not-a-uuid/vote', { method: 'POST', body: { vote: 'confirm' }, headers: asClient() })).status, 404);
  });
});

test('moderate: 403 without configured token or wrong token; hide/show audited', async () => {
  const noTok = deps();
  await withServer(noTok.deps, async (base) => {
    const { body: { id } } = await call(base, '/v1/reports', { method: 'POST', body: report(), headers: asClient() });
    const r = await call(base, `/v1/reports/${id}/moderate`, { method: 'POST', body: { action: 'hide' }, headers: { [R.MODERATOR_HEADER]: '' } });
    assert.equal(r.status, 403);
  });
  const { repo, deps: d } = deps({ moderatorToken: 's3cret' });
  await withServer(d, async (base) => {
    const { body: { id } } = await call(base, '/v1/reports', { method: 'POST', body: report(), headers: asClient() });
    const mod = (tok, body) => call(base, `/v1/reports/${id}/moderate`, { method: 'POST', body, headers: { [R.MODERATOR_HEADER]: tok } });
    assert.equal((await mod('wrong', { action: 'hide' })).status, 403);
    assert.equal((await mod('s3cret', { action: 'delete' })).status, 400);
    assert.deepEqual((await mod('s3cret', { action: 'hide', reason: 'spam' })).body, { id, status: 'hidden' });
    assert.deepEqual((await mod('s3cret', { action: 'show' })).body, { id, status: 'visible' });
    assert.deepEqual(repo.audit.map((a) => [a.action, a.actor, a.reason]), [['hide', 'moderator', 'spam'], ['show', 'moderator', null]]);
  });
});

test('PG repo: bbox and near-route SQL + params; only visible and not expired', async () => {
  const seen = [];
  const db = { query: async (sql, p) => { seen.push({ sql, p }); return { rows: [] }; } };
  const repo = R.createReportsRepo(db);
  await repo.listBbox({ minLon: 34.7, minLat: 32, maxLon: 34.9, maxLat: 32.2 }, T0);
  assert.deepEqual(seen[0].p, [34.7, 32, 34.9, 32.2, T0]);
  assert.match(seen[0].sql, /status = 'visible' AND expires_at > \$5/);
  assert.match(seen[0].sql, /ST_MakeEnvelope\(\$1, \$2, \$3, \$4, 4326\)/);
  assert.doesNotMatch(seen[0].sql, /restrictions/);
  await repo.nearRoute([[34.78, 32.08], [34.8, 32.1]], T0);
  assert.deepEqual(seen[1].p, ['{"type":"LineString","coordinates":[[34.78,32.08],[34.8,32.1]]}', T0, 100]);
  assert.match(seen[1].sql, /ST_DWithin\(geometry::geography/);
  await repo.insert({ type: 'camera', position: [34.78, 32.08], note: null, createdAt: T0, expiresAt: R.expiresAt('camera', T0), reporterHash: 'h'.repeat(64) });
  assert.deepEqual(seen[2].p.slice(0, 4), ['camera', 34.78, 32.08, null]);
  assert.doesNotMatch(R.SQL.bbox + R.SQL.nearRoute, /reporter_hash/);
});

test('route: trucksil.reports lists reports near the final route; failure does not block route', async () => {
  const shape = [[34.78, 32.08], [35.21, 31.77]];
  const trip = { status: 0, legs: [{ shape: encodePolyline(shape) }], summary: { length: 60, time: 3600 } };
  const fetch = async () => ({ ok: true, status: 200, json: async () => ({ trip }) });
  const { repo, deps: d } = deps();
  // Real restrictions repo over a db mock with no rows.
  const db = { query: async () => ({ rows: [] }) };
  const truck = { profileName: 'Test rigid', heightM: 3.8, widthM: 2.5, lengthM: 10, grossWeightT: 18 };
  await withServer({ ...d, db, valhallaUrl: 'http://valhalla:8002', fetch }, async (base) => {
    await call(base, '/v1/reports', { method: 'POST', body: report({ type: 'accident' }), headers: asClient() });
    const r = await call(base, '/v1/route', { method: 'POST', body: { from: shape[0], to: shape[1], vehicle: truck } });
    assert.equal(r.status, 200, JSON.stringify(r.body));
    assert.equal(r.body.trucksil.reports.length, 1);
    assert.deepEqual(Object.keys(r.body.trucksil.reports[0]).sort(), ['ageMinutes', 'confirmations', 'id', 'label', 'position', 'type', 'verified']);
    assert.equal(r.body.trucksil.reports[0].verified, false);
    const near = repo.calls.find((c) => c[0] === 'near');
    assert.deepEqual(near[1], shape);
    assert.equal(near[3], 100);
  });
  const broken = { ...fakeRepo(), nearRoute: async () => { throw new Error('boom'); } };
  const origErr = console.error; console.error = () => {};
  try {
    await withServer({ db, valhallaUrl: 'http://valhalla:8002', fetch, reportsRepo: broken, reports: { salt: SALT } }, async (base) => {
      const r = await call(base, '/v1/route', { method: 'POST', body: { from: shape[0], to: shape[1], vehicle: truck } });
      assert.equal(r.status, 200);
      assert.equal(r.body.trucksil.reports, null);
    });
  } finally { console.error = origErr; }
});
