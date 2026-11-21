import test from 'node:test';
import assert from 'node:assert/strict';
import {
  initialState, apply, canApply, totals, checkAlerts, nextAlert, normalizeSettings, DEFAULT_SETTINGS,
  loadState, saveState, loadSettings, saveSettings, loadHistory, archiveShift, clearHistory, toCsv, formatDuration,
  STATE_KEY, HISTORY_MAX,
} from '../src/shift/timer.js';
import { STRINGS, LANGS } from '../src/i18n.js';

const H = 3600000;
const M = 60000;
const T0 = Date.UTC(2026, 10, 21, 6, 0, 0);
const mem = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), _m: m }; };

test('shift: state machine idle -> driving -> break -> driving -> ended; invalid actions ignored', () => {
  let s = initialState();
  assert.equal(canApply(s, 'break'), false);
  assert.equal(apply(s, 'break', T0), s);
  s = apply(s, 'start', T0);
  assert.equal(s.status, 'driving');
  assert.equal(apply(s, 'start', T0 + 1), s, 'no double start');
  assert.equal(apply(s, 'resume', T0 + 1), s);
  s = apply(s, 'break', T0 + 2 * H);
  assert.equal(s.status, 'break');
  s = apply(s, 'resume', T0 + 2 * H + 30 * M);
  s = apply(s, 'end', T0 + 4 * H);
  assert.equal(s.status, 'ended');
  assert.equal(canApply(s, 'start'), false);
  assert.deepEqual(s.events.map((e) => e.type), ['start', 'break', 'resume', 'end']);
});

test('shift: totals from timestamps (fake clock), frozen after end, robust to clock going back', () => {
  let s = apply(initialState(), 'start', T0);
  assert.deepEqual(totals(s, T0 + 90 * M), { drivingMs: 90 * M, breakMs: 0, elapsedMs: 90 * M, continuousMs: 90 * M, breaks: 0, stint: 1 });
  s = apply(s, 'break', T0 + 2 * H);
  let tt = totals(s, T0 + 2 * H + 20 * M);
  assert.equal(tt.drivingMs, 2 * H); assert.equal(tt.breakMs, 20 * M); assert.equal(tt.continuousMs, 0);
  s = apply(s, 'resume', T0 + 2 * H + 45 * M);
  tt = totals(s, T0 + 3 * H);
  assert.equal(tt.drivingMs, 2 * H + 15 * M); assert.equal(tt.breakMs, 45 * M); assert.equal(tt.elapsedMs, 3 * H); assert.equal(tt.continuousMs, 15 * M);
  // Tab slept 5 h: one call later sees the full delta.
  assert.equal(totals(s, T0 + 8 * H).drivingMs, 7 * H + 15 * M);
  // Clock moved backwards: no negative durations.
  assert.equal(totals(s, T0).drivingMs, 2 * H);
  s = apply(s, 'end', T0 + 4 * H);
  assert.equal(totals(s, T0 + 99 * H).elapsedMs, 4 * H);
});

test('shift: alerts at 2 h, 1 h, 30 min before and at each limit, each once per shift', () => {
  const settings = { shiftLimitH: 12, drivingLimitH: 9, breakReminderH: null };
  let s = apply(initialState(), 'start', T0);
  const ids = [];
  for (let m = 0; m <= 12 * 60; m += 1) {
    const r = checkAlerts(s, settings, T0 + m * M);
    s = r.state;
    for (const a of r.alerts) ids.push(`${a.id}@${m}`);
  }
  assert.deepEqual(ids, [
    'driving:120@420', 'driving:60@480', 'driving:30@510', 'driving:0@540',
    'shift:120@600', 'shift:60@660', 'shift:30@690', 'shift:0@720',
  ]);
  assert.deepEqual(checkAlerts(s, settings, T0 + 13 * H).alerts, [], 'no repeats');
});

test('shift: after tab sleep only the most urgent crossed alert is reported; others marked fired', () => {
  const settings = { shiftLimitH: 12, drivingLimitH: 9, breakReminderH: null };
  const s = apply(initialState(), 'start', T0);
  const r = checkAlerts(s, settings, T0 + 8 * H + 40 * M);
  assert.deepEqual(r.alerts.map((a) => a.id), ['driving:30']);
  assert.ok(r.state.fired.includes('driving:120') && r.state.fired.includes('driving:60'));
  assert.deepEqual(checkAlerts(r.state, settings, T0 + 8 * H + 41 * M).alerts, []);
});

test('shift: driving limit pauses on break; continuous-driving reminder re-arms per stint', () => {
  const settings = { shiftLimitH: 12, drivingLimitH: 9, breakReminderH: 4.5 };
  let s = apply(initialState(), 'start', T0);
  let r = checkAlerts(s, settings, T0 + 2 * H + 30 * M);
  assert.deepEqual(r.alerts.map((a) => a.id), ['continuous#1:120']);
  s = apply(r.state, 'break', T0 + 3 * H);
  r = checkAlerts(s, settings, T0 + 6 * H); // 3 h break: driving clock is paused
  assert.deepEqual(r.alerts.map((a) => a.id), []);
  s = apply(r.state, 'resume', T0 + 6 * H);
  r = checkAlerts(s, settings, T0 + 8 * H + 30 * M); // driving 5.5 h, stint 2.5 h, shift 8.5 h
  assert.deepEqual(r.alerts.map((a) => a.id), ['continuous#2:120']);
  r = checkAlerts(r.state, settings, T0 + 10 * H); // driving 7 h, shift 10 h
  assert.deepEqual(r.alerts.map((a) => a.id).sort(), ['continuous#2:30', 'driving:120', 'shift:120'].sort());
});

test('shift: thresholds not shorter than the limit are skipped; nextAlert', () => {
  const settings = { shiftLimitH: 1, drivingLimitH: 1, breakReminderH: null };
  const s = apply(initialState(), 'start', T0);
  assert.deepEqual(checkAlerts(s, settings, T0).alerts, []);
  assert.deepEqual(nextAlert(s, settings, T0), { limit: 'shift', minutesBefore: 30, inMs: 30 * M });
  const r = checkAlerts(s, settings, T0 + 30 * M);
  assert.deepEqual(r.alerts.map((a) => a.id), ['shift:30', 'driving:30']);
  assert.equal(nextAlert(initialState(), settings, T0), null);
});

test('shift: settings defaults and validation', () => {
  assert.deepEqual(normalizeSettings({}), { ...DEFAULT_SETTINGS });
  assert.deepEqual(normalizeSettings({ shiftLimitH: '10', drivingLimitH: 'x', breakReminderH: null }), { shiftLimitH: 10, drivingLimitH: 9, breakReminderH: null });
  assert.equal(normalizeSettings({ shiftLimitH: 99 }).shiftLimitH, 12);
  const st = mem();
  saveSettings(st, { drivingLimitH: 8 });
  assert.equal(loadSettings(st).drivingLimitH, 8);
});

test('shift: persistence round-trip (reload mid-shift), corrupt storage -> idle', () => {
  const st = mem();
  let s = apply(apply(initialState(), 'start', T0), 'break', T0 + H);
  s = checkAlerts(s, {}, T0 + H).state;
  saveState(st, s);
  const back = loadState(st);
  assert.deepEqual(back, s);
  assert.equal(totals(back, T0 + H + 10 * M).breakMs, 10 * M);
  st.setItem(STATE_KEY, '{not json');
  assert.deepEqual(loadState(st), initialState());
  st.setItem(STATE_KEY, JSON.stringify({ v: 1, status: 'flying', events: [], fired: [] }));
  assert.equal(loadState(st).status, 'idle');
});

test('shift: history keeps last 7, newest first; clear; CSV export', () => {
  const st = mem();
  for (let i = 0; i < 9; i += 1) {
    const b = T0 + i * 24 * H;
    let s = apply(initialState(), 'start', b);
    s = apply(s, 'break', b + 2 * H);
    s = apply(s, 'resume', b + 2 * H + 45 * M);
    s = apply(s, 'end', b + 5 * H);
    archiveShift(st, s);
  }
  const h = loadHistory(st);
  assert.equal(h.length, HISTORY_MAX);
  assert.equal(h[0].startedAt, T0 + 8 * 24 * H);
  assert.equal(loadState(st).status, 'idle', 'current shift reset after archive');
  const csv = toCsv(h.slice(0, 1));
  assert.equal(csv, 'shift_start_utc,shift_end_utc,driving_min,break_min,elapsed_min,breaks\r\n2026-11-29T06:00:00.000Z,2026-11-29T11:00:00.000Z,255,45,300,1\r\n');
  assert.deepEqual(clearHistory(st), []);
  assert.deepEqual(loadHistory(st), []);
  assert.equal(toCsv([]).split('\r\n').length, 2);
});

test('shift: formatDuration and disclaimer in all languages', () => {
  assert.equal(formatDuration(0), '0:00');
  assert.equal(formatDuration(2 * H + 5 * M + 59000), '2:05');
  assert.equal(formatDuration(-5), '0:00');
  assert.equal(STRINGS.ru['shift.disclaimer'], 'Напоминание, не юридическое подтверждение соблюдения режима труда и отдыха.');
  for (const l of LANGS) assert.ok(STRINGS[l]['shift.disclaimer'].length > 20);
});
