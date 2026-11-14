// Shared ESM source (used by the API via require(esm), Node >= 22.12, and by web/ via Vite).
// Decoder for Valhalla's encoded polyline (Google algorithm, precision 1e6 = "polyline6").
// Returns [[lon, lat], ...] (GeoJSON order), whereas the encoding stores lat first.

export function decodePolyline(str, precision = 6) {
  if (typeof str !== 'string') throw new TypeError('polyline must be a string');
  const factor = 10 ** precision;
  const coords = [];
  let index = 0;
  let lat = 0;
  let lon = 0;
  const next = () => {
    let result = 0;
    let shift = 0;
    let b;
    do {
      if (index >= str.length) throw new Error('truncated polyline');
      b = str.charCodeAt(index++) - 63;
      if (b < 0 || b > 63) throw new Error('invalid polyline character');
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    return result & 1 ? ~(result >>> 1) : result >>> 1;
  };
  while (index < str.length) {
    lat += next();
    lon += next();
    coords.push([lon / factor, lat / factor]);
  }
  return coords;
}

/** Encoder (used by tests and dev tooling). Input [[lon, lat], ...]. */
export function encodePolyline(coords, precision = 6) {
  const factor = 10 ** precision;
  let out = '';
  let pLat = 0;
  let pLon = 0;
  const enc = (v) => {
    let n = v < 0 ? ~(v << 1) : v << 1;
    while (n >= 0x20) { out += String.fromCharCode((0x20 | (n & 0x1f)) + 63); n >>>= 5; }
    out += String.fromCharCode(n + 63);
  };
  for (const [lon, lat] of coords) {
    const la = Math.round(lat * factor);
    const lo = Math.round(lon * factor);
    enc(la - pLat); enc(lo - pLon);
    pLat = la; pLon = lo;
  }
  return out;
}

/** Concatenates the decoded shapes of all legs of a Valhalla /route response. */
export function routeShape(valhallaResult) {
  const legs = valhallaResult && valhallaResult.trip && Array.isArray(valhallaResult.trip.legs) ? valhallaResult.trip.legs : [];
  const coords = [];
  for (const leg of legs) if (typeof leg.shape === 'string') coords.push(...decodePolyline(leg.shape, 6));
  return coords;
}

