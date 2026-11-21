'use strict';
// Local (metre-scale) geometry for route checks, done in JS on the decoded route shape (ADR-0011):
//  - direction: does the route traverse a LineString restriction in its digitized (forward) direction?
//  - thin exclusion: small rectangles around the ROUTE sub-line that passes a restriction, so Valhalla
//    excludes only the edge actually used instead of everything within 20 m (crossing roads, the
//    opposite carriageway).
// Projection: equirectangular around the restriction's latitude. Errors are well below a metre over the
// ~100 m neighbourhood used here; distances along the whole route are only used to locate that window.

const R = 6371008.8;
const rad = (d) => (d * Math.PI) / 180;
const deg = (r) => (r * 180) / Math.PI;

const DIRECTION_WINDOW_M = 15; // route bearing taken over +-15 m around the closest point
const MIN_BEARING_LEN_M = 5; // shorter than this -> direction undetermined -> apply (conservative)
const SAME_DIRECTION_DEG = 60; // within +-60 deg = same direction; within 60 deg of opposite = backward
const THIN_HALF_WIDTH_M = 7; // half-width of the rectangle around the route edge
const THIN_ALONG_M = 30; // route sub-line taken +-30 m along the route from the closest point

function projector(lat0) {
  const k = Math.cos(rad(lat0));
  return {
    xy: ([lon, lat]) => [rad(lon) * k * R, rad(lat) * R],
    ll: ([x, y]) => [+deg(x / (k * R)).toFixed(7), +deg(y / R).toFixed(7)],
  };
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const cross = (a, b) => a[0] * b[1] - a[1] * b[0];
const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** Closest point on segment AB to P: {t, q, d}. */
function projectOnSegment(P, A, B) {
  const AB = sub(B, A);
  const L = dot(AB, AB);
  const t = L ? Math.max(0, Math.min(1, dot(sub(P, A), AB) / L)) : 0;
  const q = lerp(A, B, t);
  return { t, q, d: dist(P, q) };
}

/** Closest pair between route segment AB and restriction segment CD: {t (on AB), d}. */
function segmentPair(A, B, C, D) {
  const r = sub(B, A);
  const s = sub(D, C);
  const den = cross(r, s);
  if (den !== 0) {
    const t = cross(sub(C, A), s) / den;
    const u = cross(sub(C, A), r) / den;
    if (t >= 0 && t <= 1 && u >= 0 && u <= 1) return { t, d: 0 };
  }
  const c1 = projectOnSegment(C, A, B);
  const c2 = projectOnSegment(D, A, B);
  const a1 = projectOnSegment(A, C, D);
  const a2 = projectOnSegment(B, C, D);
  let best = c1.d <= c2.d ? { t: c1.t, d: c1.d } : { t: c2.t, d: c2.d };
  if (a1.d < best.d) best = { t: 0, d: a1.d };
  if (a2.d < best.d) best = { t: 1, d: a2.d };
  return best;
}

function geometryParts(geometry) {
  if (!geometry || typeof geometry !== 'object' || !Array.isArray(geometry.coordinates)) return null;
  if (geometry.type === 'Point') return { type: 'Point', coords: [geometry.coordinates] };
  if (geometry.type === 'LineString' && geometry.coordinates.length >= 1) return { type: 'LineString', coords: geometry.coordinates };
  return null;
}

/**
 * Locates a restriction geometry on the route.
 * @returns {null | {proj, pts, cum, along, distM, restrSeg}} pts = route in metres, cum = cumulative length,
 *   along = distance along the route of the closest point, restrSeg = [C, D] of the restriction (LineString only).
 */
function locate(shape, geometry) {
  const g = geometryParts(geometry);
  if (!g || !Array.isArray(shape) || shape.length === 0) return null;
  const proj = projector(g.coords[0][1]);
  const pts = shape.map(proj.xy);
  const cum = [0];
  for (let i = 1; i < pts.length; i += 1) cum.push(cum[i - 1] + dist(pts[i - 1], pts[i]));
  const rp = g.coords.map(proj.xy);
  const restrSegs = rp.length === 1 ? [[rp[0], rp[0]]] : rp.slice(1).map((p, j) => [rp[j], p]);
  let best = { d: Infinity, along: 0, seg: null };
  const routeSegs = Math.max(pts.length - 1, 1);
  for (let i = 0; i < routeSegs; i += 1) {
    const A = pts[i];
    const B = pts[Math.min(i + 1, pts.length - 1)];
    for (const [C, D] of restrSegs) {
      const { t, d } = segmentPair(A, B, C, D);
      if (d < best.d) best = { d, along: cum[i] + t * dist(A, B), seg: [C, D] };
    }
  }
  return { proj, pts, cum, along: best.along, distM: best.d, restrSeg: g.type === 'LineString' ? best.seg : null };
}

/** Point at distance s along the projected route (clamped). */
function pointAt(pts, cum, s) {
  if (pts.length === 1) return pts[0];
  const total = cum[cum.length - 1];
  const x = Math.max(0, Math.min(total, s));
  let i = 1;
  while (i < cum.length - 1 && cum[i] < x) i += 1;
  const len = cum[i] - cum[i - 1];
  return lerp(pts[i - 1], pts[i], len ? (x - cum[i - 1]) / len : 0);
}

/** Route vertices strictly between s0 and s1, plus interpolated end points. */
function subLine(pts, cum, s0, s1) {
  const out = [pointAt(pts, cum, s0)];
  for (let i = 0; i < pts.length; i += 1) if (cum[i] > s0 && cum[i] < s1) out.push(pts[i]);
  out.push(pointAt(pts, cum, s1));
  return out;
}

const bearingOf = (a, b) => (deg(Math.atan2(b[0] - a[0], b[1] - a[1])) + 360) % 360;
const angleDiff = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };

/**
 * Angle (0..180) between the route's travel direction near the restriction and the restriction's
 * digitization direction, or null when it cannot be determined (not a LineString, degenerate geometry,
 * route too short around the point).
 */
function travelAngle(shape, geometry) {
  const loc = locate(shape, geometry);
  if (!loc || !loc.restrSeg) return null;
  const [C, D] = loc.restrSeg;
  if (dist(C, D) < 0.5) return null;
  const a = pointAt(loc.pts, loc.cum, loc.along - DIRECTION_WINDOW_M);
  const b = pointAt(loc.pts, loc.cum, loc.along + DIRECTION_WINDOW_M);
  if (dist(a, b) < MIN_BEARING_LEN_M) return null;
  return angleDiff(bearingOf(a, b), bearingOf(C, D));
}

/**
 * True if a restriction row applies to this route given its `direction`.
 * 'both', missing direction, Points and undeterminable geometry -> true (conservative).
 */
function directionApplies(row, shape) {
  const dir = row && row.direction;
  if (dir !== 'forward' && dir !== 'backward') return true;
  const angle = travelAngle(shape, row.geometry);
  if (angle === null) return true;
  return dir === 'forward' ? angle <= SAME_DIRECTION_DEG : angle >= 180 - SAME_DIRECTION_DEG;
}

/** Douglas-Peucker in metres. */
function simplify(points, tol) {
  if (points.length <= 2) return points;
  const [A, B] = [points[0], points[points.length - 1]];
  let idx = -1;
  let dmax = 0;
  for (let i = 1; i < points.length - 1; i += 1) {
    const d = projectOnSegment(points[i], A, B).d;
    if (d > dmax) { dmax = d; idx = i; }
  }
  if (dmax <= tol) return [A, B];
  return [...simplify(points.slice(0, idx + 1), tol).slice(0, -1), ...simplify(points.slice(idx), tol)];
}

/**
 * Thin exclusion around the route edge that passes `geometry`: one rectangle per (simplified) segment of
 * the route sub-line within +-alongM of the closest point, widened by halfWidthM on each side and at
 * both ends (so consecutive rectangles overlap at bends). Returns closed [lon,lat] rings, or null when
 * it cannot be built (no geometry/shape, or a zero-length sub-line) -> caller falls back to the wide
 * polygon around the restriction.
 */
function thinExclusionRings(shape, geometry, { halfWidthM = THIN_HALF_WIDTH_M, alongM = THIN_ALONG_M } = {}) {
  const loc = locate(shape, geometry);
  if (!loc) return null;
  const line = simplify(subLine(loc.pts, loc.cum, loc.along - alongM, loc.along + alongM), 1);
  const rings = [];
  for (let i = 1; i < line.length; i += 1) {
    const [A, B] = [line[i - 1], line[i]];
    const L = dist(A, B);
    if (L < 0.01) continue;
    const u = [(B[0] - A[0]) / L, (B[1] - A[1]) / L];
    const n = [-u[1], u[0]];
    const w = halfWidthM;
    const A2 = [A[0] - u[0] * w, A[1] - u[1] * w];
    const B2 = [B[0] + u[0] * w, B[1] + u[1] * w];
    const corner = (P, side) => [P[0] + n[0] * w * side, P[1] + n[1] * w * side];
    const ring = [corner(A2, 1), corner(B2, 1), corner(B2, -1), corner(A2, -1)].map(loc.proj.ll);
    ring.push(ring[0]);
    rings.push(ring);
  }
  return rings.length ? rings : null;
}

module.exports = {
  DIRECTION_WINDOW_M, MIN_BEARING_LEN_M, SAME_DIRECTION_DEG, THIN_HALF_WIDTH_M, THIN_ALONG_M,
  locate, travelAngle, directionApplies, thinExclusionRings, projector,
};
