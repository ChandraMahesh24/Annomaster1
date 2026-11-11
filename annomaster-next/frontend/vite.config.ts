import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server proxies /api → FastAPI backend, so the SPA and API share an origin
// in development (no CORS wrangling, cookies flow) — matching how they'll be
// served together in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
