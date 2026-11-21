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
    200: { trip: { legs: [{ shape: encodePolyline([[34.78, 32.08], [34.795, 32.095], [34.80, 32.10], [34.82, 32.12]]), maneuvers: [
      { type: 1, begin_shape_index: 0, instruction: 'Двигайтесь на северо-восток.', verbal_pre_transition_instruction: 'Двигайтесь на северо-восток по Тестовой улице.', verbal_post_transition_instruction: 'Продолжайте движение 3 километра.' },
      { type: 10, begin_shape_index: 2, instruction: 'Поверните направо.', verbal_transition_alert_instruction: 'Поверните направо.', verbal_pre_transition_instruction: 'Поверните направо на Мостовую улицу.' },
      { type: 4, begin_shape_index: 3, instruction: 'Вы прибыли в пункт назначения.', verbal_pre_transition_instruction: 'Вы прибыли в пункт назначения.' },
    ] }], summary: { length: 5.1, time: 540 } },
      trucksil: { disclaimer: 'prototype, not for navigation', avoided: [low], onRoute: [ok], coverage: { verifiedOnRoute: 1, unverifiedOnRoute: 0, note: 'Absence of restrictions in TrucksIL data does not mean the route is safe', status: 'computed', structuresOnRoute: 2, structuresWithData: 1, noDataSegments: [{ type: 'bridge', from: [34.80, 32.10], to: [34.82, 32.12], wayId: 123, coordinates: [[34.80, 32.10], [34.82, 32.12]] }] }, reroutes: 1 } },
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
    if (u.pathname === '/api/v1/reports' && req.method === 'GET') {
      // Driver reports (ADR-0012): one unverified report in any bbox.
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ reports: [{ id: 'r-smoke', type: 'hazard', position: [34.8, 32.1], note: null, ageMinutes: 4, confirmations: 1, verified: false }] }));
      return;
    }
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
    page.on('console', (m) => { if (m.type() === 'error' && !/status of 422|ERR_INTERNET_DISCONNECTED|tiles\/israel\.pmtiles/.test(m.text())) errors.push(m.text()); });
    // Mock Web Speech API: record what would be spoken (ADR-0015 voice guidance).
    await page.addInitScript(() => {
      window.__spoken = [];
      const synth = { getVoices: () => [{ lang: 'ru-RU', name: 'ru-mock', localService: true }], speak(u) { window.__spoken.push(u.text); setTimeout(() => u.onend && u.onend(), 5); }, cancel() {}, onvoiceschanged: null };
      Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
      window.SpeechSynthesisUtterance = function Utterance(text) { this.text = text; };
    });
    await page.route('https://tile.openstreetmap.org/**', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: blankTile() }));
    await page.goto(base);

    // Default language from navigator (ru), ltr; banner always present.
    assert.equal(await page.getAttribute('html', 'dir'), 'ltr');
    assert.match(await page.textContent('.banner'), /Прототип\. Не для навигации\./);
    assert.match(await page.textContent('.banner'), /Отсутствие ограничений ≠ безопасно/);

    // No data/tiles/israel.pmtiles in this test: OSM raster fallback with a visible dev notice.
    assert.equal(await page.getAttribute('#map', 'data-basemap'), 'osm-raster');
    assert.match(await page.textContent('#map-notice'), /Файл офлайн-карты не установлен/);
    assert.equal(await page.isDisabled('#nav-sim'), true, 'navigation needs a route');

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
    // Bridge/tunnel coverage (ADR-0014): count line + dashed no-data layer with legend.
    assert.match(txt, /Мостов\/тоннелей на маршруте: 2, с данными TrucksIL: 1 — 1 без данных \(проверьте знаки\)/);
    assert.match(txt, /мост\/тоннель без данных TrucksIL/);
    assert.equal(await page.getAttribute('#map', 'data-no-data-segments'), '1');
    const routeReqs = requests.filter((r) => r.path === '/api/v1/route');
    assert.deepEqual(routeReqs.at(-1).body.from, [34.78, 32.08]);
    assert.equal(routeReqs.at(-1).body.vehicle.heightM, 4);

    assert.equal(routeReqs.at(-1).body.language, 'ru-RU', 'Valhalla narrative in UI language');

    // Simulated drive (ADR-0015): voice on, fast replay to arrival; maneuvers + TrucksIL warning spoken.
    await page.check('#nav-voice');
    await page.fill('#nav-speed', '3000');
    await page.click('#nav-sim');
    await page.waitForFunction(() => /Вы прибыли/.test(document.querySelector('#nav-status').textContent), null, { timeout: 20000 });
    assert.match(await page.textContent('#nav-status'), /СИМУЛЯЦИЯ/);
    const spoken = await page.evaluate(() => window.__spoken);
    assert.equal(spoken[0], 'Двигайтесь на северо-восток по Тестовой улице.');
    assert.ok(spoken.some((x) => /мост без данных TrucksIL\. Проверьте знаки\./.test(x)), spoken.join(' | '));
    assert.ok(spoken.includes('Поверните направо на Мостовую улицу.'), spoken.join(' | '));
    assert.ok(spoken.includes('Вы прибыли в пункт назначения.'), spoken.join(' | '));
    await page.click('#nav-stop');

    // Off-route: simulate 200 m beside the line -> after 10 s off route -> automatic reroute from
    // the (simulated) current position, same destination and vehicle.
    const before = requests.filter((r) => r.path === '/api/v1/route').length;
    await page.fill('#nav-speed', '60');
    await page.fill('#nav-offset', '200');
    await page.click('#nav-sim');
    await page.waitForFunction(() => document.querySelector('#nav-status').dataset.reroutes === '1', null, { timeout: 25000 });
    const rr = requests.filter((r) => r.path === '/api/v1/route');
    assert.equal(rr.length, before + 1);
    const [fx, fy] = rr.at(-1).body.from; // first route segment is lat = 32.08 + (lon - 34.78); sim is 200 m north of it
    assert.ok(Math.abs(fy - (32.08 + (fx - 34.78)) - 200 / 111320) < 0.0002, JSON.stringify(rr.at(-1).body.from));
    assert.deepEqual(rr.at(-1).body.to, [34.82, 32.12]);
    assert.equal(rr.at(-1).body.vehicle.heightM, 4);
    await page.click('#nav-stop');
    await page.fill('#nav-offset', '0');

    // Offline: the API is unreachable -> last route shown, flagged as outdated (never "valid").
    await page.route('**/api/v1/route', (r) => r.abort('internetdisconnected'));
    await page.click('#route button[type=submit]');
    await page.waitForSelector('#restr-body .offline-route');
    assert.match(await page.textContent('#restr-body .offline-route'), /Офлайн: маршрут от .+, ограничения могут быть устаревшими\./);
    assert.equal(await routeFeatureCount(page), 4);
    await page.unroute('**/api/v1/route');

    // Driver reports panel: distinct item, always labelled unverified.
    await page.waitForSelector('#reports-body li.report');
    assert.match(await page.textContent('#reports-body'), /сообщение водителя, не проверено/);

    // Shift timer (US-06, ADR-0018) with a fake clock: start -> alert -> break -> resume -> reload.
    {
      const ctx = await browser.newContext({ locale: 'ru-RU' });
      const sp = await ctx.newPage();
      sp.on('pageerror', (e) => errors.push(`shift: ${e.message}`));
      await sp.addInitScript(() => {
        window.__spoken = [];
        const synth = { getVoices: () => [{ lang: 'ru-RU', name: 'ru-mock', localService: true }], speak(u) { window.__spoken.push(u.text); setTimeout(() => u.onend && u.onend(), 5); }, cancel() {}, onvoiceschanged: null };
        Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
        window.SpeechSynthesisUtterance = function Utterance(text) { this.text = text; };
      });
      await sp.clock.install({ time: new Date('2026-11-21T06:00:00Z') });
      await sp.route('https://tile.openstreetmap.org/**', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: blankTile() }));
      await sp.goto(base);
      assert.match(await sp.textContent('#shift'), /Напоминание, не юридическое подтверждение соблюдения режима труда и отдыха/);
      await sp.check('#nav-voice');
      await sp.click('#shift summary');
      await sp.fill('#shift-drive-limit', '3');
      await sp.click('#shift-settings button[type=submit]');
      await sp.click('#shift-start');
      assert.equal(await sp.getAttribute('#shift-status', 'data-status'), 'driving');
      await sp.clock.runFor('01:00:05');
      await sp.waitForFunction(() => !document.querySelector('#shift-alert').hidden);
      assert.match(await sp.textContent('#shift-alert'), /До лимита вождения осталось 2:00/);
      assert.ok((await sp.evaluate(() => window.__spoken)).some((x) => /лимита вождения/.test(x)));
      await sp.click('#shift-break');
      await sp.clock.runFor('00:15:00');
      await sp.click('#shift-resume');
      await sp.clock.runFor('00:10:00');
      assert.match(await sp.textContent('#shift-totals'), /Вождение 1:10 · перерывы 0:15 · смена 1:25/);
      await sp.reload();
      assert.equal(await sp.getAttribute('#shift-status', 'data-status'), 'driving', 'state survives reload');
      assert.match(await sp.textContent('#shift-totals'), /Вождение 1:10/);
      await sp.click('#shift-end');
      assert.equal(await sp.getAttribute('#shift-status', 'data-status'), 'idle');
      assert.equal(await sp.locator('#shift-history li').count(), 1);
      const [dl] = await Promise.all([sp.waitForEvent('download'), sp.click('#shift-export')]);
      assert.match(dl.suggestedFilename(), /^trucksil-shifts-2026-11-21\.csv$/);
      sp.once('dialog', (d) => d.accept());
      await sp.click('#shift-clear');
      assert.equal(await sp.locator('#shift-history li').count(), 0);
      await ctx.close();
    }

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
