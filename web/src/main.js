// TrucksIL PWA prototype (stage 4, first slice). NOT FOR NAVIGATION.
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
// MapLibre 6 loads its worker relative to its own module URL, which bundling breaks; let Vite
// bundle the worker (with its shared chunk) and hand MapLibre the resulting URL.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import './styles.css';
import schema from '../../data/vehicle-profile.schema.json';
import { LANGS, resolveLang, t, applyLang } from './i18n.js';
import { ADR_CLASSES, createVehicleValidator, profileFromForm, parseLonLat } from './validation.js';
import { loadProfiles, saveProfile, deleteProfile } from './storage.js';
import { routeViewModel, markersGeoJSON, noDataGeoJSON } from './viewModel.js';
import { requestRoute } from './api.js';
import { vectorStyle, rasterFallbackStyle, isPmtilesHeader, nameExpr, PMTILES_PATH } from './map/style.js';
import { Protocol, PMTiles } from 'pmtiles';
import { buildNavRoute } from './nav/progress.js';
import { createNavSession } from './nav/session.js';
import { createRateLimiter } from './nav/offRoute.js';
import { warningText, distanceParams } from './nav/announce.js';
import { createSpeechQueue, SPEECH_LANG } from './nav/speech.js';
import { simulateFixes } from './nav/simulate.js';
import { saveLastRoute, loadLastRoute, staleViewModel, formatSavedAt } from './nav/offline.js';
import { tilesAlongRoute } from './nav/tiles.js';
import { REPORT_TYPES, getClientId, reportItems, reportsGeoJSON, validateDraft, submitMessage, postReport, fetchReports, voteReport } from './reports.js';

const LANG_KEY = 'trucksil.lang';
const store = (() => { try { return window.localStorage; } catch { return null; } })();
const memStore = new Map();
const storage = store || { getItem: (k) => memStore.get(k) ?? null, setItem: (k, v) => memStore.set(k, v) };

let lang = resolveLang(storage.getItem(LANG_KEY), navigator.languages || []);
let lastVm = null;
let pickTarget = null; // 'from' | 'to' | 'report'
let reportPos = null;
let areaReports = [];
const validateProfile = createVehicleValidator(schema);

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
  for (const k of kids) n.append(k);
  return n;
};

// ---------- i18n ----------
function renderStrings() {
  applyLang(document.documentElement, lang);
  document.title = `${t(lang, 'app.title')} — ${t(lang, 'banner.prototype')}`;
  for (const n of document.querySelectorAll('[data-i18n]')) n.textContent = t(lang, n.dataset.i18n);
  $('#lang').value = lang;
  renderSaved();
  renderReportTypes();
  renderReports();
  if (lastVm) renderRestrictions(lastVm);
  if (vectorMap && map.isStyleLoaded()) {
    for (const l of map.getStyle().layers) if (l.type === 'symbol' && l.layout && Array.isArray(l.layout['text-field']) && l.layout['text-field'][0] === 'coalesce') map.setLayoutProperty(l.id, 'text-field', nameExpr(lang));
  }
  $('#map-notice').hidden = vectorMap;
  $('#map-notice').textContent = vectorMap ? '' : t(lang, 'map.fallback');
  renderNav();
  renderVoiceMsg();
}

// ---------- profiles (US-01) ----------
function renderAdr() {
  const box = $('#adr');
  for (const c of ADR_CLASSES) {
    box.append(el('label', { class: 'chk' }, el('input', { type: 'checkbox', name: 'adr', value: c }), c));
  }
}

function readProfileForm() {
  const f = $('#profile');
  const raw = Object.fromEntries(new FormData(f).entries());
  raw.adrClasses = [...f.querySelectorAll('input[name=adr]:checked')].map((x) => x.value);
  return profileFromForm(raw);
}

function fillProfileForm(p) {
  const f = $('#profile');
  for (const k of ['profileName', 'heightM', 'widthM', 'lengthM', 'grossWeightT', 'axleLoadT', 'note']) f.elements[k].value = p && p[k] !== undefined ? p[k] : '';
  const cls = (p && p.hazmat && p.hazmat.adrClasses) || [];
  for (const cb of f.querySelectorAll('input[name=adr]')) cb.checked = cls.includes(cb.value);
}

function renderSaved(selected) {
  const sel = $('#saved');
  const cur = selected ?? sel.value;
  sel.replaceChildren(el('option', { value: '' }, t(lang, 'profile.none')));
  for (const p of loadProfiles(storage)) sel.append(el('option', { value: p.profileName }, p.profileName));
  sel.value = [...sel.options].some((o) => o.value === cur) ? cur : '';
}

function showMsg(target, text, cls = '', items = []) {
  const box = $(target);
  box.className = `msg ${cls}`;
  box.replaceChildren(text);
  if (items.length) box.append(el('ul', {}, ...items.map((i) => el('li', { dir: 'ltr' }, i))));
}

// ---------- map ----------
maplibregl.setWorkerUrl(workerUrl);
// Offline map (ADR-0015): self-hosted Israel PMTiles + glyphs when data/tiles/israel.pmtiles is
// installed; otherwise the online OSM raster prototype fallback (dev only, never cached).
// RTL (Hebrew/Arabic) labels need no plugin in MapLibre 6 (setRTLTextPlugin is deprecated).
let pmtiles = null;
async function probePmtiles() {
  try {
    const r = await fetch(PMTILES_PATH, { headers: { Range: 'bytes=0-7' }, signal: AbortSignal.timeout(4000) });
    return r.ok && isPmtilesHeader(new Uint8Array(await r.arrayBuffer()));
  } catch { return false; }
}
const vectorMap = await probePmtiles();
if (vectorMap) {
  const protocol = new Protocol();
  maplibregl.addProtocol('pmtiles', protocol.tile);
  pmtiles = new PMTiles(`${location.origin}${PMTILES_PATH}`);
  protocol.add(pmtiles);
}
const map = new maplibregl.Map({
  container: 'map',
  style: vectorMap ? vectorStyle({ origin: location.origin, lang }) : rasterFallbackStyle(),
  center: [34.9, 31.9],
  zoom: 7,
});
$('#map').dataset.basemap = vectorMap ? 'pmtiles' : 'osm-raster';
map.addControl(new maplibregl.NavigationControl(), 'top-left');

const EMPTY = { type: 'FeatureCollection', features: [] };
map.on('load', () => {
  map.addSource('route', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'route', type: 'line', source: 'route', paint: { 'line-color': '#1565c0', 'line-width': 5 } });
  // Bridges/tunnels without TrucksIL data (ADR-0014): dashed amber over the route.
  map.addSource('nodata', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'nodata', type: 'line', source: 'nodata', paint: { 'line-color': '#ff8f00', 'line-width': 7, 'line-dasharray': [1.5, 1] } });
  map.addSource('points', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'points', type: 'circle', source: 'points', paint: { 'circle-radius': 6, 'circle-color': '#222', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } });
  map.addSource('restr', { type: 'geojson', data: EMPTY });
  map.addLayer({
    id: 'restr',
    type: 'circle',
    source: 'restr',
    paint: {
      'circle-radius': 8,
      'circle-color': ['match', ['get', 'kind'], 'onRoute', '#f9a825', '#c62828'],
      'circle-stroke-color': ['match', ['get', 'status'], 'verified', '#1b5e20', '#000'],
      'circle-stroke-width': ['match', ['get', 'status'], 'verified', 3, 1.5],
    },
  });
  // Driver reports: separate source/layer, purple dashed-looking ring, never mixed with restrictions.
  map.addSource('reports', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'reports', type: 'circle', source: 'reports', paint: { 'circle-radius': 7, 'circle-color': '#f3e5f5', 'circle-stroke-color': '#8e24aa', 'circle-stroke-width': 3, 'circle-opacity': 0.9 } });
  // Current (or simulated) position while navigating. Never stored or sent anywhere.
  map.addSource('me', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'me', type: 'circle', source: 'me', paint: { 'circle-radius': 8, 'circle-color': ['case', ['get', 'sim'], '#6a1b9a', '#1e88e5'], 'circle-stroke-color': '#fff', 'circle-stroke-width': 3 } });
  if (lastVm) drawVm(lastVm);
  loadAreaReports();
});
map.on('moveend', () => loadAreaReports());
map.on('contextmenu', (e) => startReport([e.lngLat.lng, e.lngLat.lat])); // long-press / right click

map.on('click', (e) => {
  if (!pickTarget) return;
  if (pickTarget === 'report') { pickTarget = null; map.getCanvas().style.cursor = ''; startReport([e.lngLat.lng, e.lngLat.lat]); return; }
  $('#route').elements[pickTarget].value = `${e.lngLat.lng.toFixed(5)},${e.lngLat.lat.toFixed(5)}`;
  pickTarget = null;
  map.getCanvas().style.cursor = '';
  showMsg('#route-msg', '');
  drawPoints();
});

function drawPoints() {
  const src = map.getSource && map.getSource('points');
  if (!src) return;
  const f = $('#route');
  const feats = ['from', 'to'].map((k) => parseLonLat(f.elements[k].value)).filter(Boolean)
    .map((c) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: c }, properties: {} }));
  src.setData({ type: 'FeatureCollection', features: feats });
}

function drawVm(vm, { fit = true } = {}) {
  // Number of route vertices currently drawn (0 = no route); also read by the smoke test.
  $('#map').dataset.routePoints = String(vm.route ? vm.route.length : 0);
  $('#map').dataset.noDataSegments = String(vm.structures ? vm.structures.noData.length : 0);
  if (!map.getSource('route')) return;
  // Only a 'route' view model carries geometry; conflicts/errors clear any previous route.
  map.getSource('route').setData(vm.route ? { type: 'Feature', geometry: { type: 'LineString', coordinates: vm.route }, properties: {} } : EMPTY);
  map.getSource('restr').setData(markersGeoJSON(vm));
  if (map.getSource('nodata')) map.getSource('nodata').setData(vm.route ? noDataGeoJSON(vm) : EMPTY);
  const pts = vm.route || [...vm.conflicts, ...vm.avoided].map((x) => x.position).filter(Boolean);
  if (pts.length && fit) {
    const b = pts.reduce((acc, p) => acc.extend(p), new maplibregl.LngLatBounds(pts[0], pts[0]));
    map.fitBounds(b, { padding: 60, maxZoom: 15, duration: 0 });
  }
}

// ---------- driver reports (stage 5, ADR-0012) ----------
function renderReportTypes() {
  const sel = $('#report-type');
  const cur = sel.value;
  sel.replaceChildren(...REPORT_TYPES.map((k) => el('option', { value: k }, t(lang, `rtype.${k}`))));
  if (cur) sel.value = cur;
}

function startReport(pos) {
  reportPos = [Number(pos[0].toFixed(5)), Number(pos[1].toFixed(5))];
  $('#report-form').hidden = false;
  showMsg('#report-msg', `${reportPos[0]},${reportPos[1]}`);
}

function reportNode(it) {
  const li = el('li', { class: 'report', 'data-id': it.id },
    el('span', { class: 'type' }, t(lang, it.typeKey)), ' ',
    el('span', { class: 'badge report' }, t(lang, it.labelKey)), ' ',
    el('span', { class: 'src' }, [it.ageMinutes !== null ? t(lang, 'reports.age', { min: it.ageMinutes }) : '', t(lang, 'reports.confirmations', { n: it.confirmations })].filter(Boolean).join(' · ')));
  if (it.note) li.append(el('div', { class: 'reason' }, el('bdi', {}, it.note)));
  const votes = el('div', { class: 'votes' });
  for (const v of ['confirm', 'reject']) {
    const b = el('button', { type: 'button', class: 'secondary', 'data-vote': v }, t(lang, `reports.${v}`));
    b.addEventListener('click', async () => {
      const r = await voteReport(it.id, v, getClientId(storage));
      const m = submitMessage('vote', r.status);
      showMsg('#report-msg', t(lang, m.key, { status: r.status ?? '—' }), m.cls);
      loadAreaReports();
    });
    votes.append(b);
  }
  li.append(votes);
  return li;
}

function renderReports() {
  const body = $('#reports-body');
  body.replaceChildren(areaReports.length ? el('ul', {}, ...areaReports.map(reportNode)) : el('p', { class: 'none' }, t(lang, 'reports.none')));
  const src = map.getSource && map.getSource('reports');
  const routeReports = lastVm ? lastVm.reports : [];
  const seen = new Set(areaReports.map((r) => r.id));
  if (src) src.setData(reportsGeoJSON([...areaReports, ...routeReports.filter((r) => !seen.has(r.id))]));
}

async function loadAreaReports() {
  if (!map.getBounds) return;
  const b = map.getBounds();
  const { status, body } = await fetchReports([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]);
  areaReports = status === 200 && body ? reportItems(body.reports) : [];
  renderReports();
}

// ---------- restrictions panel ----------
function itemNode(it) {
  const value = it.valueText !== null ? el('bdi', { dir: 'ltr', class: 'value' }, it.valueText) : el('span', { class: 'value' }, t(lang, it.valueBoolKey));
  const li = el('li', { class: `restr ${it.kind}`, 'data-id': it.id },
    el('span', { class: 'type' }, t(lang, it.typeKey)), ' ', value, ' ',
    el('span', { class: 'src' }, `(${t(lang, it.valueSourceKey)})`), ' ',
    el('span', { class: `badge ${it.status}` }, t(lang, it.statusKey)));
  if (it.reason) li.append(el('div', { class: 'reason' }, `${t(lang, 'restr.reason')}: `, el('bdi', { dir: 'ltr' }, it.reason)));
  return li;
}

function listSection(titleKey, items) {
  return el('div', { class: 'list' }, el('h3', {}, t(lang, titleKey)),
    items.length ? el('ul', {}, ...items.map(itemNode)) : el('p', { class: 'none' }, t(lang, 'restr.none')));
}

function renderRestrictions(vm) {
  const body = $('#restr-body');
  body.replaceChildren();
  if (vm.error) {
    const box = el('div', { class: 'error', role: 'alert' }, el('strong', {}, t(lang, vm.error.key, { status: vm.error.status ?? '—' })));
    if (vm.error.message) box.append(el('div', { dir: 'ltr', class: 'detail' }, vm.error.message));
    if (vm.error.details.length) box.append(el('ul', { dir: 'ltr' }, ...vm.error.details.map((d) => el('li', {}, d))));
    body.append(box);
  }
  if (vm.kind === 'conflict') {
    body.append(listSection('restr.conflicts', vm.conflicts));
    if (vm.avoided.length) body.append(listSection('restr.avoided', vm.avoided));
  }
  if (vm.kind === 'route') {
    if (vm.stale) body.append(el('p', { class: 'offline-route', role: 'alert' }, t(lang, 'offline.route', { time: formatSavedAt(vm.stale.savedAt, lang) })));
    if (vm.summary) body.append(el('p', { class: 'summary' }, t(lang, 'route.summary', vm.summary)));
    body.append(listSection('restr.avoided', vm.avoided), listSection('restr.onRoute', vm.onRoute));
    if (vm.coverage) body.append(el('p', { class: 'coverage' }, t(lang, 'restr.coverage', vm.coverage)));
    if (vm.structures) {
      body.append(el('p', { class: `coverage structures ${vm.structures.status}` }, t(lang, vm.structures.key, vm.structures)));
      if (vm.structures.noData.length) body.append(el('p', { class: 'legend-nodata' }, el('span', { class: 'swatch-nodata', 'aria-hidden': 'true' }), ' ', t(lang, 'legend.noData')));
    }
    if (vm.reports.length) body.append(el('div', { class: 'list' }, el('h3', {}, t(lang, 'reports.nearRoute')), el('ul', {}, ...vm.reports.map(reportNode))));
  }
  // Coverage caveat is repeated with every result, whatever happened (ADR-0002).
  if (vm.kind !== 'error') body.append(el('p', { class: 'caveat' }, t(lang, 'banner.coverage')));
}

// ---------- wiring ----------
function init() {
  renderAdr();
  renderStrings();
  $('#lang').addEventListener('change', (e) => {
    if (!LANGS.includes(e.target.value)) return;
    lang = e.target.value;
    storage.setItem(LANG_KEY, lang);
    renderStrings();
  });
  $('#saved').addEventListener('change', (e) => {
    fillProfileForm(loadProfiles(storage).find((p) => p.profileName === e.target.value) || null);
    showMsg('#profile-msg', '');
  });
  $('#profile').addEventListener('submit', (e) => {
    e.preventDefault();
    const p = readProfileForm();
    const v = validateProfile(p);
    if (!v.ok) return showMsg('#profile-msg', t(lang, 'profile.invalid'), 'bad', v.errors.map((x) => x.message));
    saveProfile(storage, p);
    renderSaved(p.profileName);
    showMsg('#profile-msg', t(lang, 'profile.savedOk'), 'good');
  });
  $('#del').addEventListener('click', () => {
    const name = $('#saved').value;
    if (!name) return;
    deleteProfile(storage, name);
    fillProfileForm(null);
    renderSaved('');
  });
  for (const b of document.querySelectorAll('[data-pick]')) {
    b.addEventListener('click', () => {
      pickTarget = b.dataset.pick;
      map.getCanvas().style.cursor = 'crosshair';
      showMsg('#route-msg', t(lang, 'route.pickHint'));
    });
  }
  $('#report-add').addEventListener('click', () => {
    pickTarget = 'report';
    map.getCanvas().style.cursor = 'crosshair';
    showMsg('#report-msg', t(lang, 'reports.pickHint'));
  });
  $('#report-cancel').addEventListener('click', () => { reportPos = null; $('#report-form').hidden = true; showMsg('#report-msg', ''); });
  $('#report-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const draft = { type: e.target.elements.type.value, position: reportPos, note: e.target.elements.note.value.trim() };
    const bad = validateDraft(draft);
    if (bad) return showMsg('#report-msg', t(lang, bad), 'bad');
    const r = await postReport(draft, getClientId(storage));
    const m = submitMessage('create', r.status);
    showMsg('#report-msg', t(lang, m.key, { status: r.status ?? '—' }), m.cls);
    if (r.status === 201) { e.target.reset(); e.target.hidden = true; reportPos = null; loadAreaReports(); }
  });
  for (const k of ['from', 'to']) $('#route').elements[k].addEventListener('change', drawPoints);
  $('#route').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    const from = parseLonLat(f.elements.from.value);
    const to = parseLonLat(f.elements.to.value);
    if (!from || !to) return showMsg('#route-msg', t(lang, 'route.badPoint'), 'bad');
    const vehicle = readProfileForm();
    const v = validateProfile(vehicle);
    if (!v.ok) return showMsg('#route-msg', t(lang, 'route.needProfile'), 'bad', v.errors.map((x) => x.message));
    showMsg('#route-msg', t(lang, 'route.loading'));
    drawPoints();
    stopNav();
    const request = { from, to, vehicle, uiLang: lang, language: SPEECH_LANG[lang] };
    const { status, body } = await requestRoute(request);
    showMsg('#route-msg', '');
    showRoute(request, status, body);
  });
  if ('serviceWorker' in navigator && import.meta.env.PROD) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
}

// ---------- route result, offline copy (ADR-0015) ----------
let lastRequest = null; // {from, to, vehicle, uiLang, language} of the route on screen
let lastBody = null;
let prefetchToken = 0;

function showRoute(request, status, body, { fit = true } = {}) {
  if (status === null) {
    // Network failure: show the last stored route, explicitly flagged as outdated. Never a "valid" route.
    const saved = loadLastRoute(storage);
    if (saved) {
      lastVm = staleViewModel(routeViewModel(200, saved.body), saved.savedAt);
      lastBody = lastVm.kind === 'route' ? saved.body : null;
      lastRequest = lastBody ? { ...request, to: saved.to || request.to } : null;
      renderRestrictions(lastVm);
      drawVm(lastVm, { fit });
      renderReports();
      renderNav();
      return lastVm;
    }
  }
  lastVm = routeViewModel(status, body);
  lastBody = lastVm.kind === 'route' ? body : null;
  lastRequest = lastBody ? request : null;
  if (lastBody) {
    saveLastRoute(storage, { to: request.to }, body);
    prefetchRouteTiles(lastVm.route);
  }
  renderRestrictions(lastVm);
  drawVm(lastVm, { fit });
  renderReports();
  renderNav();
  return lastVm;
}

// Warm the offline tile cache along the route (the service worker stores the byte ranges).
async function prefetchRouteTiles(route) {
  if (!pmtiles || !route) return;
  const token = ++prefetchToken;
  for (const { z, x, y } of tilesAlongRoute(route, [8, 10, 12, 14], { buffer: 1, maxTiles: 600 })) {
    if (token !== prefetchToken || !navigator.onLine) return;
    try { await pmtiles.getZxy(z, x, y); } catch { /* offline or missing tile: ignore */ }
  }
}

// ---------- voice (Web Speech API) ----------
const VOICE_KEY = 'trucksil.voice';
const speech = createSpeechQueue({ synth: window.speechSynthesis || null, Utterance: window.SpeechSynthesisUtterance || null });

function renderVoiceMsg() {
  const box = $('#voice-msg');
  if (!box) return;
  if (!speech.supported) return showMsg('#voice-msg', t(lang, 'nav.voiceUnsupported'), 'bad');
  if (!speech.enabled) return showMsg('#voice-msg', '');
  speech.setLang(lastRequest ? lastRequest.language : SPEECH_LANG[lang]);
  showMsg('#voice-msg', speech.voiceStatus() === 'noVoice' ? t(lang, 'nav.noVoice') : '', 'bad');
}

// ---------- navigation: GPS / simulation, off-route + reroute ----------
const REROUTE_MIN_INTERVAL_MS = 30000;
let run = null; // {session, mode, watchId, timer, fixes, reroutes, msg, last, limiter, rerouting}

function routeTr(k, p) { return t(lastRequest ? lastRequest.uiLang : lang, k, p); }

function sayAll(items) {
  for (const a of items) {
    if (a.kind === 'warning') speech.say(warningText(routeTr, a.warning), { priority: 'high' });
    else speech.say(a.text);
  }
}

function setMe(fix) {
  const src = map.getSource && map.getSource('me');
  if (src) src.setData(fix ? { type: 'Feature', geometry: { type: 'Point', coordinates: fix.coords }, properties: { sim: Boolean(fix.simulated) } } : EMPTY);
}

function renderNav() {
  const box = $('#nav-status');
  if (!box) return;
  const hasRoute = Boolean(lastBody);
  $('#nav-start').disabled = Boolean(run) || !hasRoute;
  $('#nav-sim').disabled = Boolean(run) || !hasRoute;
  $('#nav-stop').disabled = !run;
  box.className = 'msg';
  if (!run) {
    box.dataset.state = 'idle';
    box.replaceChildren(run === null && box.dataset.final ? t(lang, box.dataset.final) : '');
    return;
  }
  const kids = [];
  if (run.mode === 'sim') kids.push(el('span', { class: 'sim' }, t(lang, 'nav.simulated')), ' ');
  const last = run.last;
  if (!last) {
    kids.push(t(lang, 'nav.waiting'));
  } else {
    const st = last.offRoute.state;
    kids.push(el('span', { class: `state-${st}` }, t(lang, `nav.state.${st}`)));
    const p = last.progress;
    if (p && p.nextIndex !== null) {
      const m = run.session.nav.maneuvers[p.nextIndex];
      const dp = distanceParams(p.distanceToNextM);
      kids.push(el('div', { class: 'next' }, el('bdi', {}, t(lang, 'nav.next', { instruction: m.instruction || m.verbalPre || '—' })), ' ', t(lang, 'nav.inDist', { dist: t(lang, dp.key, { n: dp.n }) })));
    }
    if (p) kids.push(el('div', {}, t(lang, 'nav.remaining', { km: (p.remainingM / 1000).toFixed(1) })));
  }
  if (run.msg) kids.push(el('div', { class: run.msgCls || '' }, t(lang, run.msg.key, run.msg.params)));
  box.dataset.state = last ? last.offRoute.state : 'waiting';
  box.dataset.next = last && last.progress && last.progress.nextIndex !== null ? String(last.progress.nextIndex) : '';
  box.dataset.reroutes = String(run.reroutes);
  box.dataset.mode = run.mode;
  box.replaceChildren(...kids);
}

function startNav(mode) {
  if (!lastBody || run) return;
  const nav = buildNavRoute(lastBody, lastVm);
  if (!nav) return showMsg('#nav-status', t(lang, 'nav.needRoute'), 'bad');
  delete $('#nav-status').dataset.final;
  run = { mode, session: createNavSession(nav), watchId: null, timer: null, reroutes: 0, msg: null, last: null, limiter: createRateLimiter(REROUTE_MIN_INTERVAL_MS), rerouting: false };
  speech.setLang(lastRequest.language);
  sayAll(run.session.start());
  if (mode === 'sim') startSim(nav, Number($('#nav-offset').value) || 0);
  else startGps();
  renderNav();
}

function startSim(nav, offsetM) {
  const speedKmh = Math.min(3000, Math.max(5, Number($('#nav-speed').value) || 60));
  const fixes = simulateFixes(nav, { speedKmh, stepMs: 1000, offsetM, startMs: performance.now() });
  clearInterval(run.timer);
  run.timer = setInterval(() => {
    const n = fixes.next();
    if (n.done) { clearInterval(run.timer); return; }
    onFix(n.value);
  }, 1000);
}

function startGps() {
  if (!('geolocation' in navigator)) { finishNav('nav.geoUnsupported'); return; }
  run.watchId = navigator.geolocation.watchPosition(
    (pos) => onFix({ coords: [pos.coords.longitude, pos.coords.latitude], accuracyM: pos.coords.accuracy, speedMps: pos.coords.speed, t: pos.timestamp }),
    (err) => {
      if (err.code === 1) finishNav('nav.geoDenied');
      else if (run) { run.msg = { key: 'nav.geoError', params: { message: err.message || err.code } }; run.msgCls = 'bad'; renderNav(); }
    },
    { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 },
  );
}

function stopNav() {
  if (!run) return;
  clearInterval(run.timer);
  if (run.watchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(run.watchId);
  run = null;
  speech.cancel();
  setMe(null);
  renderNav();
}

function finishNav(key) {
  stopNav();
  $('#nav-status').dataset.final = key;
  renderNav();
}

function onFix(fix) {
  if (!run) return;
  setMe(fix);
  const r = run.session.update(fix);
  run.last = r;
  if (r.offRoute.changed && r.offRoute.state === 'on') run.msg = null;
  sayAll(r.announcements);
  if (r.offRoute.state === 'off') maybeReroute(fix);
  if (r.justArrived) {
    // Spoken arrival comes from Valhalla's destination maneuver; the UI line is ours.
    run.msg = { key: 'nav.arrived', params: {} };
    run.msgCls = 'good';
    if (run.mode === 'sim') clearInterval(run.timer);
  }
  renderNav();
}

async function maybeReroute(fix) {
  if (run.rerouting) return;
  if (!navigator.onLine || (lastVm && lastVm.stale)) { run.msg = { key: 'nav.rerouteOffline', params: {} }; run.msgCls = 'bad'; return; }
  const now = performance.now();
  if (!run.limiter.tryAcquire(now)) { run.msg = { key: 'nav.rerouteWait', params: { s: Math.ceil(run.limiter.msUntilNext(now) / 1000) } }; run.msgCls = 'bad'; return; }
  const current = run;
  current.rerouting = true;
  current.msg = { key: 'nav.rerouting', params: {} };
  current.msgCls = 'bad';
  renderNav();
  // The ONLY moment the position leaves the device: as the start point of the new route request.
  const from = [Number(fix.coords[0].toFixed(5)), Number(fix.coords[1].toFixed(5))];
  const request = { ...lastRequest, from };
  const { status, body } = await requestRoute(request);
  if (run !== current) return; // stopped meanwhile
  current.rerouting = false;
  if (status === null) { current.msg = { key: 'nav.rerouteOffline', params: {} }; renderNav(); return; }
  if (status !== 200) {
    // ADR-0002: a conflict/error never yields a route; show it and stop guiding.
    showRoute(request, status, body, { fit: false });
    speech.cancel();
    speech.say(routeTr('nav.rerouteFailed'), { priority: 'high' });
    finishNav('nav.rerouteFailed');
    return;
  }
  const vm = showRoute(request, status, body, { fit: false });
  const nav = vm.kind === 'route' ? buildNavRoute(body, vm) : null;
  if (!nav) { finishNav('nav.rerouteFailed'); return; }
  current.session = createNavSession(nav);
  current.reroutes += 1;
  current.msg = null;
  current.last = null;
  sayAll(current.session.start());
  if (current.mode === 'sim') startSim(nav, 0); // simulated vehicle follows the new route
  renderNav();
}

function initNav() {
  $('#nav-start').addEventListener('click', () => startNav('gps'));
  $('#nav-sim').addEventListener('click', () => startNav('sim'));
  $('#nav-stop').addEventListener('click', () => stopNav());
  const voice = $('#nav-voice');
  voice.checked = storage.getItem(VOICE_KEY) === '1' && speech.supported;
  voice.disabled = !speech.supported;
  speech.setEnabled(voice.checked);
  voice.addEventListener('change', () => {
    speech.setEnabled(voice.checked);
    storage.setItem(VOICE_KEY, voice.checked ? '1' : '0');
    renderVoiceMsg();
  });
  if (window.speechSynthesis && 'onvoiceschanged' in window.speechSynthesis) window.speechSynthesis.onvoiceschanged = renderVoiceMsg;
  renderNav();
  renderVoiceMsg();
}

init();
initNav();
