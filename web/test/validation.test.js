import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createVehicleValidator, profileFromForm, parseLonLat } from '../src/validation.js';

// The same schema file the API validates against.
const schema = JSON.parse(fs.readFileSync(new URL('../../data/vehicle-profile.schema.json', import.meta.url), 'utf8'));
const validate = createVehicleValidator(schema);
const form = { profileName: ' Test truck (fictional) ', heightM: '4', widthM: '2,55', lengthM: '12', grossWeightT: '18', axleLoadT: '', note: '', adrClasses: [] };

test('validation: form -> profile (trim, comma decimals, empty optionals omitted)', () => {
  assert.deepEqual(profileFromForm(form), { profileName: 'Test truck (fictional)', heightM: 4, widthM: 2.55, lengthM: 12, grossWeightT: 18 });
  assert.deepEqual(profileFromForm({ ...form, adrClasses: ['3', '8'], axleLoadT: '10' }).hazmat, { adrClasses: ['3', '8'] });
});

test('validation: valid profile passes the shared schema', () => {
  assert.deepEqual(validate(profileFromForm(form)), { ok: true, errors: [] });
  assert.equal(validate(JSON.parse(fs.readFileSync(new URL('../../src/truck-profile.example.json', import.meta.url), 'utf8'))).ok, true);
});

test('validation: missing required, out of range and non-numeric are reported', () => {
  const r1 = validate(profileFromForm({ ...form, heightM: '' }));
  assert.equal(r1.ok, false);
  assert.ok(r1.errors.some((e) => e.field === 'heightM'));
  const r2 = validate(profileFromForm({ ...form, heightM: '7' }));
  assert.ok(r2.errors.some((e) => e.field === 'heightM' && /<= 6/.test(e.message)));
  const r3 = validate(profileFromForm({ ...form, grossWeightT: 'abc' }));
  assert.ok(r3.errors.some((e) => e.field === 'grossWeightT' && /number/.test(e.message)));
  assert.equal(validate({ ...profileFromForm(form), extra: 1 }).ok, false);
  assert.equal(validate({ ...profileFromForm(form), hazmat: { adrClasses: ['10'] } }).ok, false);
});

test('validation: parseLonLat', () => {
  assert.deepEqual(parseLonLat('34.78, 32.08'), [34.78, 32.08]);
  for (const bad of ['', '34.78', '34.78,', 'a,b', '200,10', '10,95', '1,2,3', null]) assert.equal(parseLonLat(bad), null, String(bad));
});
