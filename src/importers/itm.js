'use strict';
// Israeli Transverse Mercator (EPSG:2039, Israel 1993 / GRS80) -> WGS84.
// Inverse TM (Snyder series) on GRS80, then 7-parameter Helmert (EPSG:1073-style
// towgs84 as used by PROJ: -24.0024,-17.1032,-17.8444,-0.33077,-1.85269,1.66969,5.4248).
// Accuracy is well under a metre for Israel, sufficient for snapping bridges.
const D2R = Math.PI / 180;
const A = 6378137.0, F = 1 / 298.257222101; // GRS80
const WGS_A = 6378137.0, WGS_F = 1 / 298.257223563;
const LAT0 = (31 + 44 / 60 + 3.817 / 3600) * D2R;
const LON0 = (35 + 12 / 60 + 16.261 / 3600) * D2R;
const K0 = 1.0000067, FE = 219529.584, FN = 626907.39;
const TOWGS84 = [-24.0024, -17.1032, -17.8444, -0.33077, -1.85269, 1.66969, 5.4248];

function meridianArc(phi, a, e2) {
  const e4 = e2 * e2, e6 = e4 * e2;
  return a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
    - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * Math.sin(2 * phi)
    + (15 * e4 / 256 + 45 * e6 / 1024) * Math.sin(4 * phi)
    - (35 * e6 / 3072) * Math.sin(6 * phi));
}

function inverseTM(x, y) {
  const e2 = 2 * F - F * F, ep2 = e2 / (1 - e2);
  const M = meridianArc(LAT0, A, e2) + (y - FN) / K0;
  const mu = M / (A * (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256));
  const e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
  const phi1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu)
    + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
    + (151 * e1 ** 3 / 96) * Math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
  const s = Math.sin(phi1), c = Math.cos(phi1), t = Math.tan(phi1);
  const C1 = ep2 * c * c, T1 = t * t;
  const N1 = A / Math.sqrt(1 - e2 * s * s);
  const R1 = A * (1 - e2) / Math.pow(1 - e2 * s * s, 1.5);
  const D = (x - FE) / (N1 * K0);
  const lat = phi1 - (N1 * t / R1) * (D * D / 2
    - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * D ** 4 / 24
    + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep2 - 3 * C1 * C1) * D ** 6 / 720);
  const lon = LON0 + (D - (1 + 2 * T1 + C1) * D ** 3 / 6
    + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep2 + 24 * T1 * T1) * D ** 5 / 120) / c;
  return [lat, lon];
}

function geodeticToEcef(lat, lon, a, f) {
  const e2 = 2 * f - f * f, N = a / Math.sqrt(1 - e2 * Math.sin(lat) ** 2);
  return [N * Math.cos(lat) * Math.cos(lon), N * Math.cos(lat) * Math.sin(lon), N * (1 - e2) * Math.sin(lat)];
}

function ecefToGeodetic(X, Y, Z, a, f) {
  const e2 = 2 * f - f * f, p = Math.hypot(X, Y), lon = Math.atan2(Y, X);
  let lat = Math.atan2(Z, p * (1 - e2));
  for (let i = 0; i < 10; i++) {
    const N = a / Math.sqrt(1 - e2 * Math.sin(lat) ** 2);
    const h = p / Math.cos(lat) - N;
    lat = Math.atan2(Z, p * (1 - e2 * N / (N + h)));
  }
  return [lat, lon];
}

/** Convert ITM easting/northing (m) to WGS84 [lon, lat] in degrees. */
function itmToWgs84(x, y) {
  const [lat, lon] = inverseTM(x, y);
  const [X, Y, Z] = geodeticToEcef(lat, lon, A, F);
  const [dx, dy, dz, rxs, rys, rzs, ppm] = TOWGS84;
  const rx = rxs / 3600 * D2R, ry = rys / 3600 * D2R, rz = rzs / 3600 * D2R, m = 1 + ppm * 1e-6;
  // Position-vector convention (PROJ towgs84)
  const X2 = dx + m * (X - rz * Y + ry * Z);
  const Y2 = dy + m * (rz * X + Y - rx * Z);
  const Z2 = dz + m * (-ry * X + rx * Y + Z);
  const [lat2, lon2] = ecefToGeodetic(X2, Y2, Z2, WGS_A, WGS_F);
  return [lon2 / D2R, lat2 / D2R];
}

module.exports = { itmToWgs84 };
