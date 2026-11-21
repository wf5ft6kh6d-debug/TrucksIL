'use strict';
// e2e evaluation relative to the baseline (ADR-0016). FICTIONAL ids only.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { evaluateRelative } = require('../scenarios/lib');

const ok = (reroutes, avoided = [], onRoute = []) => ({
  status: 200,
  body: { trucksil: { disclaimer: 'prototype, not for navigation', reroutes, avoided: avoided.map((id) => ({ id })), onRoute: onRoute.map((id) => ({ id })) } },
});
const avoidS = { restrictions: [{ id: 'e2e-x' }], expected: { status: 200, avoidedIds: ['x'], onRouteIds: [], minReroutes: 1, maxReroutes: 3 } };
const plainS = { restrictions: [{ id: 'e2e-y' }], expected: { status: 200, avoidedIds: [], onRouteIds: ['y'], minReroutes: 0, maxReroutes: 0 } };

test('baseline blocked by real data -> SKIP with reason (FAIL in strict mode)', () => {
  const base = { status: 422, body: { error: 'no route found' } };
  const r = evaluateRelative(avoidS, base, null);
  assert.equal(r.result, 'SKIP');
  assert.match(r.notes[0], /baseline blocked by non-test data: baseline HTTP 422 \(no route found\)/);
  assert.equal(evaluateRelative(avoidS, base, null, { strict: true }).result, 'FAIL');
});

test('avoidance scenario: reroutes >= max(minReroutes, baseline); more than maxReroutes is fine', () => {
  const base = ok(2, ['osm-a', 'osm-b']);
  assert.equal(evaluateRelative(avoidS, base, ok(4, ['e2e-x', 'osm-a'])).result, 'PASS');
  const low = evaluateRelative(avoidS, base, ok(1, ['e2e-x']));
  assert.equal(low.result, 'FAIL');
  assert.match(low.fails[0], /reroutes 1 < 2 \(baseline 2\)/);
  assert.equal(evaluateRelative(avoidS, base, ok(4, ['e2e-x']), { strict: true }).result, 'FAIL', 'strict keeps maxReroutes');
  assert.equal(evaluateRelative(avoidS, ok(0), ok(1, [])).result, 'FAIL', 'seeded id must be avoided');
});

test('no-avoid scenario: baseline reroutes tolerated, seeded id must stay out of avoided', () => {
  const base = ok(3, ['osm-a']);
  const r = evaluateRelative(plainS, base, ok(3, ['osm-a'], ['e2e-y']));
  assert.equal(r.result, 'PASS');
  assert.match(r.notes[0], /baseline: reroutes 3, 1 non-test/);
  assert.equal(evaluateRelative(plainS, base, ok(4, ['e2e-y'])).result, 'FAIL');
  assert.equal(evaluateRelative(plainS, base, { status: 409, body: { error: 'x' } }).result, 'FAIL');
  assert.equal(evaluateRelative(plainS, base, ok(3, ['osm-a'], ['e2e-y']), { strict: true }).result, 'FAIL', 'strict: reroutes must be 0');
});
