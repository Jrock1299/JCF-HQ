/**
 * JCF HQ — API client
 *
 * All requests use relative URLs so Vite's dev proxy (vite.config.js) routes them:
 *   /hq/*          → http://localhost:8900  (Flask storage server)
 *   /*.json        → http://localhost:8899  (Static JSON file server)
 *
 * This avoids CORS entirely — the browser only ever talks to port 5173.
 */

const STORAGE_BASE = '/hq'
const FILES_BASE   = ''

// ── Low-level helpers ──────────────────────────────────────────────────

async function req(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`[HQ API] ${res.status} ${res.statusText} — ${url}\n${text}`)
  }
  return res.json()
}

const get  = (path)        => req(`${STORAGE_BASE}${path}`)
const post = (path, body)  => req(`${STORAGE_BASE}${path}`,  { method: 'POST',   body: JSON.stringify(body) })
const patch= (path, body)  => req(`${STORAGE_BASE}${path}`,  { method: 'PATCH',  body: JSON.stringify(body) })
const del  = (path)        => req(`${STORAGE_BASE}${path}`,  { method: 'DELETE' })
const file = (name)        => req(`/${name}`)

// ── Stored data (accounts, income, basketball, bets, etc.) ────────────

/** GET /hq/data — full persisted blob */
export const getStoredData = () => get('/data')

/** POST /hq/data — merge-update stored data */
export const updateStoredData = (body) => post('/data', body)

/** POST /hq/account/:key */
export const setAccount = (key, body) => post(`/account/${key}`, body)

// ── Income ────────────────────────────────────────────────────────────

export const addIncome    = (entry) => post('/income', entry)
export const deleteIncome = (id)    => del(`/income/${id}`)

// ── Trading accounts ──────────────────────────────────────────────────

export const addTradingAccount = (account) => post('/trading-accounts', account)

// ── Basketball ────────────────────────────────────────────────────────

export const setBasketball = (data) => post('/basketball', data)

// ── Bets ──────────────────────────────────────────────────────────────

export const addBet    = (bet)        => post('/bets', bet)
export const patchBet  = (id, body)   => patch(`/bets/${id}`, body)
export const deleteBet = (id)         => del(`/bets/${id}`)

export const parseFliffScreenshot = (formData) =>
  fetch(`${STORAGE_BASE}/parse-fliff-screenshot`, { method: 'POST', body: formData })
    .then(res => { if (!res.ok) throw new Error(`[HQ API] ${res.status} ${res.statusText}`); return res.json() })

export const setFliffBalance = (balance) => post('/fliff-balance', { balance })

// ── Oracle picks ──────────────────────────────────────────────────────

export const saveOraclePicks    = (data) => post('/oracle/picks', data)
export const saveOracleResolved = (data) => post('/oracle/resolved', data)

// ── Bankroll ──────────────────────────────────────────────────────────

export const setBankroll = (data) => post('/bankroll', data)
export const addBankrollTransaction = (tx) => post('/bankroll/transactions', tx)

// ── Agent Hub ─────────────────────────────────────────────────────────

/**
 * GET /hq/hub
 * @param {number} [limit] — optional cap on messages (newest first)
 */
export const getHubMessages = (limit) => {
  const qs = limit ? `?limit=${limit}` : ''
  return get(`/hub${qs}`)
}

export const addHubMessage  = (body)       => post('/hub', body)
export const getHubStats    = ()           => get('/hub/stats')
export const postHubCollab  = (question)   => post('/hub/collab', { question })

// ── TradeLocker trade edits ───────────────────────────────────────────

export const postManualTrade       = (body)       => post('/tradelocker/trades', body)
export const patchTradelockerTrade = (idx, body) => patch(`/tradelocker/trades/${idx}`, body)

// ── Static JSON files (served on port 8899) ───────────────────────────

export const getTradesFile      = () => req(`/tradelocker_trades.json?t=${Date.now()}`)
export const getGoatFile        = () => req(`/tradelocker_trades_goat.json?t=${Date.now()}`)
export const getOracleFile      = () => req(`/oracle_picks.json?t=${Date.now()}`)
export const getOracleResolved  = () => req(`/oracle_resolved.json?t=${Date.now()}`)
export const getHubFile         = () => file('agent_hub.json')
export const getMarketBias      = () => file('market_bias.json')
export const getPlaidData         = () => file('plaid_data.json')
export const getPlaidTransactions = () => req(`/plaid_transactions.json?t=${Date.now()}`)
export const getRobinhoodData   = () => file('robinhood_data.json')
export const getTrustWalletData = () => file('trustwallet_data.json')
export const getBballStats      = () => file('bball_stats.json')
export const getAgentPnl        = () => file('agent_pnl.json')
export const getAgentTrades     = () => file('agent_trades.json')
export const getTaoPortfolio    = () => req(`/tao_portfolio.json?t=${Date.now()}`)

// ── New dashboard endpoints ───────────────────────────────────────────

export const getRobinhoodHoldings = () => get('/robinhood-holdings')
export const getKrakenHoldings   = () => get('/kraken-holdings')
export const getKalshiDailyPnl  = () => get('/kalshi-daily-pnl')
export const getTaoDailyChange   = () => get('/tao-daily-change')
export const getAgentStatus      = () => get('/agent-status')

// ── Demo-mode mask helper ─────────────────────────────────────────────

/**
 * If demo mode is active, replace numbers with masked values
 * and optionally blur strings.
 *
 * Usage: mask(value, demoMode)
 *   mask(12345.67, true)  → "••••••"
 *   mask(12345.67, false) → 12345.67
 */
export function mask(value, demoMode, opts = {}) {
  if (!demoMode) return value
  if (typeof value === 'number') return opts.placeholder ?? '••••'
  if (typeof value === 'string' && opts.maskStrings) return '••••••'
  return value
}

/**
 * Format a dollar amount, with optional demo masking.
 *   fmt(1234.5)        → "$1,234.50"
 *   fmt(1234.5, true)  → "••••••"
 */
export function fmt(amount, demoMode = false, opts = {}) {
  if (demoMode) return opts.placeholder ?? '••••••'
  const num = parseFloat(amount) || 0
  const abs = Math.abs(num)
  const sign = num < 0 ? '-' : (opts.showPlus && num > 0 ? '+' : '')
  return `${sign}$${abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
