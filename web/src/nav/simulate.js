// Desk-testing: replays the route shape as fake GPS fixes at a given speed. Pure generator;
// the page drives it with a timer. Optional lateral offset puts the "vehicle" off the line
// (to exercise off-route detection without leaving the desk).
import { pointAt } from './geo.js';

/**
 * @param {object} nav   buildNavRoute()
 * @param {object} o
 * @param {number} o.speedKmh
 * @param {number} [o.stepMs=1000]   simulated time between fixes
 * @param {number} [o.offsetM=0]     shift north by this many metres (0 = on the line)
 * @param {number} [o.accuracyM=5]
 */
export function* simulateFixes(nav, { speedKmh, stepMs = 1000, offsetM = 0, accuracyM = 5, startMs = 0 } = {}) {
  const v = Math.max(1, Number(speedKmh) || 50) / 3.6;
  const dLat = offsetM / 111320;
  for (let t = 0, along = 0; ; t += stepMs, along += (v * stepMs) / 1000) {
    const p = pointAt(nav.coords, nav.cum, Math.min(along, nav.lengthM));
    yield { coords: [p[0], p[1] + dLat], accuracyM, speedMps: v, t: startMs + t, simulated: true };
    if (along >= nav.lengthM) return;
  }
}
