import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/hq':                    'http://localhost:8900',
      '/market_bias.json':      'http://localhost:8899',
      '/tradelocker_trades.json': 'http://localhost:8899',
      '/oracle_picks.json':     'http://localhost:8899',
      '/oracle_resolved.json':  'http://localhost:8899',
      '/plaid_data.json':       'http://localhost:8899',
      '/agent_hub.json':        'http://localhost:8899',
      '/bet_log.json':          'http://localhost:8899',
      '/robinhood_data.json':   'http://localhost:8899',
      '/trustwallet_data.json': 'http://localhost:8899',
      '/bball_stats.json':      'http://localhost:8899',
      '/sports_intel.json':     'http://localhost:8899',
    },
  },
})
