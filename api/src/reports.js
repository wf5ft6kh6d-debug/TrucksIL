'use strict';
// Driver reports (stage 5, ADR-0012). UNVERIFIED crowd hints, kept apart from `restrictions`:
// they never influence the routing safety check, they are only attached for information.
const crypto = require('node:crypto');
const { parseBbox } = require('./lib');

const REPORT_TYPES = Object.freeze(['traffic', 'accident', 'hazard', 'camera', 'low_clearance', 'other']);
const H = 3600 * 1000;
const REPORT_TTL_MS = Object.freeze({
  traffic: 1 * H, accident: 3 * H, hazard: 12 * H, camera: 30 * 24 * H, low_clearance: 30 * 24 * H, other: 6 * H,
});
// Generous Israel bbox (incl. Eilat and the Golan), WGS84.
const ISRAEL_BBOX = Object.freeze({ minLon: 34.2, minLat: 29.4, maxLon: 35.95, maxLat: 33.4 });
const NOTE_MAX = 280;
const RATE_LIMIT = Object.freeze({ max: 5, windowMs: 10 * 60 * 1000 });
const AUTO_HIDE_MIN_REJECTIONS = 3;
const ROUTE_BUFFER_M = 100;
const CLIENT_HEADER = 'x-trucksil-client';
const MODERATOR_HEADER = 'x-moderator-token';
const DEV_SALT = 'trucksil-dev-salt-do-not-use-in-production';

let warnedSalt = false;
const REPORT_LABEL = Object.freeze({ verified: false, label: 'unverified driver report' });

function ttlFor(type) { return REPORT_TTL_MS[type]; }
function expiresAt(type, now) { return new Date(now.getTime() + ttlFor(type)); }

/** Validates the POST /v1/reports body. Returns {ok, value|errors}. */
function validateReport(body) {
  const errors = [];
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { ok: false, errors: ['body must be a JSON object'] };
  if (!REPORT_TYPES.includes(body.type)) errors.push(`type must be one of ${REPORT_TYPES.join(', ')}`);
  const p = body.position;
  if (!Array.isArray(p) || p.length !== 2 || !p.every(Number.isFinite)) errors.push('position must be [lon, lat]');
  else if (p[0] < ISRAEL_BBOX.minLon || p[0] > ISRAEL_BBOX.maxLon || p[1] < ISRAEL_BBOX.minLat || p[1] > ISRAEL_BBOX.maxLat) errors.push('position must be inside Israel');
  let note = null;
  if (body.note !== undefined && body.note !== null) {
    if (typeof body.note !== 'string') errors.push('note must be a string');
    else {
      note = body.note.trim();
      if ([...note].length > NOTE_MAX) errors.push(`note must be at most ${NOTE_MAX} characters`);
      if (note === '') note = null;
    }
  }
  if (errors.length) return { ok: false, errors };
  return { ok: true, value: { type: body.type, position: [p[0], p[1]], note } };
}

/** Anonymous client id: opaque 16..128 chars of [A-Za-z0-9_-]. Never stored raw. */
function validClientId(id) { return typeof id === 'string' && /^[A-Za-z0-9_-]{16,128}$/.test(id); }
function hashClient(id, salt) { return crypto.createHmac('sha256', salt).update(id).digest('hex'); }

function shouldAutoHide({ confirmations, rejections }) {
  return rejections >= AUTO_HIDE_MIN_REJECTIONS && rejections > confirmations;
}

/** In-memory sliding window limiter, keyed by reporter hash. Lost on restart (prototype). */
function createRateLimiter({ max = RATE_LIMIT.max, windowMs = RATE_LIMIT.windowMs } = {}) {
  const hits = new Map();
  return {
    take(key, nowMs) {
      const arr = (hits.get(key) || []).filter((t) => nowMs - t < windowMs);
      if (arr.length >= max) { hits.set(key, arr); return { ok: false, retryAfterS: Math.ceil((windowMs - (nowMs - arr[0])) / 1000) }; }
      arr.push(nowMs);
      hits.set(key, arr);
      if (hits.size > 10000) for (const [k, v] of hits) if (!v.some((t) => nowMs - t < windowMs)) hits.delete(k);
      return { ok: true };
    },
  };
}

function safeEqual(a, b) {
  const x = Buffer.from(String(a)); const y = Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

// ---------- PostGIS repository ----------
const COLS = `id, type, ST_X(geometry) AS lon, ST_Y(geometry) AS lat, note, created_at, expires_at, status, confirmations, rejections`;
const SQL = {
  insert: `INSERT INTO driver_reports (type, geometry, note, created_at, expires_at, status, reporter_hash)
VALUES ($1, ST_SetSRID(ST_MakePoint($2, $3), 4326), $4, $5, $6, 'visible', $7)
RETURNING ${COLS}`,
  bbox: `SELECT ${COLS} FROM driver_reports
WHERE status = 'visible' AND expires_at > $5
  AND geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
ORDER BY created_at DESC
LIMIT 500`,
  nearRoute: `SELECT ${COLS} FROM driver_reports
WHERE status = 'visible' AND expires_at > $2
  AND ST_DWithin(geometry::geography, ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)::geography, $3)
ORDER BY created_at DESC
LIMIT 100`,
  get: `SELECT ${COLS} FROM driver_reports WHERE id = $1`,
  vote: `WITH ins AS (
  INSERT INTO driver_report_votes (report_id, reporter_hash, vote) VALUES ($1, $2, $3)
  ON CONFLICT (report_id, reporter_hash) DO NOTHING RETURNING vote
)
UPDATE driver_reports SET
  confirmations = confirmations + (SELECT count(*) FROM ins WHERE vote = 'confirm'),
  rejections = rejections + (SELECT count(*) FROM ins WHERE vote = 'reject')
WHERE id = $1 AND EXISTS (SELECT 1 FROM ins)
RETURNING ${COLS}`,
  setStatus: `UPDATE driver_reports SET status = $2 WHERE id = $1 RETURNING ${COLS}`,
  audit: `INSERT INTO report_moderation (report_id, action, actor, reason) VALUES ($1, $2, $3, $4)`,
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function createReportsRepo(db) {
  const one = async (sql, p) => (await db.query(sql, p)).rows[0] || null;
  return {
    insert: ({ type, position, note, createdAt, expiresAt: exp, reporterHash }) => one(SQL.insert, [type, position[0], position[1], note, createdAt, exp, reporterHash]),
    listBbox: async ({ minLon, minLat, maxLon, maxLat }, now) => (await db.query(SQL.bbox, [minLon, minLat, maxLon, maxLat, now])).rows,
    nearRoute: async (coords, now, meters = ROUTE_BUFFER_M) => (await db.query(SQL.nearRoute, [JSON.stringify({ type: 'LineString', coordinates: coords }), now, meters])).rows,
    get: (id) => one(SQL.get, [id]),
    /** Returns the updated row, or null when this reporter already voted. */
    vote: (id, reporterHash, vote) => one(SQL.vote, [id, reporterHash, vote]),
    setStatus: async (id, status, { action, actor, reason = null }) => {
      const row = await one(SQL.setStatus, [id, status]);
      if (row) await db.query(SQL.audit, [id, action, actor, reason]);
      return row;
    },
  };
}

/** Public JSON shape. Never exposes reporter_hash. */
function rowToReport(r, now) {
  const iso = (d) => (d instanceof Date ? d.toISOString() : d);
  const created = new Date(r.created_at);
  return {
    id: r.id,
    type: r.type,
    position: [Number(r.lon), Number(r.lat)],
    note: r.note ?? null,
    createdAt: iso(r.created_at),
    expiresAt: iso(r.expires_at),
    ageMinutes: Math.max(0, Math.floor((now.getTime() - created.getTime()) / 60000)),
    confirmations: Number(r.confirmations),
    rejections: Number(r.rejections),
    ...REPORT_LABEL,
  };
}

// ---------- HTTP handlers ----------
/**
 * @returns {null | function(req, res, url, helpers): Promise<boolean>}  true when handled
 */
function createReportsRoutes({
  repo, salt = process.env.REPORTS_SALT, moderatorToken = process.env.MODERATOR_TOKEN,
  now = () => new Date(), limiter = createRateLimiter(), log = console,
} = {}) {
  if (!salt) { if (!warnedSalt) log.warn('REPORTS_SALT is not set: using the development salt. Set REPORTS_SALT in production.'); warnedSalt = true; salt = DEV_SALT; }

  function reporter(req) {
    const id = req.headers[CLIENT_HEADER];
    return validClientId(id) ? hashClient(id, salt) : null;
  }

  async function create(req, res, { send, readJson }) {
    const hash = reporter(req);
    if (!hash) return send(res, 400, { error: `${CLIENT_HEADER} header with an anonymous client id is required` });
    let body;
    try { body = await readJson(req); } catch (e) { return send(res, e.status || 400, { error: e.message }); }
    const v = validateReport(body);
    if (!v.ok) return send(res, 400, { error: 'invalid report', details: v.errors });
    if (!repo) return send(res, 503, { error: 'database unavailable' });
    const t = now();
    const rl = limiter.take(hash, t.getTime());
    if (!rl.ok) return send(res, 429, { error: 'too many reports, try later', retryAfterS: rl.retryAfterS });
    const row = await repo.insert({ ...v.value, createdAt: t, expiresAt: expiresAt(v.value.type, t), reporterHash: hash });
    send(res, 201, { id: row.id, report: rowToReport(row, t) });
  }

  async function list(_req, res, url, { send }) {
    const bbox = parseBbox(url.searchParams.get('bbox'));
    if (!bbox.ok) return send(res, 400, { error: bbox.error });
    if (!repo) return send(res, 503, { error: 'database unavailable' });
    const t = now();
    const rows = await repo.listBbox(bbox.value, t);
    send(res, 200, { reports: rows.map((r) => rowToReport(r, t)), notice: 'unverified driver reports; not official data' });
  }

  async function vote(req, res, id, { send, readJson }) {
    const hash = reporter(req);
    if (!hash) return send(res, 400, { error: `${CLIENT_HEADER} header with an anonymous client id is required` });
    let body;
    try { body = await readJson(req); } catch (e) { return send(res, e.status || 400, { error: e.message }); }
    const choice = body && body.vote;
    if (choice !== 'confirm' && choice !== 'reject') return send(res, 400, { error: 'vote must be confirm or reject' });
    if (!repo) return send(res, 503, { error: 'database unavailable' });
    const t = now();
    const cur = await repo.get(id);
    if (!cur || cur.status !== 'visible' || new Date(cur.expires_at) <= t) return send(res, 404, { error: 'report not found' });
    let row = await repo.vote(id, hash, choice);
    if (!row) return send(res, 409, { error: 'already voted' });
    if (shouldAutoHide(row)) {
      row = (await repo.setStatus(id, 'hidden', { action: 'auto_hide', actor: 'system', reason: `rejections ${row.rejections} > confirmations ${row.confirmations}` })) || row;
    }
    send(res, 200, { report: rowToReport(row, t), status: row.status });
  }

  async function moderate(req, res, id, { send, readJson }) {
    // No token configured -> moderation is disabled (403), never open.
    if (!moderatorToken || !safeEqual(req.headers[MODERATOR_HEADER] || '', moderatorToken)) return send(res, 403, { error: 'forbidden' });
    let body;
    try { body = await readJson(req); } catch (e) { return send(res, e.status || 400, { error: e.message }); }
    const action = body && body.action;
    if (action !== 'hide' && action !== 'show') return send(res, 400, { error: 'action must be hide or show' });
    if (!repo) return send(res, 503, { error: 'database unavailable' });
    const reason = typeof body.reason === 'string' ? body.reason.slice(0, 280) : null;
    const row = await repo.setStatus(id, action === 'hide' ? 'hidden' : 'visible', { action, actor: 'moderator', reason });
    if (!row) return send(res, 404, { error: 'report not found' });
    send(res, 200, { id, status: row.status });
  }

  return async function route(req, res, url, helpers) {
    const p = url.pathname;
    if (p === '/v1/reports') {
      if (req.method === 'POST') { await create(req, res, helpers); return true; }
      if (req.method === 'GET') { await list(req, res, url, helpers); return true; }
      helpers.send(res, 405, { error: 'method not allowed' }); return true;
    }
    const m = /^\/v1\/reports\/([^/]+)\/(vote|moderate)$/.exec(p);
    if (!m) return false;
    if (req.method !== 'POST') { helpers.send(res, 405, { error: 'method not allowed' }); return true; }
    if (!UUID_RE.test(m[1])) { helpers.send(res, 404, { error: 'report not found' }); return true; }
    if (m[2] === 'vote') await vote(req, res, m[1].toLowerCase(), helpers);
    else await moderate(req, res, m[1].toLowerCase(), helpers);
    return true;
  };
}

/**
 * Reports within ROUTE_BUFFER_M of the final route, for trucksil.reports. Informational only:
 * failure here must never block or alter a checked route, so errors yield null.
 */
async function reportsForRoute(repo, coords, now = new Date()) {
  if (!repo || !Array.isArray(coords) || coords.length < 2) return [];
  try {
    const rows = await repo.nearRoute(coords, now, ROUTE_BUFFER_M);
    return rows.map((r) => {
      const x = rowToReport(r, now);
      return { id: x.id, type: x.type, position: x.position, ageMinutes: x.ageMinutes, confirmations: x.confirmations, ...REPORT_LABEL };
    });
  } catch (e) {
    console.error('reports near route failed:', e.message);
    return null;
  }
}

module.exports = {
  REPORT_TYPES, REPORT_TTL_MS, ISRAEL_BBOX, NOTE_MAX, RATE_LIMIT, ROUTE_BUFFER_M, CLIENT_HEADER, MODERATOR_HEADER, DEV_SALT, SQL,
  ttlFor, expiresAt, validateReport, validClientId, hashClient, shouldAutoHide, createRateLimiter,
  createReportsRepo, rowToReport, createReportsRoutes, reportsForRoute,
};
