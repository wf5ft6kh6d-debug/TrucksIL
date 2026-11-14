'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Ajv2020 = require('ajv/dist/2020');
const addFormats = require('ajv-formats');

const root = path.join(__dirname, '..');
const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: true, strictTuples: false, allowUnionTypes: true });
addFormats(ajv);

const suites = [
  { schema: 'data/restrictions.schema.json', fixtures: 'data/examples/restrictions' },
  { schema: 'data/vehicle-profile.schema.json', fixtures: 'data/examples/vehicle-profiles' },
];

for (const { schema, fixtures } of suites) {
  const validate = ajv.compile(readJson(path.join(root, schema)));
  for (const kind of ['valid', 'invalid']) {
    const dir = path.join(root, fixtures, kind);
    const files = fs.readdirSync(dir).filter((f) => f.endsWith('.json'));
    test(`${fixtures}/${kind} has fixtures`, () => assert.ok(files.length > 0));
    for (const f of files) {
      test(`${schema}: ${kind}/${f}`, () => {
        const ok = validate(readJson(path.join(dir, f)));
        if (kind === 'valid') assert.ok(ok, JSON.stringify(validate.errors, null, 2));
        else assert.equal(ok, false, `expected ${f} to be rejected`);
      });
    }
  }
}

test('src/truck-profile.example.json conforms to vehicle profile schema', () => {
  const validate = ajv.getSchema('https://trucksil.invalid/schemas/vehicle-profile.schema.json');
  assert.ok(validate(readJson(path.join(root, 'src/truck-profile.example.json'))), JSON.stringify(validate.errors));
});
