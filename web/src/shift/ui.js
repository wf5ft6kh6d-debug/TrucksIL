// Shift timer panel (US-06, ADR-0018). DOM glue around the pure ./timer.js. All data stays in this
// browser's localStorage; nothing is sent to the API.
import { apply, canApply, totals, checkAlerts, nextAlert, loadState, saveState, loadSettings, saveSettings, loadHistory, archiveShift, clearHistory, toCsv, formatDuration } from './timer.js';

/**
 * @param {object} o
 * @param {Storage} o.storage
 * @param {object}  o.speech       speech queue (nav/speech.js); respects the user's voice toggle
 * @param {Function} o.t           (key, params) -> string in the current UI language
 * @param {Function} o.prepareVoice called before speaking (sets the speech language if idle)
 * @param {Function} [o.now]
 */
export function initShift({ storage, speech, t, prepareVoice = () => {}, now = () => Date.now() }) {
  const $ = (s) => document.querySelector(s);
  let state = loadState(storage);
  let settings = loadSettings(storage);
  let lastAlert = null;

  const alertText = (a) => t(a.minutesBefore === 0 ? `shift.alertAt.${a.limit}` : `shift.alertBefore.${a.limit}`, { time: formatDuration(a.minutesBefore * 60000) });

  function fire(alerts) {
    for (const a of alerts) {
      const text = alertText(a);
      lastAlert = text;
      prepareVoice();
      speech.say(text, { priority: 'high' }); // no-op when voice is off; the visual alert always shows
      try {
        if (typeof Notification !== 'undefined' && Notification.permission === 'granted') new Notification('TrucksIL', { body: text, tag: a.id });
      } catch { /* some browsers only allow notifications from a service worker */ }
    }
  }

  function tick() {
    const r = checkAlerts(state, settings, now());
    if (r.alerts.length) { state = r.state; saveState(storage, state); fire(r.alerts); }
    render();
  }

  function act(action) {
    if (!canApply(state, action)) return;
    state = apply(state, action, now());
    if (action === 'start') lastAlert = null;
    if (state.status === 'ended') { archiveShift(storage, state); state = loadState(storage); lastAlert = null; renderHistory(); } else saveState(storage, state);
    tick();
  }

  function render() {
    const at = now();
    const tt = totals(state, at);
    $('#shift-status').textContent = t(`shift.status.${state.status}`);
    $('#shift-status').dataset.status = state.status;
    for (const a of ['start', 'break', 'resume', 'end']) $(`#shift-${a}`).disabled = !canApply(state, a);
    $('#shift-totals').textContent = state.status === 'idle' ? '' : t('shift.totals', { driving: formatDuration(tt.drivingMs), break: formatDuration(tt.breakMs), elapsed: formatDuration(tt.elapsedMs) });
    const n = nextAlert(state, settings, at);
    $('#shift-next').textContent = n ? t('shift.next', { what: t(`shift.limit.${n.limit}`), before: formatDuration(n.minutesBefore * 60000), in: formatDuration(n.inMs) }) : '';
    const box = $('#shift-alert');
    box.hidden = !lastAlert;
    box.textContent = lastAlert || '';
  }

  function renderHistory() {
    const list = loadHistory(storage);
    const body = $('#shift-history');
    const fmt = (ms) => new Date(ms).toLocaleString(document.documentElement.lang || undefined, { dateStyle: 'short', timeStyle: 'short' });
    body.replaceChildren();
    if (!list.length) { const p = document.createElement('p'); p.className = 'none'; p.textContent = t('shift.historyNone'); body.append(p); }
    else {
      const ul = document.createElement('ul');
      for (const h of list) {
        const li = document.createElement('li');
        const when = document.createElement('bdi'); when.textContent = `${fmt(h.startedAt)} – ${fmt(h.endedAt)}`;
        li.append(when, ' · ', t('shift.totals', { driving: formatDuration(h.drivingMs), break: formatDuration(h.breakMs), elapsed: formatDuration(h.elapsedMs) }));
        ul.append(li);
      }
      body.append(ul);
    }
    $('#shift-export').disabled = !list.length;
    $('#shift-clear').disabled = !list.length;
  }

  function fillSettings() {
    $('#shift-limit').value = settings.shiftLimitH;
    $('#shift-drive-limit').value = settings.drivingLimitH;
    $('#shift-break-reminder').value = settings.breakReminderH ?? '';
  }

  for (const a of ['start', 'break', 'resume', 'end']) $(`#shift-${a}`).addEventListener('click', () => act(a));
  $('#shift-settings').addEventListener('submit', (e) => {
    e.preventDefault();
    const br = $('#shift-break-reminder').value.trim();
    settings = saveSettings(storage, { shiftLimitH: $('#shift-limit').value, drivingLimitH: $('#shift-drive-limit').value, breakReminderH: br === '' || br === '0' ? null : br });
    fillSettings();
    $('#shift-settings-msg').textContent = t('shift.settingsSaved');
    tick();
  });
  $('#shift-export').addEventListener('click', () => {
    const blob = new Blob([toCsv(loadHistory(storage))], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `trucksil-shifts-${new Date(now()).toISOString().slice(0, 10)}.csv`;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  $('#shift-clear').addEventListener('click', () => {
    if (typeof confirm === 'function' && !confirm(t('shift.clearConfirm'))) return;
    clearHistory(storage);
    renderHistory();
  });
  const notifyBtn = $('#shift-notify');
  const renderNotify = () => {
    const ok = typeof Notification !== 'undefined';
    notifyBtn.hidden = !ok || Notification.permission !== 'default';
    $('#shift-notify-msg').textContent = !ok ? t('shift.notifyUnsupported') : Notification.permission === 'granted' ? t('shift.notifyOn') : Notification.permission === 'denied' ? t('shift.notifyDenied') : '';
  };
  // Permission is requested only from this explicit user action.
  notifyBtn.addEventListener('click', async () => { try { await Notification.requestPermission(); } catch { /* ignore */ } renderNotify(); });

  fillSettings();
  renderHistory();
  renderNotify();
  tick();
  setInterval(tick, 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
  return { render: () => { render(); renderHistory(); renderNotify(); } };
}
