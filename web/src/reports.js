// Driver reports (stage 5, ADR-0012): view model, anonymous client id, API calls.
// Pure except for injected storage/fetch. Reports are UNVERIFIED and always labelled as such.
import { API_BASE } from './api.js';

export const REPORT_TYPES = ['traffic', 'accident', 'hazard', 'camera', 'low_clearance', 'other'];
export const CLIENT_KEY = 'trucksil.clientId.v1';
export const CLIENT_HEADER = 'x-trucksil-client';
export const NOTE_MAX = 280;

/**
 * Anonymous random client id, kept in localStorage. It is not tied to any account or device data;
 * the server stores only a salted hash of it.
 */
export function getClientId(storage, randomBytes = (n) => crypto.getRandomValues(new Uint8Array(n))) {
  try {
    const cur = storage.getItem(CLIENT_KEY);
    if (cur && /^[A-Za-z0-9_-]{16,128}$/.test(cur)) return cur;
  } catch { /* storage unavailable */ }
  const id = Array.from(randomBytes(16), (b) => b.toString(16).padStart(2, '0')).join('');
  try { storage.setItem(CLIENT_KEY, id); } catch { /* ignore */ }
  return id;
}

/** One report for display. `labelKey` is always the "unverified driver report" label. */
export function reportItem(r) {
  return {
    id: String(r.id),
    type: r.type,
    typeKey: `rtype.${REPORT_TYPES.includes(r.type) ? r.type : 'other'}`,
    labelKey: 'reports.unverified',
    position: Array.isArray(r.position) && r.position.length === 2 && r.position.every(Number.isFinite) ? r.position : null,
    note: typeof r.note === 'string' && r.note ? r.note : null,
    ageMinutes: Number.isFinite(r.ageMinutes) ? r.ageMinutes : null,
    confirmations: Number.isFinite(r.confirmations) ? r.confirmations : 0,
  };
}

export function reportItems(list) { return Array.isArray(list) ? list.map(reportItem) : []; }

/** GeoJSON for the dedicated (distinctly styled) report layer. */
export function reportsGeoJSON(items) {
  return {
    type: 'FeatureCollection',
    features: items.filter((it) => it.position).map((it) => ({
      type: 'Feature', geometry: { type: 'Point', coordinates: it.position }, properties: { id: it.id, type: it.type, unverified: true },
    })),
  };
}

/** Client-side check mirroring the API; returns an i18n key or null. */
export function validateDraft({ type, position, note }) {
  if (!REPORT_TYPES.includes(type)) return 'reports.type';
  if (!Array.isArray(position) || position.length !== 2 || !position.every(Number.isFinite)) return 'reports.pickHint';
  if (typeof note === 'string' && [...note.trim()].length > NOTE_MAX) return 'reports.note';
  return null;
}

/** Maps a POST /v1/reports or /vote outcome to a message key. */
export function submitMessage(kind, status) {
  if (kind === 'create') {
    if (status === 201) return { key: 'reports.sent', cls: 'good' };
    if (status === 429) return { key: 'reports.rateLimited', cls: 'bad' };
    return { key: 'reports.failed', cls: 'bad' };
  }
  if (status === 200) return { key: 'reports.voted', cls: 'good' };
  if (status === 409) return { key: 'reports.alreadyVoted', cls: 'bad' };
  return { key: 'reports.failed', cls: 'bad' };
}

async function jsonCall(fetchImpl, url, init) {
  let res;
  try { res = await fetchImpl(url, init); } catch { return { status: null, body: null }; }
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  return { status: res.status, body };
}

const headers = (clientId) => ({ 'content-type': 'application/json', [CLIENT_HEADER]: clientId });

export function postReport({ type, position, note }, clientId, fetchImpl = globalThis.fetch) {
  return jsonCall(fetchImpl, `${API_BASE}/v1/reports`, { method: 'POST', headers: headers(clientId), body: JSON.stringify({ type, position, note: note || undefined }) });
}

export function fetchReports(bbox, fetchImpl = globalThis.fetch) {
  return jsonCall(fetchImpl, `${API_BASE}/v1/reports?bbox=${bbox.map((n) => n.toFixed(5)).join(',')}`, { method: 'GET' });
}

export function voteReport(id, vote, clientId, fetchImpl = globalThis.fetch) {
  return jsonCall(fetchImpl, `${API_BASE}/v1/reports/${encodeURIComponent(id)}/vote`, { method: 'POST', headers: headers(clientId), body: JSON.stringify({ vote }) });
}
