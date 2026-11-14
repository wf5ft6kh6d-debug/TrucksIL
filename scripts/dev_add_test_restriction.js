#!/usr/bin/env node
'use strict';
// DEV ONLY: adds/removes a FICTIONAL max_height restriction to test POST /v1/route avoidance.
//   node scripts/dev_add_test_restriction.js pick < route.json        # print a point from the middle of the route shape
//   node scripts/dev_add_test_restriction.js add <lon> <lat> [heightM] # default 3.5
//   node scripts/dev_add_test_restriction.js delete
// DB: DATABASE_URL, e.g. postgres://trucksil:<password>@localhost:5432/trucksil (see .env).
// The record is marked unverified, source "dev-test", and must never be left in a real database.
const { Pool } = require('pg');
const { routeShape } = require('../api/src/polyline');

const ID = 'dev-test-max-height';

function usage(msg) {
  if (msg) console.error(msg);
  console.error('usage: dev_add_test_restriction.js pick < route.json | add <lon> <lat> [heightM] | delete');
  process.exit(2);
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

async function withDb(fn) {
  if (!process.env.DATABASE_URL) usage('DATABASE_URL is not set');
  const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 1 });
  try { return await fn(pool); } finally { await pool.end(); }
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  if (cmd === 'pick') {
    const shape = routeShape(JSON.parse(await readStdin()));
    if (!shape.length) usage('no trip.legs[].shape in input (pass the JSON returned by POST /v1/route)');
    const [lon, lat] = shape[Math.floor(shape.length / 2)];
    console.log(`${lon},${lat}`);
    return;
  }
  if (cmd === 'add') {
    const [lon, lat, h = '3.5'] = args.map(Number);
    if (![lon, lat, Number(h)].every(Number.isFinite)) usage('lon, lat and heightM must be numbers');
    await withDb(async (db) => {
      await db.query("SELECT set_config('trucksil.actor', 'dev_add_test_restriction', false)");
      await db.query(`
        INSERT INTO restrictions (id, road_segment_id, geometry, value_source, restriction_type, value_numeric, unit,
                                  status, source, observed_at)
        VALUES ($1, 'dev-test', ST_SetSRID(ST_MakePoint($2, $3), 4326), 'posted_sign', 'max_height', $4, 'm',
                'unverified', '{"name":"dev-test","reference":"fictional, scripts/dev_add_test_restriction.js"}', now())
        ON CONFLICT (id) DO UPDATE SET geometry = EXCLUDED.geometry, value_numeric = EXCLUDED.value_numeric`,
      [ID, lon, lat, Number(h)]);
    });
    console.log(`added ${ID}: max_height ${h} m at ${lon},${lat} (fictional, unverified)`);
    return;
  }
  if (cmd === 'delete') {
    const n = await withDb(async (db) => {
      await db.query("SELECT set_config('trucksil.actor', 'dev_add_test_restriction', false)");
      return (await db.query('DELETE FROM restrictions WHERE id = $1', [ID])).rowCount;
    });
    console.log(`deleted ${n} row(s)`);
    return;
  }
  usage();
}

main().catch((e) => { console.error(e.message); process.exit(1); });
