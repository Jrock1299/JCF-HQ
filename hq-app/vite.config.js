import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev proxy mirrors production serve_hq.py (:8899):
//   /hq/*        → :8900  (Flask storage server)
//   /*.json      → :8899  (static dashboard JSON files)
// In production the built app is served BY serve_hq on :8899, so the browser
// only ever talks to same-origin — these proxies just replicate that in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/hq': 'http://localhost:8900',
      '^/[^/]+\\.json$': 'http://localhost:8899',
    },
  },
})
