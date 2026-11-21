import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

const repoRoot = fileURLToPath(new URL('..', import.meta.url));
const tilesDir = path.join(repoRoot, 'data', 'tiles');

// Dev only: serve data/tiles (israel.pmtiles + fonts/) at /tiles with HTTP Range support, like
// the nginx container does. Missing file -> 404 (the app then falls back to OSM raster tiles).
function serveTiles() {
  return {
    name: 'trucksil-tiles',
    configureServer(server) {
      server.middlewares.use('/tiles', (req, res, next) => {
        const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
        const file = path.join(tilesDir, path.normalize(rel));
        if (!file.startsWith(tilesDir + path.sep)) return next();
        let st;
        try { st = fs.statSync(file); } catch { res.statusCode = 404; return res.end(); }
        if (!st.isFile()) { res.statusCode = 404; return res.end(); }
        const m = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range || '');
        res.setHeader('Accept-Ranges', 'bytes');
        res.setHeader('Content-Type', file.endsWith('.pbf') ? 'application/x-protobuf' : 'application/octet-stream');
        res.setHeader('ETag', `"${st.size.toString(16)}-${Math.floor(st.mtimeMs).toString(16)}"`);
        if (!m) { res.setHeader('Content-Length', st.size); return fs.createReadStream(file).pipe(res); }
        const start = Number(m[1]);
        const end = Math.min(m[2] ? Number(m[2]) : st.size - 1, st.size - 1);
        if (start > end) { res.statusCode = 416; res.setHeader('Content-Range', `bytes */${st.size}`); return res.end(); }
        res.statusCode = 206;
        res.setHeader('Content-Range', `bytes ${start}-${end}/${st.size}`);
        res.setHeader('Content-Length', end - start + 1);
        fs.createReadStream(file, { start, end }).pipe(res);
      });
    },
  };
}

export default defineConfig({
  plugins: [serveTiles()],
  // Allow importing the shared schema (data/) and polyline decoder (api/src/polyline.mjs).
  server: {
    host: '127.0.0.1',
    port: 5173,
    fs: { allow: [repoRoot] },
    // Dev only: same-origin /api like the nginx container (no CORS on the API).
    proxy: { '/api': { target: process.env.TRUCKSIL_API || 'http://127.0.0.1:8080', rewrite: (p) => p.replace(/^\/api/, '') } },
  },
  worker: { format: 'es' },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false, chunkSizeWarningLimit: 1600, target: 'es2022' },
});
