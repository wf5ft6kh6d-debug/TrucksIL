'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { buildValhallaRouteRequest, NARRATIVE_LANGUAGES } = require('../../api/src/lib.js');

const truck = { profileName: 't', heightM: 4, widthM: 2.5, lengthM: 12, grossWeightT: 18 };
const req = (language) => buildValhallaRouteRequest({ from: [34.78, 32.08], to: [35.21, 31.77], vehicle: truck, language });

test('narrative language: whitelisted UI languages pass through to Valhalla', () => {
  assert.deepEqual(NARRATIVE_LANGUAGES, ['en-US', 'he-IL', 'ru-RU', 'ar-SA']);
  for (const l of NARRATIVE_LANGUAGES) assert.equal(req(l).language, l);
});

test('narrative language: missing or unknown -> en-US; costing unaffected', () => {
  for (const l of [undefined, null, '', 'fr-FR', 'he', 42, '../x']) assert.equal(req(l).language, 'en-US');
  assert.deepEqual(req('he-IL').costing_options, req(undefined).costing_options);
});
