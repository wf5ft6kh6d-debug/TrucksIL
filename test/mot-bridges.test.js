'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const Ajv2020 = require('ajv/dist/2020');
const addFormats = require('ajv-formats');
const { importBridges, parseHeight, parseDUpdate, SOURCE_NAME } = require('../src/importers/mot-bridges');
const { itmToWgs84 } = require('../src/importers/itm');

const root = path.join(__dirname, '..');
const dir = path.join(root, 'data/examples/mot-bridges');
const load = (f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: true, strictTuples: false, allowUnionTypes: true });
addFormats(ajv);
const validate = ajv.compile(JSON.parse(fs.readFileSync(path.join(root, 'data/restrictions.schema.json'), 'utf8')));
const NOW = '2026-11-14T00:00:00.000Z';

const itm = importBridges(load('bridges-itm.fictional.geojson'), { now: NOW });
const wgs = importBridges(load('bridges-wgs84.fictional.geojson'), { now: NOW });
const byRoad = (res, id) => res.records.find((r) => r.roadSegmentId === `mot-bridge:${id}`);
const skipOf = (res, oid) => res.skipped.find((s) => s.OBJECTID === oid);

test('every output record validates against restrictions schema', () => {
  for (const r of [...itm.records, ...wgs.records]) assert.ok(validate(r), JSON.stringify(validate.errors));
  assert.equal(itm.stats.invalid + wgs.stats.invalid, 0);
});

test('ITM fixture: only valid road-bridges produce records', () => {
  assert.deepEqual(itm.records.map((r) => r.roadSegmentId).sort(), ['mot-bridge:9005', 'mot-bridge:FX-001']);
  assert.equal(itm.stats.records, 2);
  assert.equal(itm.stats.skipped, 8);
});

test('record shape: posted_sign, unverified, m, Gavrit_min, source, observedAt', () => {
  const r = byRoad(itm, 'FX-001');
  assert.equal(r.restrictionType, 'max_height');
  assert.equal(r.value, 4.6);
  assert.equal(r.unit, 'm');
  assert.equal(r.valueSource, 'posted_sign');
  assert.equal(r.status, 'unverified');
  assert.deepEqual(r.source, { name: SOURCE_NAME, reference: 'OBJECTID:9001', license: 'UNCONFIRMED' });
  assert.equal(r.observedAt, '2024-05-01T00:00:00.000Z');
  assert.equal(r.geometry.type, 'Point');
  assert.ok(!('Gavrit_max' in r) && !('note' in r));
});

test('ITM coordinates are converted to WGS84', () => {
  const [lon, lat] = byRoad(itm, 'FX-001').geometry.coordinates;
  assert.ok(Math.abs(lon - 34.7653) < 0.001 && Math.abs(lat - 32.0775) < 0.001, `${lon},${lat}`);
  assert.equal(itm.stats.itmConverted, 2);
  // ITM false origin -> about 31.7348N 35.2052E (Jerusalem)
  const [olon, olat] = itmToWgs84(219529.584, 626907.39);
  assert.ok(Math.abs(olon - 35.2052) < 0.0005 && Math.abs(olat - 31.7348) < 0.0005);
});

test('WGS84 input passes through unchanged', () => {
  assert.deepEqual(byRoad(wgs, 'FX-101').geometry.coordinates, [34.9, 31.9]);
  assert.equal(wgs.stats.itmConverted, 0);
});

test('-1, 9999, blank, non-numeric, 0, >50 -> unknown_height, no record', () => {
  const cases = { 9002: 'sentinel_-1', 9003: 'sentinel_9999', 9006: 'blank', 9007: 'non_numeric', 9008: 'non_positive', 9009: 'out_of_range_gt_50' };
  for (const [oid, detail] of Object.entries(cases)) {
    const s = skipOf(itm, Number(oid));
    assert.ok(s, `missing skip for ${oid}`);
    assert.equal(s.reason, 'unknown_height');
    assert.equal(s.detail, detail);
  }
  assert.equal(itm.stats.unknownHeight, 6);
  assert.equal(parseHeight(null).reason, 'blank');
  assert.equal(parseHeight(' 4.5 ').value, 4.5);
});

test('non-road functions (rail over stream, pedestrian) are skipped', () => {
  assert.equal(skipOf(itm, 9004).reason, 'not_over_road');
  assert.equal(skipOf(itm, 9010).reason, 'not_over_road');
  assert.equal(itm.stats.notOverRoad, 2);
});

test('Min_Gavrit alias, blank ID falls back to OBJECTID, unknown Function allowed', () => {
  const r = byRoad(itm, '9005');
  assert.equal(r.value, 4.25);
  assert.equal(r.observedAt, '2023-11-01T00:00:00.000Z');
  assert.ok(itm.warnings.some((w) => w.includes('Min_Gavrit')));
});

test('missing/invalid D_Update -> import time; unit and license warnings', () => {
  assert.equal(byRoad(wgs, '9102').observedAt, NOW);
  assert.equal(parseDUpdate('202513'), null);
  assert.ok(wgs.warnings.some((w) => /metres assumed/.test(w)));
  assert.ok(wgs.warnings.some((w) => /UNCONFIRMED/.test(w)));
});

test('license is configurable; ids are stable across runs', () => {
  const again = importBridges(load('bridges-itm.fictional.geojson'), { now: '2030-01-01T00:00:00Z', license: 'CC-BY-4.0' });
  assert.deepEqual(again.records.map((r) => r.id), itm.records.map((r) => r.id));
  assert.ok(again.records.every((r) => r.source.license === 'CC-BY-4.0'));
  assert.equal(new Set(itm.records.map((r) => r.id)).size, itm.records.length);
});

test('rejects non-FeatureCollection input', () => {
  assert.throws(() => importBridges({ type: 'Feature' }), TypeError);
});

test('CLI prints {records, skipped, warnings, stats}', () => {
  const out = JSON.parse(execFileSync(process.execPath, [path.join(root, 'src/importers/mot-bridges.js'), path.join(dir, 'bridges-itm.fictional.geojson')], { encoding: 'utf8' }));
  assert.deepEqual(Object.keys(out).sort(), ['records', 'skipped', 'stats', 'warnings']);
  assert.equal(out.records.length, 2);
  for (const r of out.records) assert.ok(validate(r));
});
