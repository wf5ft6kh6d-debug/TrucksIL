'use strict';
// Reference route scenarios (test/scenarios/routes.json) through the real HTTP handler, with a mock
// Valhalla and an in-memory restrictions repo. No Docker. All restrictions are fictional.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createServer } = require('../../api/src/app');
const S = require('../scenarios/lib');

const scenarios = S.loadScenarios();

async function postRoute(deps, body) {
  const server = createServer(deps);
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    const r = await fetch(`http://127.0.0.1:${server.address().port}/v1/route`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
    });
    return { status: r.status, body: await r.json() };
  } finally { await new Promise((r) => server.close(r)); }
}

test('scenario file: required cases present, fictional ids, valid expectations', () => {
  const ids = scenarios.map((s) => s.id);
  for (const id of ['S01', 'S02', 'S03', 'S04', 'S05', 'S06a', 'S06b', 'S07', 'S08', 'S09', 'S10']) assert.ok(ids.includes(id), id);
  for (const s of scenarios) {
    assert.ok([200, 409, 422].includes(s.expected.status), s.id);
    for (const r of s.restrictions) assert.ok(r.id.startsWith(S.SEED_PREFIX), r.id);
  }
});

test('helpers: pointAtFraction / distanceToShapeM', () => {
  const shape = [[34.0, 31.0], [34.0, 31.1], [34.1, 31.1]];
  const mid = S.pointAtFraction(shape, 0.5);
  assert.ok(S.distanceToShapeM(mid, shape) < 1);
  const total = S.haversineM(shape[0], shape[1]) + S.haversineM(shape[1], shape[2]);
  assert.ok(Math.abs(S.haversineM(shape[0], mid) - total / 2) < 5, 'midpoint by length lies on the first leg');
  assert.deepEqual(S.pointAtFraction(shape, 0), shape[0]);
  assert.ok(S.distanceToShapeM([34.05, 31.05], shape) > 4000);
});

for (const s of scenarios) {
  test(`scenario ${s.id}: ${s.description}`, async () => {
    const opts = s.mock || {};
    const baseline = S.routeShape(S.mockValhallaRoute({ locations: [{ lon: s.from[0], lat: s.from[1] }, { lon: s.to[0], lat: s.to[1] }] }).json);
    const rows = s.restrictions.map((r) => S.toRow(r, S.resolveWhere(r.where, baseline)));
    for (const r of rows) assert.ok(S.distanceToShapeM(r.point, baseline) <= 50, `${r.id} seeded on the baseline`);
    const deps = { db: null, repo: S.createMemoryRepo(rows), valhallaUrl: 'http://valhalla.mock:8002', fetch: S.mockValhallaFetch(opts) };
    const { status, body } = await postRoute(deps, { from: s.from, to: s.to, vehicle: s.vehicle });
    assert.deepEqual(S.checkExpectations(s, status, body), [], JSON.stringify(body.trucksil || body));
  });
}
