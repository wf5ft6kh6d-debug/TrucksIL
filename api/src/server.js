'use strict';
const { Pool } = require('pg');
const { createServer } = require('./app');

const port = Number(process.env.PORT || 8080);
const db = process.env.DATABASE_URL ? new Pool({ connectionString: process.env.DATABASE_URL, max: 5 }) : null;
if (db) db.on('error', (e) => console.error('pg pool error:', e.message));

const server = createServer({ db, valhallaUrl: process.env.VALHALLA_URL || '' });
server.listen(port, () => {
  console.log(`trucksil api listening on :${port} (valhalla: ${process.env.VALHALLA_URL || 'disabled'})`);
});

function shutdown() {
  server.close(() => (db ? db.end() : Promise.resolve()).finally(() => process.exit(0)));
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
