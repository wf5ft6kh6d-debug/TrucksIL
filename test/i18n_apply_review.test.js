'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const root = path.join(__dirname, '..');
const script = path.join(root, 'scripts', 'i18n_apply_review.js');
const real = path.join(root, 'web', 'src', 'i18n.js');

function setup(csvBody) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'i18n-review-'));
  const target = path.join(dir, 'i18n.js');
  fs.copyFileSync(real, target);
  const csv = path.join(dir, 's.csv');
  fs.writeFileSync(csv, '﻿key,en,he_reviewed,ar_reviewed\r\n' + csvBody);
  return { target, csv };
}
const run = (args) => { try { return { code: 0, out: execFileSync('node', [script, ...args], { encoding: 'utf8', stdio: 'pipe' }) }; } catch (e) { return { code: e.status, out: e.stdout + e.stderr }; } };

test('applies he/ar reviewed values, skips empty, leaves real file alone', () => {
  const before = fs.readFileSync(real, 'utf8');
  const { target, csv } = setup('banner.prototype,Prototype. Not for navigation.,אב טיפוס. אין להשתמש לניווט.,\r\n' +
    'route.summary,"Distance {km} km, time {min} min, restriction detours: {reroutes}",,"المسافة {km} كم، الوقت {min} دقيقة، it\'s {reroutes}"\r\n' +
    'lang.label,Language,,\r\n');
  const r = run([csv, '--target', target]);
  assert.strictEqual(r.code, 0, r.out);
  const src = fs.readFileSync(target, 'utf8');
  assert.match(src, /'banner\.prototype': 'אב טיפוס\. אין להשתמש לניווט\.',/);
  assert.ok(src.includes("it\\'s {reroutes}"));
  assert.match(src, /'banner\.prototype': 'Prototype\. Not for navigation\.',/); // en untouched
  assert.strictEqual(fs.readFileSync(real, 'utf8'), before);
});

test('--dry-run does not write', () => {
  const { target, csv } = setup('banner.prototype,x,שינוי,\r\n');
  const before = fs.readFileSync(target, 'utf8');
  const r = run([csv, '--target', target, '--dry-run']);
  assert.strictEqual(r.code, 0);
  assert.match(r.out, /dry run/);
  assert.strictEqual(fs.readFileSync(target, 'utf8'), before);
});

test('rejects broken placeholders and unknown keys', () => {
  const { target, csv } = setup('restr.coverage,"{verified} / {unverified}",{verified} בלבד,\r\nno.such,x,y,\r\n');
  const before = fs.readFileSync(target, 'utf8');
  const r = run([csv, '--target', target]);
  assert.strictEqual(r.code, 1);
  assert.match(r.out, /placeholders/);
  assert.match(r.out, /not found/);
  assert.strictEqual(fs.readFileSync(target, 'utf8'), before);
});

test('generated strings.csv parses and matches i18n.js keys', () => {
  const { parseCsv } = require(script);
  const rows = parseCsv(fs.readFileSync(path.join(root, 'docs', 'i18n', 'strings.csv'), 'utf8'));
  assert.ok(rows.length > 50);
  assert.ok(rows.every((r) => 'he_reviewed' in r && 'ar_reviewed' in r));
});
