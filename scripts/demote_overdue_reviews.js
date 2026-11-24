#!/usr/bin/env node
'use strict';
// Demote 'verified' restrictions with an overdue review to 'unverified' (ADR-0021).
// Dry run by default; add --apply to write. Run periodically (cron) against DATABASE_URL.
const { Pool } = require('pg');
const { demoteOverdueReviews } = require('../api/src/reviewDue');

async function main() {
  if (!process.env.DATABASE_URL) { console.error('DATABASE_URL is not set'); process.exit(2); }
  const apply = process.argv.includes('--apply');
  const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 1 });
  try {
    const r = await demoteOverdueReviews(pool, { apply });
    console.log(`${r.applied ? 'demoted' : 'would demote (dry run, use --apply)'}: ${r.ids.length}`);
    for (const id of r.ids) console.log(`  ${id}`);
  } finally { await pool.end(); }
}
main().catch((e) => { console.error(e.message); process.exit(1); });
