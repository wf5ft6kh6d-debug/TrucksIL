// Pure geometry helpers for in-browser navigation (no DOM). Coordinates are [lon, lat] (WGS84).
// Distances use a local equirectangular projection per segment: error < 0.1 % at Israel's
// latitudes for segments of a few km, which is far below GPS noise.
const R = 6371008.8;
const RAD = Math.PI / 180;

export function distanceM(a, b) {
  const dLat = (b[1] - a[1]) * RAD;
  const dLon = (b[0] - a[0]) * RAD;
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * RAD) * Math.cos(b[1] * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}

/** Cumulative distance (m) from the start to every vertex. */
export function cumulative(coords) {
  const cum = new Array(coords.length);
  let d = 0;
  for (let i = 0; i < coords.length; i += 1) {
    if (i > 0) d += distanceM(coords[i - 1], coords[i]);
    cum[i] = d;
  }
  return cum;
}

/** Closest point on segment a-b to p: { t (0..1), point, distanceM }. */
export function projectOnSegment(p, a, b) {
  const k = Math.cos(p[1] * RAD);
  const ax = a[0] * k; const ay = a[1];
  const bx = b[0] * k; const by = b[1];
  const px = p[0] * k; const py = p[1];
  const dx = bx - ax; const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = len2 > 0 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  const point = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  return { t, point, distanceM: distanceM(p, point) };
}

/**
 * Snaps a position to the route line.
 * @param {number[][]} coords route vertices
 * @param {number[]} cum      cumulative() of coords
 * @param {number[]} pos      [lon, lat]
 * @param {object} [o]
 * @param {number|null} [o.prevAlongM]  previous progress; segments ending more than backtrackM behind it
 *                                      are skipped so a route that passes the same road twice does not
 *                                      jump back (falls back to the whole route if nothing is near)
 * @returns {{segIndex:number, t:number, point:number[], distanceM:number, alongM:number}|null}
 */
export function snapToRoute(coords, cum, pos, { prevAlongM = null, backtrackM = 200, nearM = 100 } = {}) {
  if (!Array.isArray(coords) || coords.length < 2) return null;
  const search = (minAlong) => {
    let best = null;
    for (let i = 0; i < coords.length - 1; i += 1) {
      if (cum[i + 1] < minAlong) continue;
      const r = projectOnSegment(pos, coords[i], coords[i + 1]);
      if (!best || r.distanceM < best.distanceM) {
        best = { segIndex: i, t: r.t, point: r.point, distanceM: r.distanceM, alongM: cum[i] + (cum[i + 1] - cum[i]) * r.t };
      }
    }
    return best;
  };
  if (prevAlongM !== null && Number.isFinite(prevAlongM)) {
    const ahead = search(prevAlongM - backtrackM);
    if (ahead && ahead.distanceM <= nearM) return ahead;
  }
  return search(-Infinity);
}

/** Point at distance alongM from the start (clamped to the ends). */
export function pointAt(coords, cum, alongM) {
  if (!coords.length) return null;
  if (alongM <= 0) return coords[0].slice(0, 2);
  const total = cum[cum.length - 1];
  if (alongM >= total) return coords[coords.length - 1].slice(0, 2);
  let lo = 0; let hi = cum.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (cum[mid] <= alongM) lo = mid; else hi = mid; }
  const seg = cum[hi] - cum[lo];
  const t = seg > 0 ? (alongM - cum[lo]) / seg : 0;
  return [coords[lo][0] + (coords[hi][0] - coords[lo][0]) * t, coords[lo][1] + (coords[hi][1] - coords[lo][1]) * t];
}
