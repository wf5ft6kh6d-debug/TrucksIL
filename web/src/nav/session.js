// One navigation run over one route: GPS fix in -> snapped position, progress, off-route state
// and the announcements due. Pure: no timers, DOM, network or storage; time comes with the fix.
import { snapToRoute } from './geo.js';
import { progressAt } from './progress.js';
import { createOffRouteDetector } from './offRoute.js';
import { createAnnouncer } from './announce.js';

export function createNavSession(nav, opts = {}) {
  const detector = createOffRouteDetector(opts.offRoute);
  const announcer = createAnnouncer();
  let alongM = null;
  let last = null; // {alongM, t} for speed estimation
  let arrived = false;
  return {
    nav,
    get alongM() { return alongM; },
    /** Announcement for the start: the first maneuver ("Drive north on ..."). */
    start() {
      const m = nav.maneuvers[0];
      if (!m) return [];
      announcer.markSaid('0:alert');
      announcer.markSaid('0:pre');
      return m.verbalPre ? [{ id: '0:pre', kind: 'maneuver', stage: 'pre', text: m.verbalPre }] : [];
    },
    /** @param {{coords:number[], accuracyM?:number, speedMps?:number|null, t:number}} fix */
    update(fix) {
      const snap = snapToRoute(nav.coords, nav.cum, fix.coords, { prevAlongM: alongM });
      const off = detector.update({ distanceM: snap ? snap.distanceM : Infinity, accuracyM: fix.accuracyM, t: fix.t });
      if (snap && off.state !== 'off' && !off.ignored) alongM = alongM === null ? snap.alongM : Math.max(alongM - 50, snap.alongM);
      let speed = Number.isFinite(fix.speedMps) && fix.speedMps >= 0 ? fix.speedMps : null;
      if (speed === null && last && alongM !== null && fix.t > last.t) speed = Math.max(0, (alongM - last.alongM) / ((fix.t - last.t) / 1000));
      if (alongM !== null) last = { alongM, t: fix.t };
      const progress = alongM === null ? null : progressAt(nav, alongM);
      const announcements = progress && off.state === 'on' && !arrived ? announcer.due(nav, progress, speed ?? 0) : [];
      const justArrived = Boolean(progress && progress.arrived && off.state === 'on' && !arrived);
      if (justArrived) arrived = true;
      return { snap, progress, offRoute: off, speedMps: speed, announcements, arrived, justArrived };
    },
  };
}
