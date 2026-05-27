/**
 * Intelligence — Daily brief, macro desk, forex/sports intel, insider intelligence
 * Data: market_bias.json, sports_intel.json, sentinel_data.json
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { getMarketBias } from '../api/client.js'
import { useIsMobile } from '../hooks/useIsMobile.js'

const POLL_MS = 60_000

async function getSportsIntel() {
  const r = await fetch('/sports_intel.json')
  if (!r.ok) return []
  return r.json()
}

async function getSentinelData() {
  const r = await fetch(`/sentinel_data.json?t=${Date.now()}`)
  if (!r.ok) return null
  return r.json()
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtValue(v) {
  if (!v || v === 0) return '—'
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${Math.round(v / 1_000)}k`
  return `$${Math.round(v)}`
}

function fmtDate(d) {
  if (!d) return '—'
  try { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' }) }
  catch { return String(d).slice(0, 10) }
}

function fmtTimestamp(d) {
  if (!d) return ''
  try { return new Date(d).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return String(d).slice(0, 16) }
}

// ── Signal badge config ───────────────────────────────────────────────────────

const SIGNAL_BADGE = {
  STRONG_BUY:  { label: 'STRONG BUY',  bg: 'rgba(212,168,67,0.15)', bd: 'rgba(212,168,67,0.4)', col: '#d4a843', pulse: true },
  BUY:         { label: 'BUY',         bg: 'rgba(74,222,128,0.12)', bd: 'rgba(74,222,128,0.3)', col: '#4ade80', pulse: false },
  SELL:        { label: 'SELL',        bg: 'rgba(248,113,113,0.12)',bd: 'rgba(248,113,113,0.3)',col: '#f87171', pulse: false },
  MIXED:       { label: 'MIXED',       bg: 'rgba(255,255,255,0.06)',bd: 'rgba(255,255,255,0.15)',col: 'rgba(255,255,255,0.45)', pulse: false },
  neutral:     { label: 'NEUTRAL',     bg: 'rgba(255,255,255,0.04)',bd: 'rgba(255,255,255,0.1)', col: 'rgba(255,255,255,0.3)', pulse: false },
  CLUSTER_BUY: { label: 'CLUSTER BUY', bg: 'rgba(212,168,67,0.15)', bd: 'rgba(212,168,67,0.4)', col: '#d4a843', pulse: true },
  MULTI_BUY:   { label: 'MULTI BUY',   bg: 'rgba(74,222,128,0.12)', bd: 'rgba(74,222,128,0.3)', col: '#4ade80', pulse: false },
  INSIDER_BUY: { label: 'INSIDER BUY', bg: 'rgba(96,165,250,0.12)', bd: 'rgba(96,165,250,0.3)', col: '#60a5fa', pulse: false },
}

const CAT_COLORS = {
  holdings:      { bg: 'rgba(212,168,67,0.12)',  col: '#d4a843' },
  quantum_nuclear:{ bg: 'rgba(167,139,250,0.12)', col: '#a78bfa' },
  energy:        { bg: 'rgba(251,146,60,0.12)',  col: '#fb923c' },
  metals:        { bg: 'rgba(148,163,184,0.12)', col: '#94a3b8' },
  robotics_ai:   { bg: 'rgba(34,211,238,0.12)',  col: '#22d3ee' },
  saudi:         { bg: 'rgba(74,222,128,0.12)',  col: '#4ade80' },
  tech_semis:    { bg: 'rgba(96,165,250,0.12)',  col: '#60a5fa' },
}

function SignalBadge({ type, style = {} }) {
  const cfg = SIGNAL_BADGE[type] || SIGNAL_BADGE.neutral
  return (
    <span className={cfg.pulse ? 'sentinel-pulse' : ''} style={{
      fontSize: 8, padding: '2px 7px', borderRadius: 4,
      background: cfg.bg, border: `1px solid ${cfg.bd}`, color: cfg.col,
      textTransform: 'uppercase', letterSpacing: 1.2, fontFamily: '"IBM Plex Mono",monospace',
      whiteSpace: 'nowrap', ...style
    }}>
      {cfg.label}
    </span>
  )
}

function CatBadge({ cat }) {
  const cfg = CAT_COLORS[cat] || { bg: 'rgba(255,255,255,0.06)', col: 'rgba(255,255,255,0.4)' }
  const label = (cat || '').replace(/_/g, ' ')
  return (
    <span style={{
      fontSize: 8, padding: '2px 6px', borderRadius: 3,
      background: cfg.bg, color: cfg.col,
      textTransform: 'uppercase', letterSpacing: 1, fontFamily: '"IBM Plex Mono",monospace',
    }}>
      {label}
    </span>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function LensCalcSection({ calc }) {
  const [open, setOpen] = useState(false)
  if (!calc) return null
  const summary = calc.analysis || calc.summary || calc.note || null
  const entries = calc.key_levels || calc.signals || calc.factors || null
  return (
    <div style={{ marginTop: 8, borderTop: '1px solid rgba(201,168,76,0.12)', paddingTop: 8 }}>
      <button onClick={e => { e.stopPropagation(); setOpen(v => !v) }}
        style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
        <span style={{ fontSize: 8, padding: '1px 6px', borderRadius: 3, background: 'rgba(201,168,76,0.1)', color: 'var(--gold)', border: '1px solid rgba(201,168,76,0.2)', textTransform: 'uppercase', letterSpacing: 1 }}>
          {open ? '▾' : '▸'} Lens's Calculation
        </span>
      </button>
      {open && (
        <div style={{ marginTop: 8, padding: '10px 12px', background: 'rgba(201,168,76,0.04)', borderRadius: 6, border: '1px solid rgba(201,168,76,0.1)' }}>
          {calc.direction && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1 }}>Direction</span>
              <span style={{ fontSize: 10, color: calc.direction?.toLowerCase().includes('bull') ? 'var(--green)' : calc.direction?.toLowerCase().includes('bear') ? 'var(--red)' : 'var(--gold)', fontFamily: '"IBM Plex Mono",monospace' }}>{calc.direction}</span>
            </div>
          )}
          {summary && <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: entries ? 8 : 0 }}>{summary}</div>}
          {entries && Array.isArray(entries) && entries.map((en, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 10, color: 'var(--text-muted)', borderTop: i === 0 ? '1px solid rgba(255,255,255,0.04)' : 'none' }}>
              <span>{en.label || en.name || en}</span>
              {en.value != null && <span style={{ color: 'var(--gold)', fontFamily: '"IBM Plex Mono",monospace' }}>{en.value}</span>}
            </div>
          ))}
          {calc.beat_scenario && (
            <div style={{ marginTop: 6 }}>
              <div style={{ fontSize: 9, color: 'var(--green)', marginBottom: 2 }}>Beat: {calc.beat_scenario}</div>
              {calc.miss_scenario && <div style={{ fontSize: 9, color: 'var(--red)' }}>Miss: {calc.miss_scenario}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function WatchlistCard({ sig, isMobile, lensCalc }) {
  const [expanded, setExpanded] = useState(false)
  const hasInsiders = sig.insiders?.length > 0
  return (
    <div className="glass" style={{ padding: '14px 16px', cursor: hasInsiders ? 'pointer' : 'default' }}
      onClick={() => hasInsiders && setExpanded(e => !e)}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 15, color: 'var(--text-primary)', fontWeight: 600 }}>
            {sig.symbol}
          </span>
          <CatBadge cat={sig.category} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <SignalBadge type={sig.signal_type} />
          <span style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: 'var(--gold)', fontWeight: 700, lineHeight: 1 }}>
            {sig.score}
          </span>
        </div>
      </div>

      {/* Stats row */}
      <div style={{ display: 'flex', gap: 16, marginBottom: expanded ? 10 : 0 }}>
        <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
          <span style={{ color: '#4ade80', fontWeight: 600 }}>↑{sig.buy_count}</span>
          <span style={{ margin: '0 4px', opacity: 0.4 }}>|</span>
          <span style={{ color: '#f87171', fontWeight: 600 }}>↓{sig.sell_count}</span>
        </div>
        {sig.total_buy_value > 0 && (
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            <span style={{ color: '#4ade80' }}>{fmtValue(sig.total_buy_value)}</span>
            <span style={{ opacity: 0.5 }}> bought</span>
          </div>
        )}
        {sig.latest_date && (
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 'auto', fontFamily: '"IBM Plex Mono",monospace' }}>
            {fmtDate(sig.latest_date)}
          </div>
        )}
      </div>

      {/* Insiders expanded */}
      {expanded && hasInsiders && (
        <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: 8 }}>
          {sig.insiders.map((ins, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 5, height: 5, borderRadius: '50%', background: ins.type === 'BUY' ? '#4ade80' : ins.type === 'SELL' ? '#f87171' : 'rgba(255,255,255,0.2)', flexShrink: 0, display: 'inline-block' }} />
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{ins.name || 'Unknown'}</span>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
                {ins.value > 0 && <span style={{ fontSize: 9, color: ins.type === 'BUY' ? '#4ade80' : '#f87171', fontFamily: '"IBM Plex Mono",monospace' }}>{fmtValue(ins.value)}</span>}
                {ins.date && <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.25)', fontFamily: '"IBM Plex Mono",monospace' }}>{fmtDate(ins.date)}</span>}
              </div>
            </div>
          ))}
          {hasInsiders && <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', marginTop: 4 }}>tap to collapse</div>}
        </div>
      )}
      {!expanded && hasInsiders && (
        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', marginTop: 4 }}>tap to expand insiders</div>
      )}
      <LensCalcSection calc={lensCalc} />
    </div>
  )
}

function DiscoveryCard({ disc, lensCalc }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="glass" style={{ padding: '14px 16px', cursor: 'pointer', borderLeft: '2px solid rgba(96,165,250,0.3)' }}
      onClick={() => setExpanded(e => !e)}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 14, color: 'var(--text-primary)', fontWeight: 600 }}>
            {disc.symbol}
          </span>
          <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', fontStyle: 'italic' }}>off-watchlist</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <SignalBadge type={disc.signal_type} />
          <span style={{ fontFamily: '"Playfair Display",serif', fontSize: 16, color: disc.signal_type === 'CLUSTER_BUY' ? 'var(--gold)' : 'var(--text-primary)', fontWeight: 700 }}>
            {disc.score}
          </span>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 14, fontSize: 10, color: 'var(--text-muted)' }}>
        <span><span style={{ color: '#4ade80', fontWeight: 600 }}>↑{disc.buy_count}</span> buy{disc.buy_count !== 1 ? 's' : ''}</span>
        {disc.total_value > 0 && <span style={{ color: '#60a5fa' }}>{fmtValue(disc.total_value)}</span>}
        {disc.latest_date && <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 9, marginLeft: 'auto' }}>{fmtDate(disc.latest_date)}</span>}
      </div>
      {expanded && disc.insiders?.length > 0 && (
        <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: 8 }}>
          {disc.insiders.map((ins, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 10, color: 'var(--text-muted)' }}>
              <span>{ins.name || 'Unknown'}</span>
              <span style={{ color: '#60a5fa', fontFamily: '"IBM Plex Mono",monospace' }}>{fmtValue(ins.value)}</span>
            </div>
          ))}
        </div>
      )}
      <LensCalcSection calc={lensCalc} />
    </div>
  )
}

function AnalystBar({ rec }) {
  const total = (rec.strongBuy || 0) + (rec.buy || 0) + (rec.hold || 0) + (rec.sell || 0) + (rec.strongSell || 0)
  if (total === 0) return null
  const pct = n => `${Math.round((n / total) * 100)}%`
  const segments = [
    { val: rec.strongBuy || 0,  col: '#15803d', label: 'SB' },
    { val: rec.buy || 0,        col: '#4ade80', label: 'B'  },
    { val: rec.hold || 0,       col: 'rgba(255,255,255,0.2)', label: 'H' },
    { val: rec.sell || 0,       col: '#fb923c', label: 'S'  },
    { val: rec.strongSell || 0, col: '#f87171', label: 'SS' },
  ].filter(s => s.val > 0)

  const bullish = (rec.strongBuy || 0) + (rec.buy || 0)
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5 }}>
        <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: 'var(--text-primary)' }}>{rec.symbol}</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 9, color: '#4ade80', fontFamily: '"IBM Plex Mono",monospace' }}>{bullish} buy</span>
          {rec.hold > 0 && <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', fontFamily: '"IBM Plex Mono",monospace' }}>{rec.hold} hold</span>}
          {(rec.sell + (rec.strongSell || 0)) > 0 && <span style={{ fontSize: 9, color: '#fb923c', fontFamily: '"IBM Plex Mono",monospace' }}>{rec.sell + (rec.strongSell || 0)} sell</span>}
        </div>
      </div>
      <div style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', gap: 1 }}>
        {segments.map((s, i) => (
          <div key={i} style={{ width: pct(s.val), background: s.col, minWidth: s.val > 0 ? 3 : 0 }} title={`${s.label}: ${s.val}`} />
        ))}
      </div>
    </div>
  )
}

function EarningsRow({ e, i, total, onWatchlist, lensCalc }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ borderBottom: i < total - 1 ? '1px solid rgba(255,255,255,0.03)' : 'none' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 0', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {onWatchlist && <span style={{ color: 'var(--gold)', fontSize: 10 }}>★</span>}
          <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, color: onWatchlist ? 'var(--gold)' : 'var(--text-primary)' }}>{e.symbol}</span>
          {e.epsEstimate != null && (
            <span style={{ fontSize: 12, color: 'var(--gold)', fontFamily: '"IBM Plex Mono",monospace', fontWeight: 600 }}>
              est. {e.epsEstimate > 0 ? '+' : ''}{e.epsEstimate}
            </span>
          )}
          {lensCalc && (
            <button onClick={() => setOpen(v => !v)}
              style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(201,168,76,0.1)', color: 'var(--gold)', border: '1px solid rgba(201,168,76,0.2)', cursor: 'pointer', textTransform: 'uppercase', letterSpacing: 0.8 }}>
              {open ? '▾' : '▸'} Lens
            </button>
          )}
        </div>
        <span style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{fmtDate(e.date)}</span>
      </div>
      {open && lensCalc && (
        <div style={{ padding: '8px 12px', marginBottom: 6, background: 'rgba(201,168,76,0.04)', borderRadius: 6, border: '1px solid rgba(201,168,76,0.1)' }}>
          {lensCalc.direction && (
            <div style={{ fontSize: 10, color: lensCalc.direction?.toLowerCase().includes('bull') ? 'var(--green)' : 'var(--red)', marginBottom: 4, fontFamily: '"IBM Plex Mono",monospace' }}>
              Direction: {lensCalc.direction}
            </div>
          )}
          {lensCalc.analysis && <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 4 }}>{lensCalc.analysis}</div>}
          {lensCalc.beat_scenario && <div style={{ fontSize: 10, color: 'var(--green)', marginBottom: 2 }}>Beat: {lensCalc.beat_scenario}</div>}
          {lensCalc.miss_scenario && <div style={{ fontSize: 10, color: 'var(--red)' }}>Miss: {lensCalc.miss_scenario}</div>}
        </div>
      )}
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function Intelligence({ demoMode, isActive = true }) {
  const isMobile = useIsMobile()
  const [bias,     setBias]     = useState(null)
  const [sports,   setSports]   = useState([])
  const [sentinel, setSentinel] = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [tab,      setTab]      = useState('forex')
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const [mb, sp, sn] = await Promise.allSettled([getMarketBias(), getSportsIntel(), getSentinelData()])
      if (mb.status === 'fulfilled') setBias(mb.value)
      if (sp.status === 'fulfilled') setSports(Array.isArray(sp.value) ? sp.value : [])
      if (sn.status === 'fulfilled') setSentinel(sn.value)
    } catch (e) { console.error('[Intelligence]', e) } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!isActive) { clearInterval(timer.current); return }
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [isActive, load])

  const TABS = ['Forex', 'Sports', 'Markets', 'Crypto']

  const watchlistSignals = sentinel?.watchlist_signals || []
  const discoveries      = sentinel?.top_discoveries   || []
  const analystRecs      = sentinel?.analyst_recommendations || []
  const earnings         = sentinel?.earnings_calendar  || []
  const news             = sentinel?.market_news        || []
  const watchlistEarnings= sentinel?.watchlist_earnings || []
  const watchlistSet     = new Set(Object.values(sentinel?.watchlist_config || {}).flat())

  // Lens calculation lookup maps (from market_bias.json)
  const toCalcMap = (val) => {
    if (!val) return {}
    if (Array.isArray(val)) { const m = {}; val.forEach(c => { if (c?.symbol) m[c.symbol] = c }); return m }
    return val
  }
  const watchlistCalcMap = toCalcMap(bias?.watchlist_calculations)
  const discoveryCalcMap = toCalcMap(bias?.discovery_calculations)
  const earningsCalcMap  = toCalcMap(bias?.earnings_calculations)

  return (
    <div>
      {/* pulse keyframes injected once */}
      <style>{`
        @keyframes sentinelPulse {
          0%,100% { box-shadow: 0 0 0 0 rgba(212,168,67,0); }
          50%      { box-shadow: 0 0 6px 2px rgba(212,168,67,0.35); }
        }
        .sentinel-pulse { animation: sentinelPulse 2.2s ease-in-out infinite; }
      `}</style>

      <h1 className="page-title">Intelligence Feed</h1>

      {/* ── Daily brief ───────────────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Daily Brief</h3><div className="section-line" /></div>
      <div className="glass" style={{ border: '1px solid rgba(201,168,76,0.2)', position: 'relative', overflow: 'hidden', marginBottom: 4 }}>
        <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg,var(--gold),transparent)' }} />
        <div style={{ padding: '18px 22px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={{ fontFamily: '"Playfair Display",serif', fontSize: 17, color: 'var(--text-primary)' }}>Intelligence Summary</span>
            {bias?.last_updated && <span style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{bias.last_updated}</span>}
          </div>
          {loading
            ? <div className="space-y-2">{[80, 65, 90, 55, 70].map((w, i) => <div key={i} className="animate-pulse-slow" style={{ height: 12, width: `${w}%`, background: 'rgba(255,255,255,0.04)', borderRadius: 4 }} />)}</div>
            : bias?.summary
              ? <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.8 }} dangerouslySetInnerHTML={{ __html: bias.summary }} />
              : bias?.morning_report
                ? <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.8 }} dangerouslySetInnerHTML={{ __html: bias.morning_report }} />
                : <div style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>No brief available.</div>
          }
        </div>
      </div>

      {/* ── Market Impact Analysis ───────────────────────────────────────── */}
      {!loading && bias?.market_impact?.length > 0 && (
        <>
          <div className="section-head"><div className="section-line" /><h3>Market Impact Analysis</h3><div className="section-line" /></div>
          <div className="glass" style={{ padding: '4px 18px', marginBottom: 4 }}>
            {bias.market_impact.map((item, i) => {
              const symbol    = item.symbol || item.pair || item.asset
              const direction = item.impact_direction || item.direction
              const analysis  = item.impact_analysis || item.reasoning || item.analysis
              const event     = item.event
              const dLow      = (direction || '').toLowerCase()
              return (
                <div key={i} style={{ padding: '10px 0', borderBottom: i < bias.market_impact.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5, flexWrap: 'wrap' }}>
                    <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: 'var(--gold)', fontWeight: 600 }}>{symbol}</span>
                    {direction && (
                      <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 3,
                        background: dLow.includes('bull') ? 'rgba(74,222,128,0.1)' : dLow.includes('bear') ? 'rgba(248,113,113,0.1)' : 'rgba(255,255,255,0.06)',
                        color:      dLow.includes('bull') ? 'var(--green)'        : dLow.includes('bear') ? 'var(--red)'            : 'var(--text-muted)',
                        textTransform: 'uppercase', letterSpacing: 1 }}>
                        {direction}
                      </span>
                    )}
                    {event && <span style={{ fontSize: 10, color: 'var(--text-muted)', fontStyle: 'italic' }}>{event}</span>}
                  </div>
                  {analysis && <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6 }}>{analysis}</div>}
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* ── Macro desk ────────────────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Macro Desk — Lens Report</h3><div className="section-line" /></div>
      {loading
        ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 10, marginBottom: 4 }}>{[1, 2, 3, 4].map(i => <div key={i} className="glass animate-pulse-slow" style={{ height: 110 }} />)}</div>
        : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 10, marginBottom: 4 }}>
              {['BTC/USDT', 'XAU/USD', 'US100', 'US OIL'].map((sym, i) => {
                const rawPair = bias?.pairs?.find(p => p.symbol === sym)
                const p = rawPair || { symbol: sym, bias: 'neutral', confidence: null, note: 'Awaiting next Lens run — updates daily at 04:55 UTC' };
                const isBull = (p.bias || '').toLowerCase() === 'bullish'
                const isBear = (p.bias || '').toLowerCase() === 'bearish'
                const biasColor = isBull ? 'var(--green)' : isBear ? 'var(--red)' : 'var(--text-muted)'
                const biasBg    = isBull ? 'rgba(74,222,128,0.1)' : isBear ? 'rgba(248,113,113,0.1)' : 'rgba(255,255,255,0.04)'
                const barFill   = isBull ? 'var(--green)' : isBear ? 'var(--red)' : 'rgba(255,255,255,0.15)'
                const conf = rawPair ? (parseFloat(p.confidence) || 50) : 0
                return (
                  <div key={i} className="glass" style={{ padding: '14px 16px', opacity: rawPair ? 1 : 0.65 }}>
                    <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 16, color: 'var(--text-primary)', marginBottom: 6 }}>{p.symbol}</div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                      <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: biasBg, color: biasColor, textTransform: 'uppercase', letterSpacing: 1 }}>{p.bias || 'neutral'}</span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{rawPair ? `${p.confidence ?? '—'}%` : '—'}</span>
                    </div>
                    {p.note && <div style={{ fontSize: 11, color: rawPair ? 'var(--text-muted)' : 'rgba(255,255,255,0.3)', marginBottom: 8, lineHeight: 1.4, fontStyle: rawPair ? 'normal' : 'italic' }}>{p.note}</div>}
                    <div style={{ height: 4, background: 'rgba(255,255,255,0.04)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${conf}%`, background: barFill, borderRadius: 2, boxShadow: `0 0 8px ${barFill}40` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          )
      }

      {/* ── Intel feed (tabbed) ───────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Intelligence Feed</h3><div className="section-line" /></div>
      <div className="glass">
        <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.06)', padding: '0 16px' }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t.toLowerCase())}
              style={{ padding: '12px 16px', fontSize: 11, cursor: 'pointer', background: 'transparent', border: 'none', borderBottom: tab === t.toLowerCase() ? '2px solid var(--gold)' : '2px solid transparent', color: tab === t.toLowerCase() ? 'var(--gold)' : 'var(--text-muted)', transition: 'all .15s', marginBottom: -1 }}>
              {t}
            </button>
          ))}
        </div>
        <div style={{ padding: '14px 18px', minHeight: 120 }}>
          {tab === 'forex' && (
            !loading && bias?.forex_news?.length
              ? bias.forex_news.map((n, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '11px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: n.impact === 'high' ? 'var(--red)' : n.impact === 'medium' ? 'var(--gold)' : 'rgba(255,255,255,0.15)', marginTop: 5, flexShrink: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-primary)', marginBottom: 3 }}>{n.headline || n.title || ''}</div>
                    <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{n.time || n.date || ''}{n.source ? ` · ${n.source}` : ''}</div>
                  </div>
                </div>
              ))
              : <EmptyPanel loading={loading} />
          )}
          {tab === 'sports' && (
            sports.length
              ? sports.map((g, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '10px 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-primary)' }}>{g.game || '-'}</div>
                    <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{g.time || ''}{g.sport ? ` · ${g.sport}` : ''}</div>
                  </div>
                  <div style={{ textAlign: 'right', fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--text-muted)' }}>{g.spread || ''}</div>
                </div>
              ))
              : <EmptyPanel loading={loading} />
          )}
          {tab === 'markets' && (
            !loading && bias?.markets_feed?.length
              ? bias.markets_feed.map((n, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '11px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: n.impact === 'high' ? 'var(--red)' : n.impact === 'medium' ? 'var(--gold)' : 'rgba(255,255,255,0.15)', marginTop: 5, flexShrink: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-primary)', marginBottom: 3 }}>{n.headline || n.title || ''}</div>
                    <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{n.time || n.date || ''}{n.source ? ` · ${n.source}` : ''}</div>
                  </div>
                </div>
              ))
              : <EmptyPanel loading={loading} />
          )}
          {tab === 'crypto' && (
            !loading && bias?.crypto_feed?.length
              ? bias.crypto_feed.map((n, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '11px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: n.impact === 'high' ? 'var(--red)' : n.impact === 'medium' ? 'var(--gold)' : 'rgba(255,255,255,0.15)', marginTop: 5, flexShrink: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-primary)', marginBottom: 3 }}>{n.headline || n.title || ''}</div>
                    <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{n.time || n.date || ''}{n.source ? ` · ${n.source}` : ''}</div>
                  </div>
                </div>
              ))
              : <EmptyPanel loading={loading} />
          )}
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* ── INSIDER INTELLIGENCE ─────────────────────────────────────────── */}
      {/* ═══════════════════════════════════════════════════════════════════ */}

      <div className="section-head" style={{ marginTop: 28 }}>
        <div className="section-line" />
        <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap' }}>
          <span>Insider Intelligence</span>
          <span style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace', fontWeight: 400 }}>
            {sentinel ? `— Sentinel · ${fmtTimestamp(sentinel.last_updated)}` : ''}
          </span>
        </h3>
        <div className="section-line" />
      </div>

      {/* No data fallback */}
      {!loading && !sentinel && (
        <div className="glass" style={{ padding: '20px 22px', border: '1px solid rgba(212,168,67,0.15)' }}>
          <div style={{ fontSize: 13, color: 'var(--gold)', marginBottom: 6 }}>Sentinel pipeline not configured.</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.7 }}>
            Run <code style={{ fontFamily: '"IBM Plex Mono",monospace', background: 'rgba(255,255,255,0.06)', padding: '1px 5px', borderRadius: 3 }}>sentinel_sync.py</code> to start pulling insider data.
          </div>
        </div>
      )}

      {loading && !sentinel && (
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2,1fr)', gap: 10 }}>
          {[1, 2, 3, 4].map(i => <div key={i} className="glass animate-pulse-slow" style={{ height: 80 }} />)}
        </div>
      )}

      {sentinel && (
        <>
          {/* Summary strip */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
            {[
              { label: 'STRONG BUYS', val: sentinel.summary?.watchlist_strong_buys ?? 0, col: '#d4a843' },
              { label: 'BUY SIGNALS', val: sentinel.summary?.watchlist_buys ?? 0, col: '#4ade80' },
              { label: 'DISCOVERIES', val: sentinel.summary?.discoveries_found ?? 0, col: '#60a5fa' },
              { label: 'MKT TXS SCANNED', val: sentinel.summary?.total_market_txs ?? 0, col: 'rgba(255,255,255,0.4)' },
            ].map(s => (
              <div key={s.label} className="glass" style={{ padding: '10px 14px', flex: '1 1 auto', minWidth: 90 }}>
                <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 20, color: s.col, fontWeight: 700, lineHeight: 1 }}>{s.val}</div>
                <div style={{ fontSize: 8, color: 'var(--text-muted)', marginTop: 4, letterSpacing: 1, textTransform: 'uppercase' }}>{s.label}</div>
              </div>
            ))}
          </div>

          {/* ── Watchlist Signals ──────────────────────────────────────────── */}
          {watchlistSignals.length > 0 && (
            <>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1.5, marginBottom: 8, fontFamily: '"IBM Plex Mono",monospace' }}>
                Watchlist Signals — {watchlistSignals.length} tickers
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2,1fr)', gap: 10, marginBottom: 20 }}>
                {watchlistSignals.map((sig, i) => (
                  <WatchlistCard key={sig.symbol || i} sig={sig} isMobile={isMobile} lensCalc={watchlistCalcMap[sig.symbol]} />
                ))}
              </div>
            </>
          )}

          {/* ── Discovery Scan ─────────────────────────────────────────────── */}
          {discoveries.length > 0 && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1.5, fontFamily: '"IBM Plex Mono",monospace' }}>
                  ◎ Discovery Scan — Institutional Moves
                </span>
                <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', fontStyle: 'italic' }}>not on watchlist · potential new opportunities</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2,1fr)', gap: 10, marginBottom: 20 }}>
                {discoveries.map((disc, i) => <DiscoveryCard key={disc.symbol || i} disc={disc} lensCalc={discoveryCalcMap[disc.symbol]} />)}
              </div>
            </>
          )}

          {/* ── Analyst Consensus ─────────────────────────────────────────── */}
          {analystRecs.length > 0 && (
            <>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1.5, marginBottom: 8, fontFamily: '"IBM Plex Mono",monospace' }}>
                Analyst Consensus
              </div>
              <div className="glass" style={{ padding: '14px 18px', marginBottom: 20 }}>
                <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2,1fr)', gap: '4px 24px' }}>
                  {analystRecs.map((rec, i) => <AnalystBar key={rec.symbol || i} rec={rec} />)}
                </div>
                <div style={{ display: 'flex', gap: 14, marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                  {[
                    { col: '#15803d', label: 'Strong Buy' }, { col: '#4ade80', label: 'Buy' },
                    { col: 'rgba(255,255,255,0.2)', label: 'Hold' }, { col: '#fb923c', label: 'Sell' }, { col: '#f87171', label: 'Strong Sell' },
                  ].map(l => (
                    <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <div style={{ width: 8, height: 8, borderRadius: 2, background: l.col, flexShrink: 0 }} />
                      <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{l.label}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Consensus Top 3 */}
              {bias?.consensus_top3?.length > 0 && (
                <div className="glass" style={{ padding: '14px 18px', marginTop: 10, borderLeft: '2px solid rgba(201,168,76,0.3)' }}>
                  <div style={{ fontSize: 9, color: 'var(--gold)', textTransform: 'uppercase', letterSpacing: 1.5, marginBottom: 10, fontFamily: '"IBM Plex Mono",monospace' }}>
                    Lens's Top 3 Consensus Picks
                  </div>
                  {bias.consensus_top3.map((pick, i) => {
                    const sym    = pick.symbol || pick.ticker
                    const dir    = pick.direction || pick.action
                    const reason = pick.reason || pick.reasoning
                    const dLow   = (dir || '').toLowerCase()
                    const dirCol = dLow.includes('bull') || dLow.includes('buy')
                      ? 'var(--green)'
                      : dLow.includes('bear') || dLow.includes('sell')
                        ? 'var(--red)'
                        : 'var(--gold)'
                    return (
                      <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '7px 0', borderBottom: i < bias.consensus_top3.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none' }}>
                        <span style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: 'var(--gold)', fontWeight: 700, lineHeight: 1, flexShrink: 0, width: 20, textAlign: 'center' }}>{i + 1}</span>
                        <div style={{ flex: 1 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                            <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: 'var(--text-primary)', fontWeight: 600 }}>{sym}</span>
                            {dir && <span style={{ fontSize: 9, color: dirCol, textTransform: 'uppercase', letterSpacing: 0.8 }}>{dir}</span>}
                          </div>
                          {reason && <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{reason}</div>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </>
          )}

          {/* ── Upcoming Earnings ─────────────────────────────────────────── */}
          {earnings.length > 0 && (
            <>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1.5, marginBottom: 8, fontFamily: '"IBM Plex Mono",monospace' }}>
                Upcoming Earnings (7 days)
              </div>
              <div className="glass" style={{ padding: '4px 18px', marginBottom: 20 }}>
                {earnings.slice(0, 20).map((e, i) => (
                  <EarningsRow
                    key={i} e={e} i={i} total={Math.min(earnings.length, 20)}
                    onWatchlist={watchlistSet.has(e.symbol)}
                    lensCalc={earningsCalcMap[e.symbol]}
                  />
                ))}
              </div>
            </>
          )}

          {/* ── Market News ───────────────────────────────────────────────── */}
          {news.length > 0 && (
            <>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1.5, marginBottom: 8, fontFamily: '"IBM Plex Mono",monospace' }}>
                Market News
              </div>
              <div className="glass" style={{ padding: '4px 18px', marginBottom: 4 }}>
                {news.map((n, i) => (
                  <div key={i} style={{ padding: '11px 0', borderBottom: i < news.length - 1 ? '1px solid rgba(255,255,255,0.03)' : 'none' }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, marginBottom: 4 }}>
                      {n.url
                        ? <a href={n.url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: 'var(--text-primary)', textDecoration: 'none', lineHeight: 1.4, flex: 1 }}
                            onMouseEnter={e => e.currentTarget.style.color = 'var(--gold)'}
                            onMouseLeave={e => e.currentTarget.style.color = 'var(--text-primary)'}
                          >{n.headline}</a>
                        : <span style={{ fontSize: 12, color: 'var(--text-primary)', lineHeight: 1.4, flex: 1 }}>{n.headline}</span>
                      }
                      {n.related && watchlistSet.has(n.related) && (
                        <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 3, background: 'rgba(212,168,67,0.12)', color: 'var(--gold)', fontFamily: '"IBM Plex Mono",monospace', flexShrink: 0 }}>
                          {n.related}
                        </span>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                      {n.source && <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', fontFamily: '"IBM Plex Mono",monospace' }}>{n.source}</span>}
                      {n.datetime && (
                        <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', fontFamily: '"IBM Plex Mono",monospace' }}>
                          {typeof n.datetime === 'number' ? fmtTimestamp(new Date(n.datetime * 1000)) : fmtTimestamp(n.datetime)}
                        </span>
                      )}
                      {n.related && !watchlistSet.has(n.related) && n.related !== '' && (
                        <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', fontFamily: '"IBM Plex Mono",monospace' }}>{n.related}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}

function EmptyPanel({ loading, msg }) {
  if (loading) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {[80, 65].map((w, i) => <div key={i} className="animate-pulse-slow" style={{ height: 12, width: `${w}%`, background: 'rgba(255,255,255,0.04)', borderRadius: 4 }} />)}
    </div>
  )
  return <div style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>{msg || 'No data available.'}</div>
}
