'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  loadVehicleValidator, parseBbox, validateRouteRequest, vehicleToTruckCosting, buildValhallaRouteRequest,
} = require('../../api/src/lib');

// Fictional profile, not a real vehicle.
const truck = { profileName: 'Test semi', heightM: 4.0, widthM: 2.55, lengthM: 16.5, grossWeightT: 40, axleLoadT: 11.5 };
const validate = loadVehicleValidator();

test('vehicle validation accepts a valid profile', () => {
  assert.ok(validate(truck), JSON.stringify(validate.errors));
});

test('vehicle validation rejects missing, out-of-range and unknown fields', () => {
  assert.equal(validate({ ...truck, heightM: undefined }), false);
  assert.equal(validate({ ...truck, heightM: 9 }), false);
  assert.equal(validate({ ...truck, colour: 'red' }), false);
  assert.equal(validate(undefined), false);
});

test('route request validation', () => {
  assert.deepEqual(validateRouteRequest({ from: [34.78, 32.08], to: [35.21, 31.77], vehicle: truck }, validate), { ok: true, errors: [] });
  const bad = validateRouteRequest({ from: [34.78], to: [200, 31], vehicle: { ...truck, widthM: 0 } }, validate);
  assert.equal(bad.ok, false);
  assert.ok(bad.errors.includes('from must be [lon, lat]'));
  assert.ok(bad.errors.includes('to must be [lon, lat]'));
  assert.ok(bad.errors.some((e) => e.startsWith('vehicle/widthM')));
  assert.equal(validateRouteRequest(null, validate).ok, false);
  assert.equal(validateRouteRequest([], validate).ok, false);
});

test('vehicle maps to Valhalla truck costing', () => {
  assert.deepEqual(vehicleToTruckCosting(truck), { height: 4.0, width: 2.55, length: 16.5, weight: 40, axle_load: 11.5 });
  const { axleLoadT, ...noAxle } = truck;
  assert.equal('axle_load' in vehicleToTruckCosting(noAxle), false);
  assert.equal(vehicleToTruckCosting({ ...truck, hazmat: { adrClasses: ['3'] } }).hazmat, true);
});

test('Valhalla route request uses lon/lat order and truck costing', () => {
  const r = buildValhallaRouteRequest({ from: [34.78, 32.08], to: [35.21, 31.77], vehicle: truck });
  assert.deepEqual(r.locations, [{ lon: 34.78, lat: 32.08 }, { lon: 35.21, lat: 31.77 }]);
  assert.equal(r.costing, 'truck');
  assert.equal(r.costing_options.truck.height, 4.0);
});

test('bbox parsing', () => {
  assert.deepEqual(parseBbox('34.2,29.4,35.9,33.4'), { ok: true, value: { minLon: 34.2, minLat: 29.4, maxLon: 35.9, maxLat: 33.4 } });
  for (const bad of [null, '', '1,2,3', '1,2,3,4,5', 'a,1,2,3', '1,,2,3', '35,30,34,31', '34,31,35,30', '-181,0,1,1', '0,0,1,91', 'Infinity,0,1,1']) {
    assert.equal(parseBbox(bad).ok, false, `expected ${bad} to be rejected`);
  }
});
