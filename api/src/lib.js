'use strict';
// Pure helpers for the TrucksIL API (no I/O): validation, bbox parsing, Valhalla mapping.
const fs = require('node:fs');
const path = require('node:path');
const Ajv2020 = require('ajv/dist/2020');
const addFormats = require('ajv-formats');

const SCHEMA_DIR = process.env.TRUCKSIL_SCHEMA_DIR || path.join(__dirname, '..', '..', 'data');

const TRUCKSIL_NOTICE = Object.freeze({
  disclaimer: 'prototype, not for navigation',
  // ADR-0002: absence of data is not evidence of suitability. Per-segment coverage is not computed yet.
  unverifiedCoverage: 'unknown',
});

function loadVehicleValidator(schemaDir = SCHEMA_DIR) {
  const ajv = new Ajv2020({ allErrors: true, strict: true, strictTuples: false, allowUnionTypes: true });
  addFormats(ajv);
  const schema = JSON.parse(fs.readFileSync(path.join(schemaDir, 'vehicle-profile.schema.json'), 'utf8'));
  return ajv.compile(schema);
}

/** Parses "minLon,minLat,maxLon,maxLat". Returns {ok, value|error}. */
function parseBbox(raw) {
  if (typeof raw !== 'string' || raw.trim() === '') return { ok: false, error: 'bbox is required: minLon,minLat,maxLon,maxLat' };
  const parts = raw.split(',');
  if (parts.length !== 4) return { ok: false, error: 'bbox must have exactly 4 comma-separated numbers' };
  const nums = parts.map((p) => (p.trim() === '' ? NaN : Number(p)));
  if (nums.some((n) => !Number.isFinite(n))) return { ok: false, error: 'bbox values must be finite numbers' };
  const [minLon, minLat, maxLon, maxLat] = nums;
  if (minLon < -180 || maxLon > 180 || minLat < -90 || maxLat > 90) return { ok: false, error: 'bbox out of WGS84 range' };
  if (minLon >= maxLon || minLat >= maxLat) return { ok: false, error: 'bbox min must be less than max' };
  return { ok: true, value: { minLon, minLat, maxLon, maxLat } };
}

function isLonLat(p) {
  return Array.isArray(p) && p.length === 2 && p.every(Number.isFinite)
    && p[0] >= -180 && p[0] <= 180 && p[1] >= -90 && p[1] <= 90;
}

/** Validates the POST /v1/route body. Returns {ok, errors}. */
function validateRouteRequest(body, validateVehicle) {
  const errors = [];
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { ok: false, errors: ['body must be a JSON object'] };
  if (!isLonLat(body.from)) errors.push('from must be [lon, lat]');
  if (!isLonLat(body.to)) errors.push('to must be [lon, lat]');
  if (!validateVehicle(body.vehicle)) {
    for (const e of validateVehicle.errors || []) errors.push(`vehicle${e.instancePath} ${e.message}`);
  }
  return { ok: errors.length === 0, errors };
}

// Valhalla truck costing (3.9 API reference, "Truck options"): roads tagged without HGV access are
// effectively forbidden at hgv_no_access_penalty >= 43200 s (below that they become allowed with a
// penalty). We pin it explicitly so a changed upstream default cannot silently open such roads (ADR-0013).
const HGV_NO_ACCESS_PENALTY_S = 43200;

/**
 * Maps a TrucksIL vehicle profile to Valhalla costing_options.truck (metres, metric tonnes).
 * Every profile field that Valhalla understands is passed; Valhalla defaults (e.g. axle_load 9.07 t,
 * axle_count 5) are never relied on for a field the driver did not give, except where noted:
 *   heightM->height, widthM->width, lengthM->length, grossWeightT->weight, axleLoadT->axle_load,
 *   axleCount->axle_count, hazmat{...}->hazmat:true. hazmat.adrTunnelCode is NOT sent: stock Valhalla has
 *   no tunnel categories (it folds hazmat:A..E tags into one boolean); routing.js checks it (ADR-0013).
 * profileName/note are labels only.
 */
function vehicleToTruckCosting(v) {
  const truck = {
    height: v.heightM,
    width: v.widthM,
    length: v.lengthM,
    weight: v.grossWeightT,
    hgv_no_access_penalty: HGV_NO_ACCESS_PENALTY_S,
  };
  if (v.axleLoadT !== undefined) truck.axle_load = v.axleLoadT;
  if (v.axleCount !== undefined) truck.axle_count = v.axleCount;
  if (v.hazmat) truck.hazmat = true;
  return truck;
}

// Narrative languages offered by the PWA (Valhalla locales/: he-IL, ru-RU, ar-SA, en-US exist).
// Anything else -> en-US. Only affects instruction text, never costing.
const NARRATIVE_LANGUAGES = ['en-US', 'he-IL', 'ru-RU', 'ar-SA'];

function buildValhallaRouteRequest({ from, to, vehicle, language }) {
  return {
    locations: [
      { lon: from[0], lat: from[1] },
      { lon: to[0], lat: to[1] },
    ],
    costing: 'truck',
    costing_options: { truck: vehicleToTruckCosting(vehicle) },
    units: 'kilometers',
    language: NARRATIVE_LANGUAGES.includes(language) ? language : 'en-US',
  };
}

module.exports = {
  TRUCKSIL_NOTICE,
  loadVehicleValidator,
  parseBbox,
  validateRouteRequest,
  HGV_NO_ACCESS_PENALTY_S,
  vehicleToTruckCosting,
  buildValhallaRouteRequest,
  NARRATIVE_LANGUAGES,
};
