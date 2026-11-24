'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { demoteOverdueReviews, UPDATE_SQL } = require('../../api/src/reviewDue');
const { ALONG_ROUTE_SQL, EXPIRED_ALONG_ROUTE_SQL } = require('../../api/src/restrictionsRepo');

function fakeDb(rows) {
  const log = [];
  return { log, async query(sql) { log.push(sql); return { rows: /RETURNING|SELECT id/.test(sql) ? rows : [] }; } };
}

test('dry run only selects: nothing is written', async () => {
  const db = fakeDb([{ id: 'a' }, { id: 'b' }]);
  const r = await demoteOverdueReviews(db);
  assert.deepEqual(r, { applied: false, ids: ['a', 'b'] });
  assert.ok(db.log.every((q) => !/UPDATE|BEGIN/.test(q)));
});

test('apply: one transaction, audit actor set, status becomes unverified (never expired)', async () => {
  const db = fakeDb([{ id: 'a' }]);
  const r = await demoteOverdueReviews(db, { apply: true });
  assert.deepEqual(r, { applied: true, ids: ['a'] });
  assert.equal(db.log[0], 'BEGIN');
  assert.match(db.log[1], /system:review-due/);
  assert.equal(db.log.at(-1), 'COMMIT');
  assert.match(UPDATE_SQL, /SET status = 'unverified'/);
  assert.doesNotMatch(UPDATE_SQL, /'expired'/);
});

test('failure rolls back', async () => {
  const db = { log: [], async query(sql) { this.log.push(sql); if (/UPDATE/.test(sql)) throw new Error('boom'); return { rows: [] }; } };
  await assert.rejects(demoteOverdueReviews(db, { apply: true }), /boom/);
  assert.equal(db.log.at(-1), 'ROLLBACK');
});

test('route SQL reports an overdue verified row as unverified at read time', () => {
  for (const sql of [ALONG_ROUTE_SQL, EXPIRED_ALONG_ROUTE_SQL]) {
    assert.match(sql, /CASE WHEN r\.status = 'verified' AND r\.review_due_at IS NOT NULL AND r\.review_due_at < now\(\) THEN 'unverified' ELSE r\.status END AS status/);
  }
});
