// Off-route detection: a state machine fed with snapped GPS fixes. Pure; time is passed in.
//   on       — on the route
//   suspect  — confidently further than thresholdM, for less than durationMs
//   off      — confidently off for >= durationMs (fires once; caller reroutes, then reset())
// "Confidently" = distance minus the fix's reported accuracy is above the threshold, so a
// 60 m error ellipse at 70 m from the line is not counted. Fixes worse than maxAccuracyM are
// ignored (they neither start nor clear the timer).
export function createOffRouteDetector({ thresholdM = 50, durationMs = 10000, maxAccuracyM = 100 } = {}) {
  let state = 'on';
  let since = null;
  return {
    get state() { return state; },
    /** @returns {{state:string, changed:boolean, fired:boolean, ignored?:boolean}} */
    update({ distanceM, accuracyM = 0, t }) {
      const prev = state;
      if (!Number.isFinite(distanceM) || !Number.isFinite(t)) return { state, changed: false, fired: false, ignored: true };
      const acc = Number.isFinite(accuracyM) && accuracyM > 0 ? accuracyM : 0;
      if (acc > maxAccuracyM) return { state, changed: false, fired: false, ignored: true };
      if (state === 'off') return { state, changed: false, fired: false };
      if (distanceM - acc > thresholdM) {
        if (since === null) since = t;
        state = t - since >= durationMs ? 'off' : 'suspect';
      } else if (distanceM <= thresholdM) {
        state = 'on';
        since = null;
      } // between: uncertain, keep the current state and timer
      return { state, changed: state !== prev, fired: state === 'off' && prev !== 'off' };
    },
    reset() { state = 'on'; since = null; },
  };
}

/** Allows an action at most once per minIntervalMs (reroute requests). */
export function createRateLimiter(minIntervalMs = 30000) {
  let last = -Infinity;
  return {
    tryAcquire(t) { if (t - last < minIntervalMs) return false; last = t; return true; },
    msUntilNext(t) { return Math.max(0, minIntervalMs - (t - last)); },
  };
}
