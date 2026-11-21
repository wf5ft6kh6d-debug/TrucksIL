// When to speak what. Pure: give it progress + speed, it returns the announcements due now and
// remembers what was already said (each maneuver stage and each warning once per route).
// Distances (m) scale with speed so a truck at 90 km/h gets the alert ~40 s ahead.
export const STAGES = ['alert', 'pre', 'post'];

export function thresholds(speedMps) {
  const v = Number.isFinite(speedMps) && speedMps > 0 ? speedMps : 0;
  return {
    alertM: Math.max(400, v * 40), // "In 500 metres, turn right" (verbal_transition_alert_instruction)
    preM: Math.max(60, v * 8), // "Turn right onto ..." (verbal_pre_transition_instruction)
    warnM: Math.max(400, v * 30), // TrucksIL warnings
  };
}

export function createAnnouncer() {
  const said = new Set();
  return {
    /**
     * @param {object} nav       buildNavRoute()
     * @param {object} progress  progressAt()
     * @param {number} speedMps
     * @returns {Array<{id:string, kind:'maneuver'|'warning', stage?:string, text?:string, warning?:object}>}
     */
    due(nav, progress, speedMps) {
      const out = [];
      const th = thresholds(speedMps);
      const i = progress.nextIndex;
      // After passing a maneuver, its post-transition text ("Continue for 2 km") once.
      const prevIdx = i === null ? nav.maneuvers.length - 1 : i - 1;
      if (prevIdx >= 0 && progress.alongM > 0) {
        const m = nav.maneuvers[prevIdx];
        const id = `${prevIdx}:post`;
        if (m.verbalPost && !said.has(id) && said.has(`${prevIdx}:pre`)) { said.add(id); out.push({ id, kind: 'maneuver', stage: 'post', text: m.verbalPost }); }
      }
      if (i !== null) {
        const m = nav.maneuvers[i];
        const d = progress.distanceToNextM;
        if (d <= th.preM) {
          const id = `${i}:pre`;
          if (!said.has(id)) { said.add(id); said.add(`${i}:alert`); if (m.verbalPre) out.push({ id, kind: 'maneuver', stage: 'pre', text: m.verbalPre }); }
        } else if (d <= th.alertM) {
          const id = `${i}:alert`;
          if (!said.has(id)) { said.add(id); if (m.verbalAlert) out.push({ id, kind: 'maneuver', stage: 'alert', text: m.verbalAlert }); }
        }
      }
      for (const w of nav.warnings) {
        const ahead = w.alongM - progress.alongM;
        if (ahead >= -20 && ahead <= th.warnM && !said.has(w.id)) { said.add(w.id); out.push({ id: w.id, kind: 'warning', warning: { ...w, aheadM: Math.max(0, ahead) } }); }
      }
      // Warnings first: they are about safety, instructions are about convenience.
      return out.sort((a, b) => (a.kind === b.kind ? 0 : a.kind === 'warning' ? -1 : 1));
    },
    markSaid(id) { said.add(id); },
    has(id) { return said.has(id); },
  };
}

/** Rounded distance for display/speech: <100 m to 10 m, <1 km to 50 m, else km with 1 decimal. */
export function distanceParams(m) {
  const d = Math.max(0, Number(m) || 0);
  if (d < 100) return { key: 'unit.m', n: Math.round(d / 10) * 10 };
  if (d < 1000) return { key: 'unit.m', n: Math.round(d / 50) * 50 };
  return { key: 'unit.km', n: (d / 1000).toFixed(1) };
}

/** Text of a TrucksIL warning in the UI language. tr = (key, params) => string (i18n t bound to lang). */
export function warningText(tr, w) {
  const dp = distanceParams(w.aheadM);
  const dist = tr(dp.key, { n: dp.n });
  if (w.kind === 'avoided') return tr('warn.avoided', { type: tr(w.typeKey), value: w.valueText ?? '', dist });
  return tr('warn.noData', { structure: tr(w.structure === 'tunnel' ? 'warn.tunnel' : 'warn.bridge'), dist });
}
