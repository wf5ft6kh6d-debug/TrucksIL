#!/usr/bin/env node
// Applies native-reviewed he/ar strings from docs/i18n/strings.csv to web/src/i18n.js.
// Usage: node scripts/i18n_apply_review.js <csv> [--target web/src/i18n.js] [--dry-run]
'use strict';
const fs = require('node:fs');
const path = require('node:path');

const LANGS = ['he', 'ar'];

function parseCsv(text) {
  text = text.replace(/^﻿/, '');
  const rows = []; let row = []; let f = ''; let q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(f); f = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(f); f = ''; if (row.some((x) => x !== '')) rows.push(row); row = [];
    } else f += c;
  }
  if (f !== '' || row.length) { row.push(f); if (row.some((x) => x !== '')) rows.push(row); }
  const [head, ...body] = rows;
  return body.map((r) => Object.fromEntries(head.map((h, i) => [h.trim(), r[i] ?? ''])));
}

const placeholders = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',');
const esc = (s) => s.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Returns { source, changes, errors }. Pure: does not touch disk. */
function applyReview(source, rows) {
  const changes = []; const errors = [];
  for (const lang of LANGS) {
    const start = source.search(new RegExp(`^  ${lang}: \\{$`, 'm'));
    if (start < 0) { errors.push(`block '${lang}' not found`); continue; }
    const end = source.indexOf('\n  },', start);
    let block = source.slice(start, end);
    for (const r of rows) {
      const val = (r[`${lang}_reviewed`] || '').trim();
      if (!val) continue;
      const key = r.key;
      if (/[\r\n]/.test(val)) { errors.push(`${lang} ${key}: newline not allowed`); continue; }
      if (r.en !== undefined && placeholders(val) !== placeholders(r.en)) {
        errors.push(`${lang} ${key}: placeholders {${placeholders(val)}} != en {${placeholders(r.en)}}`); continue;
      }
      const re = new RegExp(`^(    '${reEsc(key)}': )'((?:[^'\\\\]|\\\\.)*)',$`, 'm');
      const m = block.match(re);
      if (!m) { errors.push(`${lang} ${key}: key not found in i18n.js`); continue; }
      const oldVal = m[2].replace(/\\(.)/g, '$1');
      if (oldVal === val) continue;
      block = block.replace(re, (_, p) => `${p}'${esc(val)}',`);
      changes.push({ lang, key, from: oldVal, to: val });
    }
    source = source.slice(0, start) + block + source.slice(end);
  }
  return { source, changes, errors };
}

function main(argv) {
  const args = argv.slice(2);
  const dry = args.includes('--dry-run');
  const ti = args.indexOf('--target');
  const target = ti >= 0 ? args[ti + 1] : path.join(__dirname, '..', 'web', 'src', 'i18n.js');
  const csv = args.find((a, i) => !a.startsWith('--') && args[i - 1] !== '--target');
  if (!csv) { console.error('usage: i18n_apply_review.js <csv> [--target file] [--dry-run]'); return 2; }
  const rows = parseCsv(fs.readFileSync(csv, 'utf8'));
  const { source, changes, errors } = applyReview(fs.readFileSync(target, 'utf8'), rows);
  for (const c of changes) console.log(`${c.lang} ${c.key}: "${c.from}" -> "${c.to}"`);
  for (const e of errors) console.error(`ERROR ${e}`);
  if (errors.length) { console.error('Nothing written: fix errors first.'); return 1; }
  if (!dry && changes.length) fs.writeFileSync(target, source);
  console.log(`${changes.length} change(s)${dry ? ' (dry run, not written)' : ''}.`);
  return 0;
}

module.exports = { parseCsv, applyReview };
if (require.main === module) process.exitCode = main(process.argv);
