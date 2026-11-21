// Thin fetch wrapper. Same-origin /api (proxied to the API by nginx or the Vite dev server).
export const API_BASE = '/api';

// language: Valhalla narrative language (he-IL/ru-RU/ar-SA/en-US); the API falls back to en-US.
export async function requestRoute({ from, to, vehicle, language }, fetchImpl = globalThis.fetch) {
  let res;
  try {
    res = await fetchImpl(`${API_BASE}/v1/route`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(language ? { from, to, vehicle, language } : { from, to, vehicle }),
    });
  } catch {
    return { status: null, body: null };
  }
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  return { status: res.status, body };
}
