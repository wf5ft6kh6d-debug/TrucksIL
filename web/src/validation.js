// Vehicle profile validation in the browser with the SAME schema file the API uses
// (data/vehicle-profile.schema.json) and the same validator (ajv, draft 2020-12).
import Ajv2020 from 'ajv/dist/2020.js';

export const ADR_CLASSES = ['1', '2', '3', '4.1', '4.2', '4.3', '5.1', '5.2', '6.1', '6.2', '7', '8', '9'];
const NUMERIC = ['heightM', 'widthM', 'lengthM', 'grossWeightT', 'axleLoadT'];

export function createVehicleValidator(schema) {
  // Same options as api/src/lib.js loadVehicleValidator (formats are not used by this schema).
  const ajv = new Ajv2020({ allErrors: true, strict: true, strictTuples: false, allowUnionTypes: true });
  const validate = ajv.compile(schema);
  return function validateProfile(profile) {
    const ok = validate(profile);
    const errors = ok ? [] : (validate.errors || []).map((e) => ({
      field: e.instancePath.replace(/^\//, '').split('/')[0] || (e.params && e.params.missingProperty) || '',
      message: `${e.instancePath || '/'} ${e.message}`,
    }));
    return { ok, errors };
  };
}

/**
 * Converts raw form values (strings) to a profile object. Empty optional fields are omitted;
 * numbers accept "," as decimal separator. Unparseable numbers are kept as strings so the
 * schema reports them (never silently dropped or guessed).
 */
export function profileFromForm(raw) {
  const p = {};
  if (raw.profileName !== undefined && String(raw.profileName).trim() !== '') p.profileName = String(raw.profileName).trim();
  for (const k of NUMERIC) {
    const v = raw[k] === undefined || raw[k] === null ? '' : String(raw[k]).trim();
    if (v === '') continue;
    const n = Number(v.replace(',', '.'));
    p[k] = Number.isFinite(n) ? n : v;
  }
  const classes = Array.isArray(raw.adrClasses) ? raw.adrClasses : [];
  if (classes.length) p.hazmat = { adrClasses: [...classes] };
  if (raw.note !== undefined && String(raw.note).trim() !== '') p.note = String(raw.note);
  return p;
}

/** Parses "lon,lat" -> [lon, lat] or null. */
export function parseLonLat(text) {
  if (typeof text !== 'string') return null;
  const parts = text.split(',').map((s) => s.trim());
  if (parts.length !== 2 || parts.some((s) => s === '')) return null;
  const [lon, lat] = parts.map(Number);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return null;
  return [lon, lat];
}
