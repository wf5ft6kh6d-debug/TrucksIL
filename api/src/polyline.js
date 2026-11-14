'use strict';
// CommonJS entry for the API. The implementation lives in polyline.mjs so the web client can
// import the same code (no copy). Requires Node >= 22.12 (require of ES modules).
const { decodePolyline, encodePolyline, routeShape } = require('./polyline.mjs');

module.exports = { decodePolyline, encodePolyline, routeShape };
