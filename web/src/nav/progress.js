// Route model for navigation + progress along it. Pure (no DOM, no timers).
// Uses the Valhalla maneuvers already in the /v1/route response (trip.legs[].maneuvers):
// begin_shape_index is relative to the leg's own shape, so legs are offset as routeShape()
// concatenates them.
import { decodePolyline } from '../../../api/src/polyline.mjs';
import { cumulative, snapToRoute } from './geo.js';

const str = (v) => (typeof v === 'string' && v.trim() ? v : null);

/**
 * @param {object} body  200 body of POST /v1/route
 * @param {object} [vm]  routeViewModel() of the same body (for TrucksIL warnings)
 * @returns {object|null} null when the body has no usable shape
 */
export function buildNavRoute(body, vm = null) {
  const legs = body && body.trip && Array.isArray(body.trip.legs) ? body.trip.legs : [];
  const coords = [];
  const maneuvers = [];
  for (const leg of legs) {
    if (typeof leg.shape !== 'string') continue;
    let shape;
    try { shape = decodePolyline(leg.shape, 6); } catch { return null; }
    const offset = coords.length;
    coords.push(...shape);
    for (const m of Array.isArray(leg.maneuvers) ? leg.maneuvers : []) {
      const b = Number.isInteger(m.begin_shape_index) ? m.begin_shape_index : null;
      if (b === null || b < 0 || b >= shape.length) continue;
      maneuvers.push({
        shapeIndex: offset + b,
        type: Number.isInteger(m.type) ? m.type : null,
        instruction: str(m.instruction),
        verbalAlert: str(m.verbal_transition_alert_instruction),
        verbalPre: str(m.verbal_pre_transition_instruction) || str(m.instruction),
        verbalPost: str(m.verbal_post_transition_instruction),
      });
    }
  }
  if (coords.length < 2) return null;
  const cum = cumulative(coords);
  for (const m of maneuvers) m.alongM = cum[m.shapeIndex];
  maneuvers.sort((a, b) => a.alongM - b.alongM);
  return { coords, cum, lengthM: cum[cum.length - 1], maneuvers, warnings: vm ? routeWarnings(coords, cum, vm) : [] };
}

/**
 * TrucksIL warnings placed along the route: avoided restrictions that lie near the line
 * (the route goes past them, the vehicle must not turn there) and bridges/tunnels without data.
 */
export function routeWarnings(coords, cum, vm, { nearM = 300 } = {}) {
  const out = [];
  for (const it of vm.avoided || []) {
    if (!it.position) continue;
    const s = snapToRoute(coords, cum, it.position);
    if (s && s.distanceM <= nearM) out.push({ id: `avoided:${it.id}`, kind: 'avoided', alongM: s.alongM, typeKey: it.typeKey, valueText: it.valueText });
  }
  const segs = vm.structures ? vm.structures.noData : [];
  segs.forEach((seg, i) => {
    const s = snapToRoute(coords, cum, seg.coordinates[0]);
    if (s && s.distanceM <= 50) out.push({ id: `nodata:${seg.wayId ?? i}`, kind: 'noData', alongM: s.alongM, structure: seg.type });
  });
  return out.sort((a, b) => a.alongM - b.alongM);
}

/**
 * Progress at a snapped position.
 * @returns {{alongM:number, remainingM:number, nextIndex:number|null, distanceToNextM:number|null, arrived:boolean}}
 * nextIndex is the first maneuver strictly ahead (start maneuver excluded once moving).
 */
export function progressAt(nav, alongM, { arriveM = 30 } = {}) {
  const remainingM = Math.max(0, nav.lengthM - alongM);
  let nextIndex = null;
  for (let i = 0; i < nav.maneuvers.length; i += 1) {
    if (nav.maneuvers[i].alongM > alongM + 1) { nextIndex = i; break; }
  }
  return {
    alongM,
    remainingM,
    nextIndex,
    distanceToNextM: nextIndex === null ? null : nav.maneuvers[nextIndex].alongM - alongM,
    arrived: remainingM <= arriveM,
  };
}
