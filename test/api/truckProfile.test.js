'use strict';
// ADR-0013: full truck profile -> Valhalla costing_options, and ADR tunnel-category conflicts.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { loadVehicleValidator, vehicleToTruckCosting, buildValhallaRouteRequest, HGV_NO_ACCESS_PENALTY_S } = require('../../api/src/lib');
const { TUNNEL_CATEGORIES, vehicleTunnelCode, tunnelConflict, violation, classify } = require('../../api/src/routing');

const validate = loadVehicleValidator();
const full = {
  profileName: 'FICTIONAL full profile', heightM: 4.1, widthM: 2.55, lengthM: 18.75, grossWeightT: 44,
  axleLoadT: 11.5, axleCount: 6, hazmat: { adrClasses: ['3', '8'], adrTunnelCode: 'C/E' }, note: 'x',
};

test('full profile is schema-valid', () => assert.ok(validate(full), JSON.stringify(validate.errors)));

test('every Valhalla-relevant profile field is mapped to costing_options.truck', () => {
  assert.deepEqual(vehicleToTruckCosting(full), {
    height: 4.1, width: 2.55, length: 18.75, weight: 44, axle_load: 11.5, axle_count: 6, hazmat: true,
    hgv_no_access_penalty: 43200,
  });
  const r = buildValhallaRouteRequest({ from: [34.7, 32], to: [35.2, 31.7], vehicle: full });
  assert.equal(r.costing_options.truck.axle_count, 6);
});

test('schema-known profile fields are all either mapped or deliberately not sent', () => {
  const schema = JSON.parse(fs.readFileSync(path.join(__dirname, '../../data/vehicle-profile.schema.json'), 'utf8'));
  const handled = ['profileName', 'note', 'heightM', 'widthM', 'lengthM', 'grossWeightT', 'axleLoadT', 'axleCount', 'hazmat'];
  assert.deepEqual(Object.keys(schema.properties).sort(), handled.sort());
});

test('default hgv_no_access_penalty is 43200 (no-HGV-access roads forbidden) even for a minimal profile', () => {
  assert.equal(HGV_NO_ACCESS_PENALTY_S, 43200);
  const c = vehicleToTruckCosting({ profileName: 'm', heightM: 3, widthM: 2.4, lengthM: 8, grossWeightT: 12 });
  assert.equal(c.hgv_no_access_penalty, 43200);
  for (const k of ['axle_load', 'axle_count', 'hazmat']) assert.equal(k in c, false, k);
});

test('backward compatible: old profiles without axleCount/adrTunnelCode stay valid', () => {
  assert.ok(validate({ profileName: 'old', heightM: 4, widthM: 2.5, lengthM: 12, grossWeightT: 26, hazmat: { adrClasses: ['3'] } }));
  assert.equal(validate({ ...full, axleCount: 1 }), false);
  assert.equal(validate({ ...full, hazmat: { adrClasses: ['3'], adrTunnelCode: 'A' } }), false);
  assert.equal(validate({ ...full, trailer: true }), false);
});

test('vehicleTunnelCode: first letter of the ADR code, B when unknown, null without hazmat or with "-"', () => {
  const v = (code) => ({ hazmat: { adrClasses: ['3'], ...(code === undefined ? {} : { adrTunnelCode: code }) } });
  const want = { B: 'B', B1000C: 'B', 'B/D': 'B', 'B/E': 'B', C: 'C', C5000D: 'C', 'C/D': 'C', 'C/E': 'C', D: 'D', 'D/E': 'D', E: 'E' };
  for (const [code, letter] of Object.entries(want)) assert.equal(vehicleTunnelCode(v(code)), letter, code);
  assert.equal(vehicleTunnelCode(v(undefined)), 'B');
  assert.equal(vehicleTunnelCode(v('zzz')), 'B');
  assert.equal(vehicleTunnelCode(v('-')), null);
  assert.equal(vehicleTunnelCode({}), null);
});

test('tunnelConflict for every vehicle code x tunnel category', () => {
  for (const code of TUNNEL_CATEGORIES) {
    for (const cat of TUNNEL_CATEGORIES) {
      const forbidden = TUNNEL_CATEGORIES.indexOf(cat) >= TUNNEL_CATEGORIES.indexOf(code);
      assert.equal(tunnelConflict(cat, code) !== null, forbidden, `code ${code} / tunnel ${cat}`);
    }
    assert.equal(tunnelConflict('B', null), null);
    assert.notEqual(tunnelConflict(undefined, code), null, 'unknown category treated as E');
  }
});

const tunnelRow = (cat, extra = {}) => ({
  id: `t-${cat}`, restriction_type: 'adr_tunnel', value_text: cat, value_numeric: null, value_boolean: null,
  unit: 'adr_tunnel_category', status: 'unverified', ...extra,
});

test('violation(): adr_tunnel rows', () => {
  const tanker = (code) => ({ ...full, hazmat: { adrClasses: ['3'], adrTunnelCode: code } });
  assert.match(violation(tunnelRow('D'), tanker('D/E')), /category D/);
  assert.equal(violation(tunnelRow('C'), tanker('D/E')), null);
  assert.match(violation(tunnelRow('B'), { ...full, hazmat: { adrClasses: ['2'] } }), /code B/);
  const { hazmat, ...empty } = full;
  assert.equal(violation(tunnelRow('E'), empty), null, 'no dangerous goods -> tunnel category irrelevant');
});

test('classify(): tunnel value is the category string in the public output', () => {
  const { conflicts, onRoute } = classify([tunnelRow('E'), tunnelRow('B', { id: 't-B2' })], { ...full, hazmat: { adrClasses: ['3'], adrTunnelCode: 'E' } });
  assert.deepEqual(conflicts.map((c) => [c.id, c.value]), [['t-E', 'E']]);
  assert.deepEqual(onRoute.map((c) => [c.id, c.value, c.unit]), [['t-B2', 'B', 'adr_tunnel_category']]);
});

test('migration 003 is idempotent-looking and extends the CHECKs', () => {
  const sql = fs.readFileSync(path.join(__dirname, '../../db/migrations/003_adr_tunnels.sql'), 'utf8');
  assert.match(sql, /ADD COLUMN IF NOT EXISTS value_text/);
  assert.match(sql, /adr_tunnel_category/);
  assert.match(sql, /DROP CONSTRAINT IF EXISTS/);
});

test('data/examples/tunnels fixtures are valid restrictions and marked FICTIONAL', () => {
  const Ajv2020 = require('ajv/dist/2020');
  const addFormats = require('ajv-formats');
  const ajv = new Ajv2020({ allErrors: true, strict: true, strictTuples: false, allowUnionTypes: true });
  addFormats(ajv);
  const dir = path.join(__dirname, '../../data/examples/tunnels');
  const check = ajv.compile(JSON.parse(fs.readFileSync(path.join(__dirname, '../../data/restrictions.schema.json'), 'utf8')));
  const files = fs.readdirSync(dir).filter((f) => f.endsWith('.json'));
  assert.ok(files.length > 0);
  for (const f of files) {
    const r = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
    assert.ok(check(r), `${f}: ${JSON.stringify(check.errors)}`);
    assert.equal(r.restrictionType, 'adr_tunnel');
    assert.match(r.id + r.source.name, /FICTIONAL/);
  }
});
