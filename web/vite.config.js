import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

const repoRoot = fileURLToPath(new URL('..', import.meta.url));

export default defineConfig({
  // Allow importing the shared schema (data/) and polyline decoder (api/src/polyline.mjs).
  server: {
    host: '127.0.0.1',
    port: 5173,
    fs: { allow: [repoRoot] },
    // Dev only: same-origin /api like the nginx container (no CORS on the API).
    proxy: { '/api': { target: process.env.TRUCKSIL_API || 'http://127.0.0.1:8080', rewrite: (p) => p.replace(/^\/api/, '') } },
  },
  worker: { format: 'es' },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false, chunkSizeWarningLimit: 1600 },
});
