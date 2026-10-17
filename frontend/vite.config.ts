import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backend = process.env.VITE_BACKEND || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ui/api': { target: backend, changeOrigin: true, ws: true },
      '/api': { target: backend, changeOrigin: true },
      '/admin': { target: backend, changeOrigin: true },
      '/health': backend, '/ready': backend, '/version': backend, '/metrics': backend,
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
});
