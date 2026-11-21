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
const map = new maplibregl.Map({
  container: 'map',
  // Prototype only: public OSM raster tiles. See docs/DEV_SETUP.md (OSM tile usage policy).
  style: {
    version: 8,
    sources: {
      osm: {
        type: 'raster',
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
  },
  center: [34.9, 31.9],
  zoom: 7,
});
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

function drawVm(vm) {
  // Number of route vertices currently drawn (0 = no route); also read by the smoke test.
  $('#map').dataset.routePoints = String(vm.route ? vm.route.length : 0);
  $('#map').dataset.noDataSegments = String(vm.structures ? vm.structures.noData.length : 0);
  if (!map.getSource('route')) return;
  // Only a 'route' view model carries geometry; conflicts/errors clear any previous route.
  map.getSource('route').setData(vm.route ? { type: 'Feature', geometry: { type: 'LineString', coordinates: vm.route }, properties: {} } : EMPTY);
  map.getSource('restr').setData(markersGeoJSON(vm));
  if (map.getSource('nodata')) map.getSource('nodata').setData(vm.route ? noDataGeoJSON(vm) : EMPTY);
  const pts = vm.route || [...vm.conflicts, ...vm.avoided].map((x) => x.position).filter(Boolean);
  if (pts.length) {
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
    const { status, body } = await requestRoute({ from, to, vehicle });
    lastVm = routeViewModel(status, body);
    showMsg('#route-msg', '');
    renderRestrictions(lastVm);
    drawVm(lastVm);
    renderReports();
  });
  if ('serviceWorker' in navigator && import.meta.env.PROD) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
}

init();
