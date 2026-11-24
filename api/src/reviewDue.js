'use strict';
// Overdue reviews (ADR-0021): a 'verified' restriction whose review_due_at has passed is demoted to
// 'unverified'. It is NOT set to 'expired': 'expired' stops avoidance (warning only, ADR-0020), whereas an
// overdue-but-once-verified limit must keep steering routes away. verified_by / verified_at stay for history.
// The change goes through the restrictions audit trigger with actor 'system:review-due'.

const SELECT_SQL = `SELECT id, review_due_at FROM restrictions
 WHERE status = 'verified' AND review_due_at IS NOT NULL AND review_due_at < now() ORDER BY id`;
const UPDATE_SQL = `UPDATE restrictions SET status = 'unverified'
 WHERE status = 'verified' AND review_due_at IS NOT NULL AND review_due_at < now() RETURNING id`;

/**
 * @param {{query: Function}} db  single connection (the actor setting must share the transaction)
 * @param {{apply?: boolean}} o   default is a dry run: lists what would change, writes nothing
 * @returns {Promise<{applied: boolean, ids: string[]}>}
 */
async function demoteOverdueReviews(db, { apply = false } = {}) {
  if (!apply) {
    const { rows } = await db.query(SELECT_SQL);
    return { applied: false, ids: rows.map((r) => r.id) };
  }
  await db.query('BEGIN');
  try {
    await db.query("SELECT set_config('trucksil.actor', 'system:review-due', true)");
    const { rows } = await db.query(UPDATE_SQL);
    await db.query('COMMIT');
    return { applied: true, ids: rows.map((r) => r.id) };
  } catch (e) {
    await db.query('ROLLBACK').catch(() => {});
    throw e;
  }
}

module.exports = { demoteOverdueReviews, SELECT_SQL, UPDATE_SQL };
