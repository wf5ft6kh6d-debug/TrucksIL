// Web-mercator tile indices covering a route, for warming the offline tile cache.
const RAD = Math.PI / 180;

export function lonLatToTile(lon, lat, z) {
  const n = 2 ** z;
  const x = Math.floor(((lon + 180) / 360) * n);
  const s = Math.sin(lat * RAD);
  const y = Math.floor((0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n);
  return { z, x: Math.min(n - 1, Math.max(0, x)), y: Math.min(n - 1, Math.max(0, y)) };
}

/**
 * Tiles touched by the route at each zoom, plus `buffer` neighbouring tiles each side.
 * Densifies long segments so no tile on the line is skipped. Capped at maxTiles (lowest zooms first).
 */
export function tilesAlongRoute(coords, zooms = [8, 10, 12, 14], { buffer = 1, maxTiles = 800 } = {}) {
  const out = [];
  const seen = new Set();
  for (const z of [...zooms].sort((a, b) => a - b)) {
    const stepDeg = 360 / 2 ** z / 4; // quarter tile width
    const add = (lon, lat) => {
      const c = lonLatToTile(lon, lat, z);
      for (let dx = -buffer; dx <= buffer; dx += 1) {
        for (let dy = -buffer; dy <= buffer; dy += 1) {
          const n = 2 ** z;
          const x = c.x + dx; const y = c.y + dy;
          if (x < 0 || y < 0 || x >= n || y >= n) continue;
          const k = `${z}/${x}/${y}`;
          if (seen.has(k)) continue;
          seen.add(k);
          out.push({ z, x, y });
          if (out.length >= maxTiles) return true;
        }
      }
      return false;
    };
    for (let i = 0; i < coords.length; i += 1) {
      const a = coords[i];
      if (add(a[0], a[1])) return out;
      const b = coords[i + 1];
      if (!b) continue;
      const steps = Math.ceil(Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])) / stepDeg);
      for (let s = 1; s < steps; s += 1) if (add(a[0] + ((b[0] - a[0]) * s) / steps, a[1] + ((b[1] - a[1]) * s) / steps)) return out;
    }
  }
  return out;
}
