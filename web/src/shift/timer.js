// Shift timer (US-06, ADR-0018). Pure logic: state machine, totals, alerts, persistence, CSV.
// A REMINDER only — not legal certification of compliance with working/rest-time rules.
// Time is always derived from event timestamps (Date.now deltas), never from counting ticks, so a
// sleeping tab or a reload loses nothing. Storage is injected (localStorage in the app).

export const STATE_KEY = 'trucksil.shift.v1';
export const SETTINGS_KEY = 'trucksil.shift.settings.v1';
export const HISTORY_KEY = 'trucksil.shift.history.v1';
export const HISTORY_MAX = 7;

const H = 3600000;
const M = 60000;
/** Minutes before a limit at which an alert fires; 0 = the limit itself. */
export const THRESHOLDS_MIN = [120, 60, 30, 0];
/** Defaults are configurable reminders, not a statement of the law. */
export const DEFAULT_SETTINGS = Object.freeze({ shiftLimitH: 12, drivingLimitH: 9, breakReminderH: 4.5 });
export const LIMITS = ['shift', 'driving', 'continuous'];

const ACTIONS = {
  idle: { start: 'driving' },
  driving: { break: 'break', end: 'ended' },
  break: { resume: 'driving', end: 'ended' },
  ended: {},
};

export function initialState() { return { v: 1, status: 'idle', events: [], fired: [] }; }

export function canApply(state, action) { return Boolean(ACTIONS[state.status] && ACTIONS[state.status][action]); }

const lastAt = (state) => (state.events.length ? state.events[state.events.length - 1].at : -Infinity);
// A clock that jumped backwards must not produce negative durations.
const clampAt = (state, at) => Math.max(Number(at), lastAt(state));

/** Returns a new state, or the same state if the transition is not allowed. */
export function apply(state, action, at) {
  if (!canApply(state, action)) return state;
  const t = clampAt(state, at);
  return { ...state, status: ACTIONS[state.status][action], events: [...state.events, { type: action, at: t }], fired: action === 'start' ? [] : state.fired };
}

/** Driving / break / elapsed / current continuous driving, in ms, at time `at`. */
export function totals(state, at) {
  const ev = state.events;
  if (!ev.length) return { drivingMs: 0, breakMs: 0, elapsedMs: 0, continuousMs: 0, breaks: 0, stint: 0 };
  const end = state.status === 'ended' ? lastAt(state) : clampAt(state, at);
  let drivingMs = 0; let breakMs = 0; let breaks = 0; let stint = 0; let continuousMs = 0;
  for (let i = 0; i < ev.length; i += 1) {
    const e = ev[i];
    const until = i + 1 < ev.length ? ev[i + 1].at : end;
    const d = Math.max(0, until - e.at);
    if (e.type === 'start' || e.type === 'resume') { drivingMs += d; stint += 1; continuousMs = d; }
    else if (e.type === 'break') { breakMs += d; breaks += 1; continuousMs = 0; }
  }
  if (state.status !== 'driving') continuousMs = 0;
  return { drivingMs, breakMs, elapsedMs: end - ev[0].at, continuousMs, breaks, stint };
}

export function normalizeSettings(s = {}) {
  const num = (v, d, min, max) => { const n = Number(v); return Number.isFinite(n) && n >= min && n <= max ? n : d; };
  const br = s.breakReminderH === null || s.breakReminderH === 0 || s.breakReminderH === '' ? null : num(s.breakReminderH, DEFAULT_SETTINGS.breakReminderH, 0.25, 24);
  return {
    shiftLimitH: num(s.shiftLimitH, DEFAULT_SETTINGS.shiftLimitH, 0.5, 24),
    drivingLimitH: num(s.drivingLimitH, DEFAULT_SETTINGS.drivingLimitH, 0.5, 24),
    breakReminderH: s.breakReminderH === undefined ? DEFAULT_SETTINGS.breakReminderH : br,
  };
}

/** Active limits: [{limit, usedMs, limitMs, running, key}] — `key` scopes the once-only alert ids. */
function limitsOf(state, settings, at) {
  const s = normalizeSettings(settings);
  const tt = totals(state, at);
  const driving = state.status === 'driving';
  const out = [
    { limit: 'shift', usedMs: tt.elapsedMs, limitMs: s.shiftLimitH * H, running: driving || state.status === 'break', key: 'shift' },
    { limit: 'driving', usedMs: tt.drivingMs, limitMs: s.drivingLimitH * H, running: driving, key: 'driving' },
  ];
  // Continuous-driving reminder re-arms for each driving stint (after every break).
  if (s.breakReminderH) out.push({ limit: 'continuous', usedMs: tt.continuousMs, limitMs: s.breakReminderH * H, running: driving, key: `continuous#${tt.stint}` });
  return out;
}

/**
 * Fires every alert whose threshold has been crossed and not yet fired this shift. When several
 * thresholds of one limit were crossed at once (tab slept), only the most urgent is reported, the
 * rest are marked as fired. Thresholds not shorter than the limit itself are skipped.
 * @returns {{state, alerts: Array<{id, limit, minutesBefore, remainingMs}>}}
 */
export function checkAlerts(state, settings, at) {
  if (state.status !== 'driving' && state.status !== 'break') return { state, alerts: [] };
  const fired = new Set(state.fired);
  const alerts = [];
  for (const l of limitsOf(state, settings, at)) {
    if (!l.running) continue;
    const remainingMs = l.limitMs - l.usedMs;
    let best = null;
    for (const th of THRESHOLDS_MIN) {
      if (th > 0 && th * M >= l.limitMs) continue;
      const id = `${l.key}:${th}`;
      if (fired.has(id) || remainingMs > th * M) continue;
      fired.add(id);
      if (!best || th < best.minutesBefore) best = { id, limit: l.limit, minutesBefore: th, remainingMs };
    }
    if (best) alerts.push(best);
  }
  if (!alerts.length) return { state, alerts };
  return { state: { ...state, fired: [...fired] }, alerts };
}

/** The next unfired alert among running limits: {limit, minutesBefore, inMs} or null. */
export function nextAlert(state, settings, at) {
  if (state.status !== 'driving' && state.status !== 'break') return null;
  let best = null;
  for (const l of limitsOf(state, settings, at)) {
    if (!l.running) continue;
    for (const th of THRESHOLDS_MIN) {
      if (th > 0 && th * M >= l.limitMs) continue;
      if (state.fired.includes(`${l.key}:${th}`)) continue;
      const inMs = l.limitMs - l.usedMs - th * M;
      if (inMs < 0) continue;
      if (!best || inMs < best.inMs) best = { limit: l.limit, minutesBefore: th, inMs };
    }
  }
  return best;
}

// ---------- persistence ----------
const read = (storage, key) => { try { return JSON.parse(storage.getItem(key) || 'null'); } catch { return null; } };
const write = (storage, key, v) => { try { storage.setItem(key, JSON.stringify(v)); return true; } catch { return false; } };

export function loadState(storage) {
  const s = read(storage, STATE_KEY);
  if (!s || s.v !== 1 || !ACTIONS[s.status] || !Array.isArray(s.events) || !Array.isArray(s.fired)) return initialState();
  const events = s.events.filter((e) => e && typeof e.type === 'string' && Number.isFinite(e.at));
  return { v: 1, status: s.status, events, fired: s.fired.filter((x) => typeof x === 'string') };
}
export function saveState(storage, state) { return write(storage, STATE_KEY, state); }
export function loadSettings(storage) { return normalizeSettings(read(storage, SETTINGS_KEY) || {}); }
export function saveSettings(storage, settings) { const s = normalizeSettings(settings); write(storage, SETTINGS_KEY, s); return s; }

export function loadHistory(storage) {
  const h = read(storage, HISTORY_KEY);
  return Array.isArray(h) ? h.filter((x) => x && Number.isFinite(x.startedAt) && Number.isFinite(x.endedAt)).slice(0, HISTORY_MAX) : [];
}

/** Summary of an ended shift, as stored in history. */
export function summarize(state) {
  const tt = totals(state, lastAt(state));
  return { startedAt: state.events[0].at, endedAt: lastAt(state), drivingMs: tt.drivingMs, breakMs: tt.breakMs, elapsedMs: tt.elapsedMs, breaks: tt.breaks };
}

/** Moves an ended shift to history (newest first, last HISTORY_MAX kept) and resets the current one. */
export function archiveShift(storage, state) {
  if (state.status !== 'ended' || !state.events.length) return loadHistory(storage);
  const list = [summarize(state), ...loadHistory(storage)].slice(0, HISTORY_MAX);
  write(storage, HISTORY_KEY, list);
  saveState(storage, initialState());
  return list;
}

export function clearHistory(storage) { write(storage, HISTORY_KEY, []); return []; }

// ---------- CSV ----------
const csvCell = (v) => { const s = String(v); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
const mins = (ms) => Math.round(ms / M);

/** CSV of history (UTC ISO times, minutes). Header is fixed English for spreadsheets. */
export function toCsv(history) {
  const rows = [['shift_start_utc', 'shift_end_utc', 'driving_min', 'break_min', 'elapsed_min', 'breaks']];
  for (const h of history) rows.push([new Date(h.startedAt).toISOString(), new Date(h.endedAt).toISOString(), mins(h.drivingMs), mins(h.breakMs), mins(h.elapsedMs), h.breaks]);
  return `${rows.map((r) => r.map(csvCell).join(',')).join('\r\n')}\r\n`;
}

/** "H:MM" for durations (never negative). */
export function formatDuration(ms) {
  const m = Math.max(0, Math.floor(ms / M));
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`;
}
