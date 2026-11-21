#!/usr/bin/env node
'use strict';
// Validates restriction records (JSON Lines on stdin, one record per line) against
// data/restrictions.schema.json with the same Ajv setup as test/schemas.test.js.
// Used by scripts/import_osm_maxheight.py before any SQL is produced, so importers in Python need
// no jsonschema package. Prints a JSON summary on stdout; exit code 1 if any record is invalid.
//   python3 scripts/import_osm_maxheight.py <pbf> --jsonl | node scripts/validate_restrictions.js
const fs = require('node:fs');
const path = require('node:path');
const Ajv2020 = require('ajv/dist/2020');
const addFormats = require('ajv-formats');

function createValidator() {
  const ajv = new Ajv2020({ allErrors: true, strict: true, strictTuples: false, allowUnionTypes: true });
  addFormats(ajv);
  const schema = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', 'restrictions.schema.json'), 'utf8'));
  return ajv.compile(schema);
}

/** @returns {{valid:number, invalid:Array<{line:number, id:string|null, errors:object[]}>}} */
function validateLines(text, validate = createValidator()) {
  const out = { valid: 0, invalid: [] };
  text.split('\n').forEach((raw, i) => {
    const line = raw.trim();
    if (!line) return;
    let rec;
    try {
      rec = JSON.parse(line);
    } catch (e) {
      out.invalid.push({ line: i + 1, id: null, errors: [{ message: `bad JSON: ${e.message}` }] });
      return;
    }
    if (validate(rec)) out.valid += 1;
    else out.invalid.push({ line: i + 1, id: rec && rec.id ? String(rec.id) : null, errors: validate.errors });
  });
  return out;
}

if (require.main === module) {
  const res = validateLines(fs.readFileSync(0, 'utf8'));
  process.stdout.write(`${JSON.stringify({ valid: res.valid, invalid: res.invalid.length, firstInvalid: res.invalid.slice(0, 5) })}\n`);
  process.exit(res.invalid.length ? 1 : 0);
}

module.exports = { createValidator, validateLines };
