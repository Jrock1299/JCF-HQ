// Deterministic helpers — no Math.random (stable across renders/SSR).

// Seeded pseudo-random series for sparklines when we don't have real history.
export function series(seed: number, len = 16, trendUp = true): number[] {
  const out: number[] = []
  let v = 100
  let s = seed
  for (let i = 0; i < len; i++) {
    s = (s * 1103515245 + 12345) & 0x7fffffff
    const noise = ((s / 0x7fffffff) - 0.5) * 8
    const drift = trendUp ? 1.1 : -0.6
    v = Math.max(20, v + drift + noise)
    out.push(Number(v.toFixed(2)))
  }
  return out
}

// Monthly trajectory toward a target for area charts.
export function trajectory(start: number, end: number, months = 12): { m: string; v: number }[] {
  const labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const out: { m: string; v: number }[] = []
  for (let i = 0; i < months; i++) {
    const t = i / (months - 1)
    // ease-in curve so it accelerates toward the target
    const eased = t * t
    const wobble = Math.sin(i * 1.7) * (end - start) * 0.012
    out.push({ m: labels[i % 12], v: Math.round(start + (end - start) * eased + wobble) })
  }
  return out
}

export interface BladeTrade {
  trade_id: string
  session: string
  instrument: string
  direction: string
  entry_price: number
  close_price: number
  stop_loss: number
  timestamp_close: string
  r: number
  pnlSign: 'win' | 'loss'
}

// blade_learning_log has no P&L field. Compute R = reward/risk where
// risk = |entry - stop| and reward is signed by direction. Win = R > 0.
export function computeBladeTrades(records: any[]): BladeTrade[] {
  if (!Array.isArray(records)) return []
  return records
    .map((rec) => {
      const entry = Number(rec.entry_price)
      const close = Number(rec.close_price)
      const stop = Number(rec.stop_loss)
      const dir = String(rec.direction || '').toLowerCase()
      const risk = Math.abs(entry - stop)
      let r = 0
      if (risk > 0 && Number.isFinite(entry) && Number.isFinite(close)) {
        const reward = dir.includes('short') || dir.includes('sell') ? entry - close : close - entry
        r = reward / risk
      }
      return {
        trade_id: String(rec.trade_id ?? ''),
        session: String(rec.session ?? '—'),
        instrument: String(rec.instrument ?? '—'),
        direction: dir.includes('short') || dir.includes('sell') ? 'SHORT' : 'LONG',
        entry_price: entry,
        close_price: close,
        stop_loss: stop,
        timestamp_close: String(rec.timestamp_close ?? rec.timestamp_entry ?? ''),
        r: Number(r.toFixed(2)),
        pnlSign: r >= 0 ? 'win' : 'loss',
      } as BladeTrade
    })
    .filter((t) => Number.isFinite(t.entry_price))
    .reverse() // most recent first
}

export function bladeWinRate(trades: BladeTrade[]): number | null {
  if (!trades.length) return null
  const wins = trades.filter((t) => t.pnlSign === 'win').length
  return (wins / trades.length) * 100
}
