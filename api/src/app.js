'use strict';
// HTTP handler for the TrucksIL API. Dependencies (db, valhalla) are injected so tests need no Docker.
const http = require('node:http');
const {
  TRUCKSIL_NOTICE, loadVehicleValidator, parseBbox, validateRouteRequest, buildValhallaRouteRequest,
} = require('./lib');

const MAX_BODY = 64 * 1024;

const RESTRICTIONS_SQL = `
SELECT id, road_segment_id, ST_AsGeoJSON(geometry)::json AS geometry, value_source, direction,
       restriction_type, value_numeric, value_boolean, unit, time_windows, status, source,
       observed_at, verified_by, verified_at, review_due_at
FROM restrictions
WHERE geometry IS NOT NULL
  AND geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
ORDER BY id
LIMIT 5000`;

function rowToFeature(r) {
  const iso = (d) => (d instanceof Date ? d.toISOString() : d);
  const props = {
    id: r.id,
    roadSegmentId: r.road_segment_id,
    valueSource: r.value_source,
    direction: r.direction,
    restrictionType: r.restriction_type,
    value: r.unit === 'boolean' ? r.value_boolean : r.value_numeric,
    unit: r.unit,
    timeWindows: r.time_windows,
    status: r.status,
    source: r.source,
    observedAt: iso(r.observed_at),
    verifiedBy: r.verified_by,
    verifiedAt: iso(r.verified_at),
    reviewDueAt: iso(r.review_due_at),
  };
  for (const k of Object.keys(props)) if (props[k] === null || props[k] === undefined) delete props[k];
  return { type: 'Feature', id: r.id, geometry: r.geometry, properties: props };
}

function send(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'content-length': Buffer.byteLength(body) });
  res.end(body);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(Object.assign(new Error('body too large'), { status: 413 })); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || 'null')); }
      catch { reject(Object.assign(new Error('invalid JSON'), { status: 400 })); }
    });
    req.on('error', reject);
  });
}

/**
 * @param {object} deps
 * @param {{query: Function}|null} deps.db  pg Pool-like object
 * @param {string} [deps.valhallaUrl]       base URL; empty/undefined = routing disabled
 * @param {Function} [deps.fetch]           fetch implementation
 * @param {number} [deps.timeoutMs]
 */
function createHandler({ db, valhallaUrl, fetch = globalThis.fetch, timeoutMs = 15000, validateVehicle = loadVehicleValidator() } = {}) {
  const base = valhallaUrl ? valhallaUrl.replace(/\/+$/, '') : '';

  async function checkDb() {
    if (!db) return 'down';
    try { await db.query('SELECT 1'); return 'ok'; } catch { return 'down'; }
  }

  async function checkValhalla() {
    if (!base) return 'disabled';
    try {
      const r = await fetch(`${base}/status`, { signal: AbortSignal.timeout(3000) });
      return r.ok ? 'ok' : 'down';
    } catch { return 'down'; }
  }

  async function health(_req, res) {
    const [dbState, valhalla] = await Promise.all([checkDb(), checkValhalla()]);
    const status = dbState === 'ok' && valhalla !== 'down' ? 'ok' : 'degraded';
    send(res, status === 'ok' ? 200 : 503, { status, db: dbState, valhalla });
  }

  async function restrictions(_req, res, url) {
    const bbox = parseBbox(url.searchParams.get('bbox'));
    if (!bbox.ok) return send(res, 400, { error: bbox.error });
    if (!db) return send(res, 503, { error: 'database unavailable' });
    const { minLon, minLat, maxLon, maxLat } = bbox.value;
    let rows;
    try { ({ rows } = await db.query(RESTRICTIONS_SQL, [minLon, minLat, maxLon, maxLat])); }
    catch { return send(res, 503, { error: 'database unavailable' }); }
    send(res, 200, { type: 'FeatureCollection', features: rows.map(rowToFeature) });
  }

  async function route(req, res) {
    let body;
    try { body = await readJson(req); } catch (e) { return send(res, e.status || 400, { error: e.message }); }
    const v = validateRouteRequest(body, validateVehicle);
    if (!v.ok) return send(res, 400, { error: 'invalid request', details: v.errors });
    if (!base) {
      return send(res, 503, { error: 'routing disabled: Valhalla is not configured (start with `docker compose --profile routing up` and set VALHALLA_URL)', trucksil: TRUCKSIL_NOTICE });
    }
    let r;
    try {
      r = await fetch(`${base}/route`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(buildValhallaRouteRequest(body)),
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (e) {
      return send(res, 503, { error: `routing unavailable: Valhalla unreachable at ${base} (${e.name})`, trucksil: TRUCKSIL_NOTICE });
    }
    let result;
    try { result = await r.json(); } catch { return send(res, 502, { error: 'invalid response from Valhalla', trucksil: TRUCKSIL_NOTICE }); }
    if (!r.ok) {
      // 4xx from Valhalla (e.g. no route found) is passed through; 5xx becomes 502.
      return send(res, r.status >= 500 ? 502 : r.status, { error: 'Valhalla error', valhalla: result, trucksil: TRUCKSIL_NOTICE });
    }
    send(res, 200, { ...result, trucksil: TRUCKSIL_NOTICE });
  }

  return async function handler(req, res) {
    const url = new URL(req.url, 'http://localhost');
    try {
      if (req.method === 'GET' && url.pathname === '/health') return await health(req, res, url);
      if (req.method === 'GET' && url.pathname === '/v1/restrictions') return await restrictions(req, res, url);
      if (req.method === 'POST' && url.pathname === '/v1/route') return await route(req, res, url);
      if (['/health', '/v1/restrictions', '/v1/route'].includes(url.pathname)) return send(res, 405, { error: 'method not allowed' });
      send(res, 404, { error: 'not found' });
    } catch (e) {
      console.error(e);
      if (!res.headersSent) send(res, 500, { error: 'internal error' });
    }
  };
}

function createServer(deps) {
  return http.createServer(createHandler(deps));
}

module.exports = { createHandler, createServer, rowToFeature };
