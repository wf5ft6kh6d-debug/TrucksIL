import test from 'node:test';
import assert from 'node:assert/strict';
import {
  getClientId, CLIENT_KEY, CLIENT_HEADER, reportItem, reportItems, reportsGeoJSON, validateDraft, submitMessage, postReport, voteReport, fetchReports,
} from '../src/reports.js';
import { routeViewModel } from '../src/viewModel.js';
import { encodePolyline } from '../../api/src/polyline.mjs';
import { LANGS, t } from '../src/i18n.js';

const mem = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), m }; };

test('client id: generated once, persisted, reused; broken storage still yields an id', () => {
  const s = mem();
  const id = getClientId(s, (n) => new Uint8Array(n).fill(171));
  assert.equal(id, 'ab'.repeat(16));
  assert.equal(s.m.get(CLIENT_KEY), id);
  assert.equal(getClientId(s, () => { throw new Error('must not regenerate'); }), id);
  const broken = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } };
  assert.match(getClientId(broken), /^[0-9a-f]{32}$/);
});

test('reportItem: always carries the unverified label; unknown type -> other', () => {
  const it = reportItem({ id: 'x', type: 'hazard', position: [34.78, 32.08], ageMinutes: 5, confirmations: 2, note: '' });
  assert.deepEqual(it, { id: 'x', type: 'hazard', typeKey: 'rtype.hazard', labelKey: 'reports.unverified', position: [34.78, 32.08], note: null, ageMinutes: 5, confirmations: 2 });
  assert.equal(reportItem({ id: 1, type: 'ufo' }).typeKey, 'rtype.other');
  assert.equal(reportItem({ id: 1, type: 'camera', position: [1] }).position, null);
  assert.deepEqual(reportItems(null), []);
});

test('reportsGeoJSON: only positioned items, flagged unverified', () => {
  const g = reportsGeoJSON(reportItems([{ id: 'a', type: 'camera', position: [34.8, 32.1] }, { id: 'b', type: 'other' }]));
  assert.equal(g.features.length, 1);
  assert.deepEqual(g.features[0].properties, { id: 'a', type: 'camera', unverified: true });
});

test('unverified label exists in all 4 languages with the required wording', () => {
  for (const l of LANGS) assert.ok(t(l, 'reports.unverified') !== 'reports.unverified');
  assert.equal(t('he', 'reports.unverified'), 'דיווח נהג, לא מאומת');
  assert.equal(t('en', 'reports.unverified'), 'driver report, unverified');
});

test('validateDraft and submitMessage', () => {
  assert.equal(validateDraft({ type: 'hazard', position: [34.8, 32.1], note: '' }), null);
  assert.equal(validateDraft({ type: 'x', position: [34.8, 32.1] }), 'reports.type');
  assert.equal(validateDraft({ type: 'hazard', position: null }), 'reports.pickHint');
  assert.equal(validateDraft({ type: 'hazard', position: [34.8, 32.1], note: 'x'.repeat(281) }), 'reports.note');
  assert.equal(submitMessage('create', 201).key, 'reports.sent');
  assert.equal(submitMessage('create', 429).key, 'reports.rateLimited');
  assert.equal(submitMessage('create', null).key, 'reports.failed');
  assert.equal(submitMessage('vote', 409).key, 'reports.alreadyVoted');
  assert.equal(submitMessage('vote', 200).key, 'reports.voted');
});

test('route view model includes nearby reports; non-200 has none', () => {
  const body = { trip: { legs: [{ shape: encodePolyline([[34.78, 32.08], [34.8, 32.1]]) }] }, trucksil: { reports: [{ id: 'r1', type: 'accident', position: [34.79, 32.09], ageMinutes: 3, confirmations: 0, verified: false }] } };
  const vm = routeViewModel(200, body);
  assert.deepEqual(vm.reports.map((r) => [r.id, r.labelKey]), [['r1', 'reports.unverified']]);
  assert.deepEqual(routeViewModel(200, { ...body, trucksil: { reports: null } }).reports, []);
  assert.deepEqual(routeViewModel(503, {}).reports, []);
});

test('api calls send the anonymous client header and correct paths', async () => {
  const calls = [];
  const f = async (url, init) => { calls.push({ url, init }); return { status: 201, json: async () => ({ id: 'z' }) }; };
  assert.deepEqual(await postReport({ type: 'hazard', position: [34.8, 32.1], note: '' }, 'cid-0000000000000000', f), { status: 201, body: { id: 'z' } });
  assert.equal(calls[0].url, '/api/v1/reports');
  assert.equal(calls[0].init.headers[CLIENT_HEADER], 'cid-0000000000000000');
  assert.deepEqual(JSON.parse(calls[0].init.body), { type: 'hazard', position: [34.8, 32.1] });
  await voteReport('abc', 'reject', 'cid-0000000000000000', f);
  assert.equal(calls[1].url, '/api/v1/reports/abc/vote');
  await fetchReports([34.7, 32, 34.9, 32.2], f);
  assert.equal(calls[2].url, '/api/v1/reports?bbox=34.70000,32.00000,34.90000,32.20000');
  assert.deepEqual(await postReport({ type: 'hazard', position: [1, 2] }, 'c', async () => { throw new Error('x'); }), { status: null, body: null });
});
