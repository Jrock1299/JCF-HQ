import { useEffect, useRef, useState, useCallback } from 'react'

// Logical endpoint name → same-origin URL. In production the app is served by
// serve_hq.py (:8899) which serves these JSON files directly AND proxies /hq/*
// to the Flask storage server (:8900). Never hardcode a host — relative URLs
// keep the browser on one origin (matches the old src/api/client.js pattern).
export const ENDPOINTS: Record<string, string> = {
  'market-bias': '/market_bias.json',
  'strategy-recommendation': '/strategy_recommendation.json',
  'blade-learning-log': '/blade_learning_log.json',
  'blade-balance': '/blade_balance.json',
  'blade-manual': '/blade_manual.json',
  'kraken': '/kraken_data.json',
  'mercury': '/mercury_data.json',
  'jerry-portfolio': '/jerry_portfolio.json',
  'plaid-data': '/plaid_data.json',
  'plaid-transactions': '/plaid_transactions.json',
  'tradelocker-trades': '/tradelocker_trades.json',
  'tao-portfolio': '/tao_portfolio.json',
  'net-worth': '/net_worth.json',
  'robinhood': '/robinhood_data.json',
  'trustwallet': '/trustwallet_data.json',
  'victoria-report': '/victoria_report.json',
  'norman-report': '/norman_report.json',
  'agent-hub': '/hq/hub',
  'agent-hub-file': '/agent_hub.json',
  'morning-report': '/morning_report.json',
  'sentinel-data': '/sentinel_data.json',
}

async function fetchWithTimeout(url: string, ms = 2500): Promise<any> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), ms)
  try {
    const res = await fetch(url, { signal: ctrl.signal })
    if (!res.ok) throw new Error(`${res.status}`)
    return await res.json()
  } finally {
    clearTimeout(t)
  }
}

export interface HQResult<T = any> {
  data: T | null
  loading: boolean
  error: boolean
}

/**
 * Fetch a logical HQ endpoint (or raw URL) with a hard timeout, try/catch, and
 * optional polling. Never throws to the component — on failure returns
 * { data: null, error: true } so callers render a graceful fallback.
 *
 * @param name    logical endpoint key from ENDPOINTS, or a raw "/path.json"
 * @param pollMs  poll interval in ms (0 = no polling). Default 60s — backend
 *                JSON is only refreshed every 2–5 min by cron, so faster
 *                polling just wastes fetches. Pass a smaller value per-call
 *                only for data that genuinely needs it.
 */
export function useHQData<T = any>(name: string, pollMs = 60_000): HQResult<T> {
  const url = ENDPOINTS[name] || name
  const [state, setState] = useState<HQResult<T>>({ data: null, loading: true, error: false })
  const mounted = useRef(true)

  const load = useCallback(async () => {
    try {
      const data = await fetchWithTimeout(url)
      if (mounted.current) setState({ data, loading: false, error: false })
    } catch {
      if (mounted.current) setState((prev) => ({ data: prev.data, loading: false, error: true }))
    }
  }, [url])

  useEffect(() => {
    mounted.current = true
    load()
    if (pollMs > 0) {
      const id = setInterval(load, pollMs)
      return () => {
        mounted.current = false
        clearInterval(id)
      }
    }
    return () => {
      mounted.current = false
    }
  }, [load, pollMs])

  return state
}

// Try a primary endpoint, fall back to a secondary if the first fails/empties.
export function useHQDataWithFallback<T = any>(
  primary: string,
  fallback: string,
  pollMs = 60_000,
): HQResult<T> {
  const a = useHQData<T>(primary, pollMs)
  const b = useHQData<T>(fallback, pollMs)
  if (a.data) return a
  if (a.error && (b.data || !b.loading)) return b
  return a.loading ? a : b
}

// ── Formatting helpers (graceful: numbers → "--", never NaN) ──────────
export const fmtUSD = (n: number | null | undefined, dp = 0): string =>
  n == null || Number.isNaN(n)
    ? '--'
    : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: dp, maximumFractionDigits: dp })

export const fmtNum = (n: number | null | undefined, dp = 2): string =>
  n == null || Number.isNaN(n) ? '--' : n.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })

export const fmtPct = (n: number | null | undefined, dp = 1): string =>
  n == null || Number.isNaN(n) ? '--' : `${n >= 0 ? '+' : ''}${n.toFixed(dp)}%`

export const fmtSigned = (n: number | null | undefined): string =>
  n == null || Number.isNaN(n) ? '--' : `${n >= 0 ? '+' : '−'}${fmtUSD(Math.abs(n))}`

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '--'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '--'
  const s = Math.floor((Date.now() - then) / 1000)
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}
