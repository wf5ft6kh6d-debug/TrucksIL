#!/usr/bin/env node
'use strict';
/**
 * Importer for the (not yet published) Israel MoT GIS layer "גשרים" (spec v1)
 * -> TrucksIL restriction records (data/restrictions.schema.json).
 * See docs/DATA_SOURCES.md section 6. Gavrit_* is the limit PER ROAD SIGN
 * (valueSource "posted_sign"), not a measured clearance. Unit is not stated
 * in the spec: metres are ASSUMED and a warning is always emitted.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { itmToWgs84 } = require('./itm');

const SOURCE_NAME = 'Israel Ministry of Transport – GIS layer גשרים';
const DEFAULT_LICENSE = 'UNCONFIRMED';
const SCHEMA_PATH = path.join(__dirname, '..', '..', 'data', 'restrictions.schema.json');
const ROAD_FUNCTIONS = new Set([1, 3, 6]); // over road, over road+rail, vehicle passage
const KNOWN_FUNCTIONS = new Set([1, 2, 3, 4, 5, 6, 7]);
const MAX_HEIGHT_M = 50;

let cachedValidator = null;
function getValidator() {
  if (cachedValidator) return cachedValidator;
  const Ajv2020 = require('ajv/dist/2020');
  const addFormats = require('ajv-formats');
  const ajv = new Ajv2020({ allErrors: true, strict: true, strictTuples: false, allowUnionTypes: true });
  addFormats(ajv);
  cachedValidator = ajv.compile(JSON.parse(fs.readFileSync(SCHEMA_PATH, 'utf8')));
  return cachedValidator;
}

const isBlank = (v) => v === undefined || v === null || (typeof v === 'string' && v.trim() === '');

/** Case-insensitive property lookup over several alias names. */
function pick(props, names) {
  const keys = Object.keys(props);
  for (const n of names) {
    const k = keys.find((key) => key.toLowerCase() === n.toLowerCase());
    if (k !== undefined && !isBlank(props[k])) return { key: k, value: props[k] };
  }
  for (const n of names) {
    const k = keys.find((key) => key.toLowerCase() === n.toLowerCase());
    if (k !== undefined) return { key: k, value: props[k] };
  }
  return { key: null, value: undefined };
}

/** Parse a height value. Returns {value} or {reason}. */
function parseHeight(raw) {
  if (isBlank(raw)) return { reason: 'blank' };
  const n = typeof raw === 'number' ? raw : Number(String(raw).trim().replace(',', '.'));
  if (!Number.isFinite(n)) return { reason: 'non_numeric' };
  if (n === -1) return { reason: 'sentinel_-1' };
  if (n === 9999) return { reason: 'sentinel_9999' };
  if (n <= 0) return { reason: 'non_positive' };
  if (n > MAX_HEIGHT_M) return { reason: 'out_of_range_gt_50' };
  return { value: n };
}

function parseFunction(raw) {
  if (isBlank(raw)) return null;
  const n = Number(String(raw).trim());
  return Number.isInteger(n) && KNOWN_FUNCTIONS.has(n) ? n : null;
}

/** D_Update YYYYMM -> ISO first day of month UTC, or null. */
function parseDUpdate(raw) {
  if (isBlank(raw)) return null;
  const m = /^(\d{4})(\d{2})$/.exec(String(raw).trim().replace(/\.0+$/, ''));
  if (!m) return null;
  const y = Number(m[1]), mo = Number(m[2]);
  if (mo < 1 || mo > 12 || y < 1900) return null;
  return new Date(Date.UTC(y, mo - 1, 1)).toISOString();
}

/** Detect whether the collection is in EPSG:2039. */
function detectCrs(fc, override) {
  if (override) return override;
  const name = fc && fc.crs && fc.crs.properties && fc.crs.properties.name;
  if (typeof name === 'string') {
    if (/2039/.test(name)) return 'EPSG:2039';
    if (/4326|CRS84/i.test(name)) return 'EPSG:4326';
  }
  return null; // decide per coordinate
}

function looksLikeItm([x, y]) {
  return x > 100000 && x < 300000 && y > 350000 && y < 820000;
}
function looksLikeWgs84([lon, lat]) {
  return lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90;
}

/** Representative point of a geometry (Point, or first vertex / midpoint of lines). */
function representativePosition(geom) {
  if (!geom || !geom.coordinates) return null;
  const c = geom.coordinates;
  switch (geom.type) {
    case 'Point': return c;
    case 'MultiPoint': case 'LineString': return c[Math.floor(c.length / 2)] || null;
    case 'MultiLineString': case 'Polygon': return (c[0] && c[0][Math.floor(c[0].length / 2)]) || null;
    case 'MultiPolygon': return (c[0] && c[0][0] && c[0][0][0]) || null;
    default: return null;
  }
}

function toWgs84(pos, crs) {
  if (!Array.isArray(pos) || pos.length < 2 || !pos.slice(0, 2).every(Number.isFinite)) return null;
  const xy = [pos[0], pos[1]];
  const useItm = crs === 'EPSG:2039' || (crs === null && looksLikeItm(xy));
  const out = useItm ? itmToWgs84(xy[0], xy[1]) : xy;
  if (!looksLikeWgs84(out)) return null;
  return [Math.round(out[0] * 1e7) / 1e7, Math.round(out[1] * 1e7) / 1e7];
}

function stableId(bridgeKey, placement) {
  const h = crypto.createHash('sha1').update(`mot-bridges|${bridgeKey}|${placement || ''}|max_height`).digest('hex').slice(0, 12);
  return `mot-bridge-${String(bridgeKey).replace(/[^A-Za-z0-9_-]/g, '_')}${placement ? `-${String(placement).replace(/[^A-Za-z0-9_-]/g, '_')}` : ''}-maxheight-${h}`;
}

/**
 * @param {object} fc GeoJSON FeatureCollection
 * @param {{license?: string, crs?: string, now?: Date|string}} [opts]
 */
function importBridges(fc, opts = {}) {
  const license = opts.license || DEFAULT_LICENSE;
  const nowIso = new Date(opts.now || Date.now()).toISOString();
  const validate = getValidator();
  const records = [], skipped = [], warnings = [];
  const stats = { features: 0, records: 0, skipped: 0, unknownHeight: 0, notOverRoad: 0, invalid: 0, itmConverted: 0 };
  const warn = (msg) => { if (!warnings.includes(msg)) warnings.push(msg); };

  warn('Unit of Gavrit_min/Gavrit_max is not stated in the spec; metres assumed. Confirm in writing before production import.');
  if (license === DEFAULT_LICENSE) warn('Source license is UNCONFIRMED (see docs/DATA_SOURCES.md 6.3).');
  if (!fc || fc.type !== 'FeatureCollection' || !Array.isArray(fc.features)) {
    throw new TypeError('Input must be a GeoJSON FeatureCollection');
  }
  const crs = detectCrs(fc, opts.crs);
  if (crs === null) warn('No CRS declared; coordinates auto-detected per feature (ITM range -> EPSG:2039, else WGS84).');

  const seenIds = new Set();
  fc.features.forEach((feature, index) => {
    stats.features++;
    const p = (feature && feature.properties) || {};
    const objectId = pick(p, ['OBJECTID']).value;
    const bridgeId = pick(p, ['ID']).value;
    const ref = { index, OBJECTID: isBlank(objectId) ? null : objectId, ID: isBlank(bridgeId) ? null : bridgeId, NAME: isBlank(p.NAME) ? null : p.NAME };
    const skip = (reason, extra = {}) => { skipped.push({ ...ref, reason, ...extra }); stats.skipped++; };

    const key = !isBlank(bridgeId) ? String(bridgeId).trim() : !isBlank(objectId) ? String(objectId).trim() : null;
    if (key === null) return skip('missing_id');

    const fnRaw = pick(p, ['Function']).value;
    const fn = parseFunction(fnRaw);
    if (fn !== null && !ROAD_FUNCTIONS.has(fn)) { stats.notOverRoad++; return skip('not_over_road', { Function: fn }); }
    if (fn === null && !isBlank(fnRaw)) warn(`Unrecognised Function value(s) treated as unknown (e.g. "${fnRaw}").`);

    const minF = pick(p, ['Gavrit_min', 'Min_Gavrit']);
    const maxF = pick(p, ['Gavrit_max', 'Max_Gavrit']);
    if (minF.key && minF.key.toLowerCase() === 'min_gavrit') warn('Field alias Min_Gavrit used instead of Gavrit_min.');
    if (maxF.key && maxF.key.toLowerCase() === 'max_gavrit') warn('Field alias Max_Gavrit used instead of Gavrit_max.');
    const h = parseHeight(minF.value);
    if (h.reason) {
      stats.unknownHeight++;
      return skip('unknown_height', { detail: h.reason, rawGavritMin: minF.value === undefined ? null : minF.value });
    }
    // Gavrit_max has no place in the schema (additionalProperties:false) -> not emitted.
    const hMax = parseHeight(maxF.value);
    if (hMax.value !== undefined && hMax.value < h.value) {
      warn(`Gavrit_max < Gavrit_min for ${key}; Gavrit_min used.`);
    }

    const pos = representativePosition(feature.geometry);
    const coords = toWgs84(pos, crs);
    if (!coords) return skip('invalid_geometry');
    if (crs === 'EPSG:2039' || (crs === null && looksLikeItm(pos))) stats.itmConverted++;

    const placement = isBlank(p.Placement) ? null : String(p.Placement).trim();
    let id = stableId(key, placement);
    if (seenIds.has(id)) { id = `${id}-${index}`; warn(`Duplicate bridge key ${key}/${placement || ''}; index suffix added.`); }
    seenIds.add(id);

    const observed = parseDUpdate(pick(p, ['D_Update']).value);
    if (!observed) warn('Some records lack a valid D_Update; import time used as observedAt.');

    const record = {
      id,
      roadSegmentId: `mot-bridge:${key}`,
      geometry: { type: 'Point', coordinates: coords },
      valueSource: 'posted_sign',
      restrictionType: 'max_height',
      value: h.value,
      unit: 'm',
      status: 'unverified',
      source: { name: SOURCE_NAME, reference: `OBJECTID:${isBlank(objectId) ? key : objectId}`, license },
      observedAt: observed || nowIso,
    };
    if (!validate(record)) {
      stats.invalid++;
      return skip('schema_invalid', { errors: validate.errors.map((e) => `${e.instancePath} ${e.message}`) });
    }
    records.push(record);
    stats.records++;
  });
  return { records, skipped, warnings, stats };
}

function main(argv) {
  const args = argv.slice(2);
  let input = null, license, crs;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--license') license = args[++i];
    else if (args[i] === '--crs') crs = args[++i];
    else if (args[i] === '-h' || args[i] === '--help') input = null, i = args.length;
    else input = args[i];
  }
  if (!input) {
    process.stderr.write('Usage: node src/importers/mot-bridges.js input.geojson [--license ID] [--crs EPSG:2039|EPSG:4326] > out.json\n');
    return 2;
  }
  const fc = JSON.parse(fs.readFileSync(input, 'utf8'));
  process.stdout.write(JSON.stringify(importBridges(fc, { license, crs }), null, 2) + '\n');
  return 0;
}

module.exports = { importBridges, parseHeight, parseDUpdate, SOURCE_NAME, DEFAULT_LICENSE };
if (require.main === module) process.exitCode = main(process.argv);
