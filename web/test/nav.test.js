import test from 'node:test';
import assert from 'node:assert/strict';
import { encodePolyline } from '../../api/src/polyline.mjs';
import { distanceM, cumulative, snapToRoute, pointAt } from '../src/nav/geo.js';
import { buildNavRoute, progressAt } from '../src/nav/progress.js';
import { createOffRouteDetector, createRateLimiter } from '../src/nav/offRoute.js';
import { createAnnouncer, thresholds, distanceParams, warningText } from '../src/nav/announce.js';
import { createSpeechQueue, pickVoice, SPEECH_LANG } from '../src/nav/speech.js';
import { simulateFixes } from '../src/nav/simulate.js';
import { createNavSession } from '../src/nav/session.js';
import { saveLastRoute, loadLastRoute, staleViewModel, clearLastRoute } from '../src/nav/offline.js';
import { tilesAlongRoute, lonLatToTile } from '../src/nav/tiles.js';
import { routeViewModel } from '../src/viewModel.js';
import { t } from '../src/i18n.js';

// Fictional L-shaped route: east along lat 32.0, then north. Corner at index 3.
const SHAPE = [[34.80, 32.0], [34.81, 32.0], [34.82, 32.0], [34.83, 32.0], [34.83, 32.01], [34.83, 32.02]];
const body = (extra = {}) => ({
  trip: {
    summary: { length: 5, time: 400 },
    legs: [{
      shape: encodePolyline(SHAPE),
      maneuvers: [
        { type: 2, begin_shape_index: 0, instruction: 'Drive east.', verbal_pre_transition_instruction: 'Drive east on Test Road.', verbal_post_transition_instruction: 'Continue for 3 kilometers.' },
        { type: 15, begin_shape_index: 3, instruction: 'Turn left.', verbal_transition_alert_instruction: 'Turn left onto North Road.', verbal_pre_transition_instruction: 'Turn left onto North Road.', verbal_post_transition_instruction: 'Continue for 2 kilometers.' },
        { type: 4, begin_shape_index: 5, instruction: 'You have arrived.', verbal_pre_transition_instruction: 'You have arrived at your destination.' },
      ],
    }],
  },
  trucksil: { avoided: [], onRoute: [], ...extra },
});
const fakeStorage = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };

test('geo: distance, cumulative, pointAt', () => {
  const d = distanceM([34.80, 32.0], [34.81, 32.0]);
  assert.ok(d > 940 && d < 946, String(d)); // 0.01° lon at 32°N ≈ 943 m
  const cum = cumulative(SHAPE);
  assert.equal(cum[0], 0);
  assert.ok(Math.abs(cum[3] - 3 * d) < 1);
  const mid = pointAt(SHAPE, cum, cum[3] / 2);
  assert.ok(Math.abs(mid[0] - 34.815) < 1e-6 && mid[1] === 32.0);
  assert.deepEqual(pointAt(SHAPE, cum, -5), SHAPE[0]);
  assert.deepEqual(pointAt(SHAPE, cum, 1e9), SHAPE[5]);
});

test('geo: snapToRoute projects onto the nearest segment and reports the offset', () => {
  const cum = cumulative(SHAPE);
  const s = snapToRoute(SHAPE, cum, [34.815, 32.0003]); // ~33 m north of the first leg
  assert.equal(s.segIndex, 1);
  assert.ok(Math.abs(s.distanceM - 33.4) < 1, String(s.distanceM));
  assert.ok(Math.abs(s.alongM - cum[3] / 2) < 2);
  assert.equal(snapToRoute([[1, 1]], [0], [1, 1]), null);
});

test('geo: snapping prefers progress ahead on a route that doubles back', () => {
  const back = [[34.80, 32.0], [34.82, 32.0], [34.82, 32.0002], [34.80, 32.0002]]; // out and back 22 m apart
  const cum = cumulative(back);
  const p = [34.81, 32.0001];
  const fresh = snapToRoute(back, cum, p);
  const later = snapToRoute(back, cum, p, { prevAlongM: cum[2] + 100 });
  assert.ok(later.alongM > cum[2], 'stays on the return leg');
  assert.ok(fresh.distanceM <= later.distanceM + 0.01);
});

test('progress: maneuvers offset per leg; next maneuver and distance', () => {
  const nav = buildNavRoute(body());
  assert.equal(nav.maneuvers.length, 3);
  assert.equal(nav.maneuvers[1].verbalAlert, 'Turn left onto North Road.');
  const p = progressAt(nav, 1000);
  assert.equal(p.nextIndex, 1);
  assert.ok(Math.abs(p.distanceToNextM - (nav.cum[3] - 1000)) < 0.01);
  assert.equal(p.arrived, false);
  assert.equal(progressAt(nav, nav.lengthM).arrived, true);
  assert.equal(progressAt(nav, nav.lengthM).nextIndex, null);
  // Two legs: second leg's begin_shape_index is relative to its own shape.
  const two = { trip: { legs: [
    { shape: encodePolyline(SHAPE.slice(0, 4)), maneuvers: [{ begin_shape_index: 0 }, { begin_shape_index: 3, verbal_pre_transition_instruction: 'Waypoint.' }] },
    { shape: encodePolyline(SHAPE.slice(3)), maneuvers: [{ begin_shape_index: 0, verbal_pre_transition_instruction: 'Go north.' }, { begin_shape_index: 2 }] },
  ] } };
  const n2 = buildNavRoute(two);
  assert.equal(n2.coords.length, 7);
  assert.deepEqual(n2.maneuvers.map((m) => m.shapeIndex), [0, 3, 4, 6]);
  assert.equal(buildNavRoute({ trip: { legs: [] } }), null);
  assert.equal(buildNavRoute({ trip: { legs: [{ shape: 42 }] } }), null);
});

test('progress: TrucksIL warnings placed along the route (avoided nearby, no-data structures)', () => {
  const b = body({
    avoided: [
      { id: 'near', restrictionType: 'max_height', value: 3.8, unit: 'm', status: 'unverified', valueSource: 'posted_sign', geometry: { type: 'Point', coordinates: [34.825, 32.001] } },
      { id: 'far', restrictionType: 'max_height', value: 3.5, unit: 'm', status: 'unverified', valueSource: 'posted_sign', geometry: { type: 'Point', coordinates: [34.9, 32.1] } },
    ],
    coverage: { status: 'computed', structuresOnRoute: 1, structuresWithData: 0, noDataSegments: [{ type: 'tunnel', wayId: 7, coordinates: [[34.83, 32.015], [34.83, 32.017]] }] },
  });
  const nav = buildNavRoute(b, routeViewModel(200, b));
  assert.deepEqual(nav.warnings.map((w) => w.id), ['avoided:near', 'nodata:7']);
  assert.equal(nav.warnings[0].valueText, '3.8 m');
  assert.equal(nav.warnings[1].structure, 'tunnel');
});

test('off-route: >50 m for >10 s fires once; accuracy is taken into account', () => {
  const d = createOffRouteDetector();
  assert.equal(d.update({ distanceM: 10, t: 0 }).state, 'on');
  assert.equal(d.update({ distanceM: 80, accuracyM: 10, t: 1000 }).state, 'suspect');
  assert.equal(d.update({ distanceM: 80, accuracyM: 10, t: 6000 }).state, 'suspect');
  const r = d.update({ distanceM: 90, accuracyM: 10, t: 11000 });
  assert.deepEqual([r.state, r.fired], ['off', true]);
  assert.equal(d.update({ distanceM: 90, t: 12000 }).fired, false, 'fires only once');
  d.reset();
  assert.equal(d.state, 'on');
  // 70 m away with 40 m accuracy is not confidently off: never fires.
  for (let t = 0; t <= 30000; t += 1000) assert.notEqual(d.update({ distanceM: 70, accuracyM: 40, t }).state, 'off');
  // Coming back within 50 m clears the timer.
  d.reset();
  d.update({ distanceM: 80, t: 0 });
  d.update({ distanceM: 20, t: 5000 });
  assert.equal(d.update({ distanceM: 80, t: 11000 }).state, 'suspect');
  // Very poor fixes are ignored.
  assert.equal(d.update({ distanceM: 500, accuracyM: 300, t: 30000 }).ignored, true);
  assert.equal(d.update({ distanceM: Number.NaN, t: 1 }).ignored, true);
});

test('off-route: reroute rate limiter', () => {
  const l = createRateLimiter(30000);
  assert.equal(l.tryAcquire(0), true);
  assert.equal(l.tryAcquire(10000), false);
  assert.equal(l.msUntilNext(10000), 20000);
  assert.equal(l.tryAcquire(30000), true);
});

test('announcements: alert, pre and post once each, timing scales with speed', () => {
  const nav = buildNavRoute(body());
  const a = createAnnouncer();
  const corner = nav.cum[3];
  assert.deepEqual(thresholds(0), { alertM: 400, preM: 60, warnM: 400 });
  assert.equal(thresholds(25).alertM, 1000);
  const at = (along, v = 0) => a.due(nav, progressAt(nav, along), v).map((x) => x.id);
  assert.deepEqual(at(corner - 1500), []);
  assert.deepEqual(at(corner - 1000, 25), ['1:alert']); // 90 km/h -> alert 1 km ahead
  assert.deepEqual(at(corner - 900, 25), []);
  assert.deepEqual(at(corner - 50), ['1:pre']);
  assert.deepEqual(at(corner - 40), []);
  assert.deepEqual(at(corner + 30), ['1:post']);
  assert.deepEqual(at(corner + 60), []);
  // Jumping straight inside the pre threshold skips the alert.
  const b = createAnnouncer();
  assert.deepEqual(b.due(nav, progressAt(nav, corner - 30), 0).map((x) => x.text), ['Turn left onto North Road.']);
});

test('announcements: warnings come first and use UI-language text', () => {
  const nav = { maneuvers: [{ alongM: 0 }, { alongM: 1000, verbalPre: 'Turn.' }], warnings: [{ id: 'nodata:1', kind: 'noData', alongM: 1100, structure: 'bridge' }], lengthM: 2000 };
  const a = createAnnouncer();
  const out = a.due(nav, progressAt(nav, 950), 0);
  assert.deepEqual(out.map((x) => x.id), ['nodata:1', '1:pre']);
  const tr = (k, p) => t('ru', k, p);
  assert.equal(warningText(tr, out[0].warning), 'Через 150 м: мост без данных TrucksIL. Проверьте знаки.');
  const w = { kind: 'avoided', typeKey: 'type.max_height', valueText: '3.8 m', aheadM: 1234 };
  assert.match(warningText((k, p) => t('en', k, p), w), /^Caution: Max height restriction 3\.8 m near the route in 1\.2 km/);
  assert.deepEqual(distanceParams(44), { key: 'unit.m', n: 40 });
  assert.deepEqual(distanceParams(260), { key: 'unit.m', n: 250 });
});

function mockSynth(voices) {
  const spoken = [];
  const synth = { spoken, current: null, getVoices: () => voices, speak(u) { spoken.push(u); this.current = u; }, cancel() { this.cancelled = true; }, finish() { const u = this.current; this.current = null; u.onend(); } };
  function Utterance(text) { this.text = text; }
  return { synth, Utterance };
}

test('speech: voice selection by language (exact, primary, iw alias, local preferred)', () => {
  const v = [{ lang: 'en-US', name: 'en' }, { lang: 'ar-EG', name: 'ar' }, { lang: 'iw_IL', name: 'he-old' }, { lang: 'he-IL', name: 'he', localService: true }, { lang: 'ru-RU', name: 'ru' }];
  assert.equal(pickVoice(v, 'he-IL').name, 'he');
  assert.equal(pickVoice(v, 'ar-SA').name, 'ar');
  assert.equal(pickVoice(v.slice(0, 3), 'he-IL').name, 'he-old');
  assert.equal(pickVoice(v, 'fr-FR'), null);
  assert.deepEqual(SPEECH_LANG, { he: 'he-IL', ru: 'ru-RU', ar: 'ar-SA', en: 'en-US' });
});

test('speech queue: one at a time, high priority first, disabled = silent, no voice = silent', () => {
  const { synth, Utterance } = mockSynth([{ lang: 'ru-RU', name: 'ru' }]);
  const q = createSpeechQueue({ synth, Utterance });
  q.setLang('ru-RU');
  assert.equal(q.say('x'), false, 'disabled by default');
  q.setEnabled(true);
  q.say('one'); q.say('two'); q.say('warn', { priority: 'high' });
  assert.deepEqual(synth.spoken.map((u) => u.text), ['one']);
  assert.equal(synth.spoken[0].lang, 'ru-RU');
  assert.equal(synth.spoken[0].voice.name, 'ru');
  synth.finish();
  assert.deepEqual(synth.spoken.map((u) => u.text), ['one', 'warn']);
  synth.finish(); synth.finish();
  assert.deepEqual(synth.spoken.map((u) => u.text), ['one', 'warn', 'two']);
  assert.equal(q.voiceStatus(), 'ok');
  q.setLang('he-IL');
  assert.equal(q.voiceStatus(), 'noVoice');
  q.say('שלום');
  assert.equal(synth.spoken.length, 3, 'no Hebrew voice -> nothing spoken');
  q.setEnabled(false);
  assert.equal(synth.cancelled, true);
  const none = createSpeechQueue({});
  assert.equal(none.supported, false);
  none.setEnabled(true);
  assert.equal(none.enabled, false);
  assert.equal(none.voiceStatus(), 'unsupported');
});

test('speech queue: bounded, drops oldest normal items', () => {
  const { synth, Utterance } = mockSynth([]); // voices unknown -> speak with lang only
  const q = createSpeechQueue({ synth, Utterance, maxQueue: 2 });
  q.setEnabled(true);
  for (const s of ['a', 'b', 'c', 'd']) q.say(s);
  assert.equal(q.pending, 2);
  assert.equal(q.voiceStatus(), 'unknown');
});

test('simulation: replays the shape at the given speed and ends at the destination', () => {
  const nav = buildNavRoute(body());
  const fixes = [...simulateFixes(nav, { speedKmh: 360, stepMs: 1000 })]; // 100 m/s
  assert.equal(fixes.length, Math.ceil(nav.lengthM / 100) + 1);
  assert.deepEqual(fixes[0].coords, SHAPE[0]);
  assert.ok(distanceM(fixes.at(-1).coords, SHAPE[5]) < 0.01);
  assert.equal(fixes[1].t, 1000);
  assert.equal(fixes[0].simulated, true);
  const off = simulateFixes(nav, { speedKmh: 36, offsetM: 120 }).next().value;
  assert.ok(Math.abs(distanceM(off.coords, SHAPE[0]) - 120) < 1);
});

test('session: simulated drive announces in order and arrives; offset drive goes off-route', () => {
  const nav = buildNavRoute(body());
  const s = createNavSession(nav);
  assert.deepEqual(s.start().map((x) => x.text), ['Drive east on Test Road.']);
  const said = [];
  let arrived = 0;
  for (const f of simulateFixes(nav, { speedKmh: 72, stepMs: 1000 })) {
    const r = s.update(f);
    said.push(...r.announcements.map((x) => x.id));
    assert.equal(r.offRoute.state, 'on');
    if (r.justArrived) arrived += 1;
  }
  assert.deepEqual(said, ['0:post', '1:alert', '1:pre', '1:post', '2:pre'] /* destination has no alert text */);
  assert.equal(arrived, 1);
  const s2 = createNavSession(nav);
  let fired = null;
  for (const f of simulateFixes(nav, { speedKmh: 36, offsetM: 120 })) { const r = s2.update(f); if (r.offRoute.fired) { fired = f.t; break; } }
  assert.equal(fired, 10000);
});

test('offline: last route is stored locally and only ever shown as stale', () => {
  const st = fakeStorage();
  assert.equal(loadLastRoute(st), null);
  const b = body();
  assert.equal(saveLastRoute(st, { to: [34.83, 32.02] }, b, 1700000000000), true);
  const got = loadLastRoute(st);
  assert.equal(got.savedAt, 1700000000000);
  assert.deepEqual(got.to, [34.83, 32.02]);
  const vm = staleViewModel(routeViewModel(200, got.body), got.savedAt);
  assert.deepEqual(vm.stale, { savedAt: 1700000000000 });
  assert.equal(staleViewModel(routeViewModel(422, {}), 1).stale, undefined);
  st.setItem('trucksil.lastRoute.v1', '{bad');
  assert.equal(loadLastRoute(st), null);
  clearLastRoute(st);
  assert.equal(loadLastRoute(st), null);
  const full = { getItem: () => null, setItem: () => { throw new Error('quota'); } };
  assert.equal(saveLastRoute(full, {}, b), false);
});

test('tiles: indices along the route, buffered, unique, capped', () => {
  assert.deepEqual(lonLatToTile(34.78, 32.08, 10), { z: 10, x: 610, y: 415 });
  const tiles = tilesAlongRoute(SHAPE, [10, 14], { buffer: 0 });
  const keys = tiles.map((x) => `${x.z}/${x.x}/${x.y}`);
  assert.equal(new Set(keys).size, keys.length);
  assert.ok(keys.includes('10/610/415'));
  assert.ok(tiles.filter((x) => x.z === 14).length >= 3);
  assert.equal(tilesAlongRoute(SHAPE, [14], { buffer: 2, maxTiles: 10 }).length, 10);
});
