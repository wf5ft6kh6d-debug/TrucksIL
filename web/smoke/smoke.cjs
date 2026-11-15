'use strict';
// Playwright smoke test of the BUILT client (web/dist) with a mocked API. No network needed:
// /api/* is answered by this script and OSM tile requests are fulfilled with a blank tile.
//   cd web && npm run build && cd .. && npm run test:web-smoke [-- screenshot.png]
// Uses the preinstalled `playwright` package + chromium; does not download browsers.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const DIST = path.join(__dirname, '..', 'dist');
const shot = process.argv[2] || null;
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml', '.png': 'image/png' };

// polyline6 of [[34.78,32.08],[34.80,32.10],[34.82,32.12]] via the shared encoder.
async function fixtures() {
  const { encodePolyline } = await import('../../api/src/polyline.mjs');
  const low = { id: 'test-low-bridge', restrictionType: 'max_height', value: 3.8, unit: 'm', status: 'unverified', valueSource: 'posted_sign', reason: 'heightM 4 > limit 3.8 m', geometry: { type: 'Point', coordinates: [34.79, 32.085] } };
  const ok = { id: 'test-tall-bridge', restrictionType: 'max_height', value: 4.5, unit: 'm', status: 'verified', valueSource: 'posted_sign', geometry: { type: 'Point', coordinates: [34.81, 32.11] } };
  return {
    200: { trip: { legs: [{ shape: encodePolyline([[34.78, 32.08], [34.795, 32.095], [34.80, 32.10], [34.82, 32.12]]) }], summary: { length: 5.1, time: 540 } },
      trucksil: { disclaimer: 'prototype, not for navigation', avoided: [low], onRoute: [ok], coverage: { verifiedOnRoute: 1, unverifiedOnRoute: 0, note: 'Absence of restrictions in TrucksIL data does not mean the route is safe' }, unverifiedCoverage: 'unknown', reroutes: 1 } },
    422: { error: 'no route found that avoids the known TrucksIL restrictions for this vehicle', conflicts: [low], trucksil: { disclaimer: 'prototype, not for navigation' } },
  };
}

async function main() {
  if (!fs.existsSync(path.join(DIST, 'index.html'))) throw new Error('web/dist missing: run `npm run build` in web/ first');
  const fx = await fixtures();
  let mode = 200;
  const requests = [];
  const server = http.createServer((req, res) => {
    const u = new URL(req.url, 'http://x');
    if (u.pathname.startsWith('/api/')) {
      let b = ''; req.on('data', (c) => { b += c; });
      req.on('end', () => { requests.push({ path: u.pathname, body: JSON.parse(b || 'null') }); res.writeHead(mode, { 'content-type': 'application/json' }); res.end(JSON.stringify(fx[mode])); });
      return;
    }
    let f = path.join(DIST, path.normalize(u.pathname));
    if (!f.startsWith(DIST) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) f = path.join(DIST, 'index.html');
    res.writeHead(200, { 'content-type': TYPES[path.extname(f)] || 'application/octet-stream' });
    fs.createReadStream(f).pipe(res);
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader', '--use-angle=swiftshader'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 820 }, deviceScaleFactor: 2, locale: 'ru-RU' });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error' && !/status of 422/.test(m.text())) errors.push(m.text()); });
    await page.route('https://tile.openstreetmap.org/**', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: blankTile() }));
    await page.goto(base);

    // Default language from navigator (ru), ltr; banner always present.
    assert.equal(await page.getAttribute('html', 'dir'), 'ltr');
    assert.match(await page.textContent('.banner'), /Прототип\. Не для навигации\./);
    assert.match(await page.textContent('.banner'), /Отсутствие ограничений ≠ безопасно/);

    // Hebrew -> rtl.
    await page.selectOption('#lang', 'he');
    assert.equal(await page.getAttribute('html', 'dir'), 'rtl');
    assert.match(await page.textContent('.banner'), /לא לניווט/);
    await page.selectOption('#lang', 'ru');

    // Invalid profile is rejected by the schema.
    await page.fill('[name=profileName]', 'Тестовый грузовик (вымышленный)');
    await page.fill('[name=heightM]', '9');
    await page.click('#profile button[type=submit]');
    assert.match(await page.textContent('#profile-msg'), /heightM must be <= 6/);
    await page.fill('[name=heightM]', '4');
    await page.fill('[name=widthM]', '2.5');
    await page.fill('[name=lengthM]', '12');
    await page.fill('[name=grossWeightT]', '18');
    await page.click('#profile button[type=submit]');
    assert.match(await page.textContent('#profile-msg'), /Профиль сохранён/);
    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('trucksil.profiles.v1')));
    assert.equal(stored[0].heightM, 4);

    // 422: conflicts, no route drawn.
    mode = 422;
    await page.fill('[name=from]', '34.78,32.08');
    await page.fill('[name=to]', '34.82,32.12');
    await page.click('#route button[type=submit]');
    await page.waitForSelector('#restr-body .error');
    assert.match(await page.textContent('#restr-body'), /Маршрут не показан/);
    assert.match(await page.textContent('#restr-body'), /3\.8 m/);
    assert.equal(await routeFeatureCount(page), 0);

    // 200: route + avoided/onRoute.
    mode = 200;
    await page.click('#route button[type=submit]');
    await page.waitForSelector('#restr-body .summary');
    const txt = await page.textContent('#restr-body');
    assert.match(txt, /Объезжено/);
    assert.match(txt, /3\.8 m/);
    assert.match(txt, /по знаку/);
    assert.match(txt, /не проверено/);
    assert.match(txt, /4\.5 m/);
    assert.match(txt, /проверено/);
    assert.equal(await routeFeatureCount(page), 4);
    assert.deepEqual(requests.at(-1).body.from, [34.78, 32.08]);
    assert.equal(requests.at(-1).body.vehicle.heightM, 4);

    // Manifest + service worker are served.
    const man = await (await page.request.get(`${base}/manifest.webmanifest`)).json();
    assert.equal(man.display, 'standalone');
    assert.equal((await page.request.get(`${base}/sw.js`)).ok(), true);

    // Show the restrictions panel in the screenshot and let the map render the route.
    await page.evaluate(() => document.querySelector('#restr').scrollIntoView());
    await page.waitForTimeout(1500);
    if (shot) await page.screenshot({ path: shot });
    assert.deepEqual(errors, []);
    console.log(`web smoke: OK${shot ? ` (screenshot ${shot})` : ''}`);
  } finally {
    await browser.close();
    server.close();
  }
}

function blankTile() {
  // 1x1 light-grey PNG; MapLibre scales it. Keeps the test offline and off the OSM servers.
  return Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');
}

async function routeFeatureCount(page) {
  return Number(await page.getAttribute('#map', 'data-route-points'));
}

main().catch((e) => { console.error(e); process.exit(1); });
