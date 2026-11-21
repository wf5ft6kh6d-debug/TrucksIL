// Regenerates docs/i18n/strings.csv from web/src/i18n.js, keeping existing
// suggestions, notes and reviewer columns for keys that already exist.
// Usage: node scripts/i18n_export_review.mjs [csvPath]
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { STRINGS } from '../web/src/i18n.js';

const csvPath = process.argv[2] || 'docs/i18n/strings.csv';
const COLS = ['key', 'en', 'ru', 'he_current', 'he_suggested', 'ar_current', 'ar_suggested', 'notes', 'he_reviewed', 'ar_reviewed'];

function parseCsv(text) {
  const rows = []; let row = []; let f = ''; let q = false;
  text = text.replace(/^﻿/, '');
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(f); f = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(f); rows.push(row); row = []; f = ''; }
    else f += c;
  }
  if (f !== '' || row.length) { row.push(f); rows.push(row); }
  return rows.filter((r) => r.length > 1 || r[0] !== '');
}
const esc = (v) => (/[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

const old = new Map();
if (existsSync(csvPath)) {
  const [hdr, ...rows] = parseCsv(readFileSync(csvPath, 'utf8'));
  for (const r of rows) old.set(r[0], Object.fromEntries(hdr.map((h, i) => [h, r[i] ?? ''])));
}
const keys = Object.keys(STRINGS.en);
const lines = [COLS.join(',')];
let added = 0;
for (const k of keys) {
  const o = old.get(k) || {};
  if (!old.has(k)) added++;
  const rec = { key: k, en: STRINGS.en[k] ?? '', ru: STRINGS.ru[k] ?? '', he_current: STRINGS.he[k] ?? '', ar_current: STRINGS.ar[k] ?? '',
    he_suggested: o.he_suggested || '', ar_suggested: o.ar_suggested || '', notes: o.notes || (old.has(k) ? '' : 'NEW'),
    he_reviewed: o.he_reviewed || '', ar_reviewed: o.ar_reviewed || '' };
  lines.push(COLS.map((c) => esc(String(rec[c]))).join(','));
}
writeFileSync(csvPath, '﻿' + lines.join('\n') + '\n');
console.log(`i18n review CSV: ${keys.length} keys (${added} new) -> ${csvPath}`);
