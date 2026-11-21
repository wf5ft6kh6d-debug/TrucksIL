// Last successful route, kept on this device only, for viewing when the network is gone.
// It is NEVER treated as a valid route: the view model is flagged stale and the UI shows
// "offline: route from <time>, restrictions may be outdated" (ADR-0002, ADR-0015). It is not a
// GPS track: only the planned route the user asked for.
export const LAST_ROUTE_KEY = 'trucksil.lastRoute.v1';

export function saveLastRoute(storage, request, body, now = Date.now()) {
  try { storage.setItem(LAST_ROUTE_KEY, JSON.stringify({ savedAt: now, to: request && request.to, body })); return true; } catch { return false; }
}

export function loadLastRoute(storage) {
  try {
    const v = JSON.parse(storage.getItem(LAST_ROUTE_KEY));
    return v && Number.isFinite(v.savedAt) && v.body && typeof v.body === 'object' ? v : null;
  } catch { return null; }
}

export function clearLastRoute(storage) { try { storage.removeItem(LAST_ROUTE_KEY); } catch { /* ignore */ } }

/** Marks a route view model as an offline, possibly outdated copy. */
export function staleViewModel(vm, savedAt) {
  return vm && vm.kind === 'route' ? { ...vm, stale: { savedAt } } : vm;
}

/** Local time label for the offline notice, e.g. "21.11 14:05". */
export function formatSavedAt(savedAt, locale) {
  try {
    return new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(savedAt));
  } catch { return new Date(savedAt).toISOString(); }
}
