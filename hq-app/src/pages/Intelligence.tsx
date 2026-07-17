import { useState } from 'react'
import GlassCard from '../components/GlassCard'
import { useHQData, fmtNum } from '../hooks/useHQData'

/**
 * Intelligence — adapted from the pre-v3 Intelligence.jsx layout (commit
 * e91d5e8) into the v3 visual system: section-divider headings, single-column
 * scroll, Daily Brief, Macro Desk (Lens report), tabbed news feed, and the
 * Insider Intelligence (Sentinel) block. Content: Lens briefing, instrument
 * bias, news, Jarvis regime, Sentinel signals. Styling: v3 gold + League
 * Spartan + JetBrains Mono (was Playfair / IBM Plex / DM Sans).
 */

// ── helpers ───────────────────────────────────────────────────────────
function fmtValue(v: any): string {
  const n = Number(v)
  if (!n || Number.isNaN(n)) return '—'
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${Math.round(n / 1000)}k`
  return `$${Math.round(n)}`
}
function fmtDate(d: any): string {
  if (!d) return '—'
  const dt = new Date(d)
  return Number.isNaN(dt.getTime()) ? String(d).slice(0, 10) : dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' })
}
function fmtTs(d: any): string {
  if (!d) return ''
  const dt = new Date(d)
  return Number.isNaN(dt.getTime()) ? String(d).slice(0, 16) : dt.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
function cap(s: string) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s }

function Divider({ children, meta }: { children: React.ReactNode; meta?: string }) {
  return (
    <div className="section-head">
      <div className="section-line" />
      <h3>{children}{meta && <span style={{ color: 'var(--text-mute)', letterSpacing: '0.04em' }}>· {meta}</span>}</h3>
      <div className="section-line" />
    </div>
  )
}

const SIGNAL: Record<string, { label: string; col: string; bg: string }> = {
  STRONG_BUY: { label: 'STRONG BUY', col: 'var(--gold)', bg: 'rgba(212,168,67,0.15)' },
  BUY: { label: 'BUY', col: '#34d47f', bg: 'rgba(34,197,94,0.12)' },
  MULTI_BUY: { label: 'MULTI BUY', col: '#34d47f', bg: 'rgba(34,197,94,0.12)' },
  CLUSTER_BUY: { label: 'CLUSTER BUY', col: 'var(--gold)', bg: 'rgba(212,168,67,0.15)' },
  INSIDER_BUY: { label: 'INSIDER BUY', col: 'var(--blue)', bg: 'rgba(56,189,248,0.12)' },
  SELL: { label: 'SELL', col: '#f2645f', bg: 'rgba(239,68,68,0.12)' },
  MIXED: { label: 'MIXED', col: 'var(--text-dim)', bg: 'rgba(128,128,140,0.10)' },
  neutral: { label: 'NEUTRAL', col: 'var(--text-dim)', bg: 'rgba(128,128,140,0.10)' },
}
function SignalBadge({ type }: { type: string }) {
  const c = SIGNAL[type] || SIGNAL.neutral
  return <span className="mono" style={{ fontSize: 8, padding: '2px 7px', borderRadius: 4, background: c.bg, border: `0.5px solid ${c.col}`, color: c.col, textTransform: 'uppercase', letterSpacing: '0.1em', whiteSpace: 'nowrap' }}>{c.label}</span>
}

export default function Intelligence() {
  const bias = useHQData('market-bias').data
  const strat = useHQData('strategy-recommendation').data
  const morning = useHQData('morning-report').data
  const sentinel = useHQData('sentinel-data').data

  const [tab, setTab] = useState<'forex' | 'markets' | 'crypto'>('forex')

  const brief: string = morning?.text || bias?.summary || bias?.morning_report || ''
  const marketImpact: any[] = Array.isArray(bias?.market_impact) ? bias.market_impact : []

  // Macro desk — prefer live strategy_recommendation instruments, fall back to
  // bias.pairs, else the classic four placeholders.
  const instruments: [string, any][] = strat?.instruments
    ? Object.entries(strat.instruments)
    : Array.isArray(bias?.pairs)
      ? bias.pairs.map((p: any) => [p.symbol, { bias: p.bias, lens_confidence: p.confidence, note: p.note }])
      : ['BTC/USDT', 'XAU/USD', 'US100', 'US OIL'].map((s) => [s, null])

  const regimeName = strat?.regime ? cap(strat.regime) : null
  const feed = (key: string) => (Array.isArray(bias?.[key]) ? bias[key] : [])
  const forex = feed('forex_news'); const markets = feed('markets_feed'); const crypto = feed('crypto_feed')
  const tabData = tab === 'forex' ? forex : tab === 'markets' ? markets : crypto

  // Sentinel
  const watchlist: any[] = sentinel?.watchlist_signals || []
  const discoveries: any[] = sentinel?.top_discoveries || []
  const analystRecs: any[] = sentinel?.analyst_recommendations || []
  const earnings: any[] = sentinel?.earnings_calendar || []
  const news: any[] = sentinel?.market_news || []
  const watchlistSet = new Set<string>(Object.values(sentinel?.watchlist_config || {}).flat() as string[])

  return (
    <div className="page-pad">
      <h1 className="page-title">Intelligence Feed</h1>

      {/* Daily Brief */}
      <Divider meta={bias?.last_updated || morning?.updated ? fmtTs(bias?.last_updated || morning?.updated) : undefined}>Daily Brief</Divider>
      <GlassCard hover={false} style={{ position: 'relative', overflow: 'hidden', border: '0.5px solid var(--gold-border)' }}>
        <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg,var(--gold),transparent)' }} />
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>Intelligence Summary</div>
        {brief
          ? <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.75, whiteSpace: 'pre-wrap' }}>{brief}</div>
          : <div style={{ fontSize: 13, color: 'var(--text-dim)', fontStyle: 'italic' }}>Awaiting Lens briefing — next run 04:55 UTC.</div>}
      </GlassCard>

      {/* Market Impact */}
      {marketImpact.length > 0 && (
        <>
          <Divider>Market Impact Analysis</Divider>
          <GlassCard hover={false} style={{ padding: '4px 20px' }}>
            {marketImpact.map((item, i) => {
              const symbol = item.symbol || item.pair || item.asset
              const dir = String(item.impact_direction || item.direction || '').toLowerCase()
              const analysis = item.impact_analysis || item.reasoning || item.analysis
              return (
                <div key={i} style={{ padding: '11px 0', borderBottom: i < marketImpact.length - 1 ? '0.5px solid rgba(128,128,140,0.10)' : 'none' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5, flexWrap: 'wrap' }}>
                    <span className="mono text-gold" style={{ fontSize: 12, fontWeight: 600 }}>{symbol}</span>
                    {dir && <span className={`badge badge-${dir.includes('bull') ? 'green' : dir.includes('bear') ? 'red' : 'mute'}`}>{dir}</span>}
                    {item.event && <span style={{ fontSize: 12, color: 'var(--text-dim)', fontStyle: 'italic' }}>{item.event}</span>}
                  </div>
                  {analysis && <div style={{ fontSize: 12.5, color: 'var(--text-dim)', lineHeight: 1.6 }}>{analysis}</div>}
                </div>
              )
            })}
          </GlassCard>
        </>
      )}

      {/* Macro Desk — Lens Report */}
      <Divider meta={regimeName ? `Jarvis regime · ${regimeName}` : undefined}>Macro Desk — Lens Report</Divider>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(240px,1fr))', gap: 12 }}>
        {instruments.map(([sym, d], i) => {
          const has = !!d
          const bStr = String(d?.bias || 'neutral').toLowerCase()
          const conf = has ? Number(d?.lens_confidence) || 0 : 0
          const badge = bStr === 'bullish' ? 'green' : bStr === 'bearish' ? 'red' : 'amber'
          const barColor = bStr === 'bullish' ? 'var(--green)' : bStr === 'bearish' ? 'var(--red)' : 'var(--amber)'
          return (
            <GlassCard key={sym} delay={i * 0.03} hover={false} style={{ opacity: has ? 1 : 0.65 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="mono" style={{ fontWeight: 600, fontSize: 14 }}>{String(sym).replace('_', '/')}</span>
                <span className={`badge badge-${badge}`}>{bStr.toUpperCase()}</span>
              </div>
              <div style={{ marginTop: 14 }}>
                <div className="mono-meta" style={{ marginBottom: 5 }}>confidence {conf.toFixed(0)}%</div>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${conf}%`, background: barColor, boxShadow: `0 0 8px ${barColor}` }} /></div>
              </div>
              {has ? (
                <>
                  <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 14, display: 'flex', justifyContent: 'space-between' }}>
                    <span>px {fmtNum(d.current_price)}</span>
                    <span>ADR {fmtNum(d.adr, 0)}</span>
                  </div>
                  <div className="mono-meta" style={{ marginTop: 6 }}>regime · {cap(String(d.regime || '—'))}</div>
                </>
              ) : (
                <div style={{ fontSize: 12, color: 'var(--text-mute)', marginTop: 12, fontStyle: 'italic', lineHeight: 1.4 }}>Awaiting next Lens run — updates daily at 04:55 UTC</div>
              )}
            </GlassCard>
          )
        })}
      </div>

      {/* Tabbed feed */}
      <Divider>Intelligence Feed</Divider>
      <GlassCard hover={false} style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', borderBottom: '0.5px solid var(--glass-border)', padding: '0 12px' }}>
          {(['forex', 'markets', 'crypto'] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              style={{ padding: '13px 16px', fontSize: 12, background: 'transparent', borderBottom: tab === t ? '2px solid var(--gold)' : '2px solid transparent', color: tab === t ? 'var(--gold)' : 'var(--text-dim)', marginBottom: -1, textTransform: 'capitalize' }}>
              {t}
            </button>
          ))}
        </div>
        <div style={{ padding: '10px 20px', minHeight: 90 }}>
          {tabData.length === 0 ? (
            <div style={{ fontSize: 12.5, color: 'var(--text-dim)', fontStyle: 'italic', padding: '12px 0' }}>No {tab} items in the latest Lens pull.</div>
          ) : tabData.map((n: any, i: number) => (
            <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'flex-start', padding: '11px 0', borderBottom: i < tabData.length - 1 ? '0.5px solid rgba(128,128,140,0.08)' : 'none' }}>
              <span style={{ width: 6, height: 6, borderRadius: 50, marginTop: 5, flexShrink: 0, background: n.impact === 'high' ? 'var(--red)' : n.impact === 'medium' ? 'var(--gold)' : 'rgba(128,128,140,0.4)' }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, lineHeight: 1.4 }}>{n.headline || n.title || ''}</div>
                <div className="mono-meta" style={{ marginTop: 3 }}>{n.time || n.date || ''}{n.source ? ` · ${n.source}` : ''}</div>
              </div>
            </div>
          ))}
        </div>
      </GlassCard>

      {/* Insider Intelligence (Sentinel) */}
      <Divider meta={sentinel ? `Sentinel · ${fmtTs(sentinel.last_updated)}` : undefined}>Insider Intelligence</Divider>
      {!sentinel ? (
        <GlassCard hover={false} style={{ border: '0.5px solid var(--gold-border)' }}>
          <div style={{ fontSize: 13, color: 'var(--gold)', marginBottom: 6 }}>Sentinel pipeline data unavailable.</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-dim)', lineHeight: 1.7 }}>
            Runs 3×/day (08:00 / 14:00 / 20:00 UTC) → <span className="mono" style={{ background: 'var(--input-bg)', padding: '1px 5px', borderRadius: 3 }}>sentinel_data.json</span>. Signals appear here once populated.
          </div>
        </GlassCard>
      ) : (
        <>
          {/* Summary strip */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
            {[
              { label: 'STRONG BUYS', val: sentinel.summary?.watchlist_strong_buys ?? 0, col: 'var(--gold)' },
              { label: 'BUY SIGNALS', val: sentinel.summary?.watchlist_buys ?? 0, col: 'var(--green)' },
              { label: 'DISCOVERIES', val: sentinel.summary?.discoveries_found ?? 0, col: 'var(--blue)' },
              { label: 'MKT TXS SCANNED', val: sentinel.summary?.total_market_txs ?? 0, col: 'var(--text-dim)' },
            ].map((s) => (
              <GlassCard key={s.label} hover={false} style={{ padding: '12px 16px', flex: '1 1 auto', minWidth: 110 }}>
                <div className="stat-num" style={{ fontSize: 22, color: s.col }}>{s.val}</div>
                <div className="mono-meta" style={{ marginTop: 4 }}>{s.label}</div>
              </GlassCard>
            ))}
          </div>

          {/* Watchlist signals */}
          {watchlist.length > 0 && (
            <>
              <div className="mono-label" style={{ marginBottom: 8 }}>watchlist signals — {watchlist.length} tickers</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 10, marginBottom: 20 }}>
                {watchlist.map((sig: any, i: number) => (
                  <GlassCard key={sig.symbol || i} hover={false}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span className="mono" style={{ fontSize: 15, fontWeight: 600 }}>{sig.symbol}</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <SignalBadge type={sig.signal_type} />
                        <span className="stat-num text-gold" style={{ fontSize: 18 }}>{sig.score}</span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 16, fontSize: 11, color: 'var(--text-dim)' }}>
                      <span><span className="text-green" style={{ fontWeight: 600 }}>↑{sig.buy_count}</span> <span style={{ opacity: 0.4 }}>|</span> <span className="text-red" style={{ fontWeight: 600 }}>↓{sig.sell_count}</span></span>
                      {sig.total_buy_value > 0 && <span className="text-green">{fmtValue(sig.total_buy_value)} bought</span>}
                      {sig.latest_date && <span className="mono-meta" style={{ marginLeft: 'auto' }}>{fmtDate(sig.latest_date)}</span>}
                    </div>
                  </GlassCard>
                ))}
              </div>
            </>
          )}

          {/* Discovery scan */}
          {discoveries.length > 0 && (
            <>
              <div className="mono-label" style={{ marginBottom: 8 }}>◎ discovery scan — institutional moves</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 10, marginBottom: 20 }}>
                {discoveries.map((d: any, i: number) => (
                  <GlassCard key={d.symbol || i} hover={false} style={{ borderLeft: '2px solid rgba(56,189,248,0.35)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                      <span className="mono" style={{ fontSize: 14, fontWeight: 600 }}>{d.symbol} <span style={{ fontSize: 9, color: 'var(--text-mute)', fontStyle: 'italic' }}>off-watchlist</span></span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <SignalBadge type={d.signal_type} />
                        <span className="stat-num" style={{ fontSize: 16, color: d.signal_type === 'CLUSTER_BUY' ? 'var(--gold)' : 'var(--text-hi)' }}>{d.score}</span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 14, fontSize: 11, color: 'var(--text-dim)' }}>
                      <span className="text-green">↑{d.buy_count} buys</span>
                      {d.total_value > 0 && <span className="text-blue">{fmtValue(d.total_value)}</span>}
                      {d.latest_date && <span className="mono-meta" style={{ marginLeft: 'auto' }}>{fmtDate(d.latest_date)}</span>}
                    </div>
                  </GlassCard>
                ))}
              </div>
            </>
          )}

          {/* Analyst consensus */}
          {analystRecs.length > 0 && (
            <>
              <div className="mono-label" style={{ marginBottom: 8 }}>analyst consensus</div>
              <GlassCard hover={false} style={{ marginBottom: 20 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(260px,1fr))', gap: '6px 24px' }}>
                  {analystRecs.map((rec: any, i: number) => <AnalystBar key={rec.symbol || i} rec={rec} />)}
                </div>
              </GlassCard>
            </>
          )}

          {/* Upcoming earnings */}
          {earnings.length > 0 && (
            <>
              <div className="mono-label" style={{ marginBottom: 8 }}>upcoming earnings (7 days)</div>
              <GlassCard hover={false} style={{ padding: '4px 20px', marginBottom: 20 }}>
                {earnings.slice(0, 20).map((e: any, i: number) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 0', borderBottom: i < Math.min(earnings.length, 20) - 1 ? '0.5px solid rgba(128,128,140,0.08)' : 'none' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {watchlistSet.has(e.symbol) && <span className="text-gold" style={{ fontSize: 10 }}>★</span>}
                      <span className="mono" style={{ fontSize: 12, color: watchlistSet.has(e.symbol) ? 'var(--gold)' : 'var(--text-hi)' }}>{e.symbol}</span>
                      {e.epsEstimate != null && <span className="mono text-gold" style={{ fontSize: 12, fontWeight: 600 }}>est. {e.epsEstimate > 0 ? '+' : ''}{e.epsEstimate}</span>}
                    </div>
                    <span className="mono-meta">{fmtDate(e.date)}</span>
                  </div>
                ))}
              </GlassCard>
            </>
          )}

          {/* Market news */}
          {news.length > 0 && (
            <>
              <div className="mono-label" style={{ marginBottom: 8 }}>market news</div>
              <GlassCard hover={false} style={{ padding: '4px 20px' }}>
                {news.map((n: any, i: number) => (
                  <div key={i} style={{ padding: '11px 0', borderBottom: i < news.length - 1 ? '0.5px solid rgba(128,128,140,0.08)' : 'none' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginBottom: 4 }}>
                      {n.url
                        ? <a href={n.url} target="_blank" rel="noreferrer" style={{ fontSize: 13, lineHeight: 1.4, flex: 1 }}>{n.headline}</a>
                        : <span style={{ fontSize: 13, lineHeight: 1.4, flex: 1 }}>{n.headline}</span>}
                      {n.related && watchlistSet.has(n.related) && <span className="badge badge-gold">{n.related}</span>}
                    </div>
                    <div className="mono-meta" style={{ display: 'flex', gap: 10 }}>
                      {n.source && <span>{n.source}</span>}
                      {n.datetime && <span>{typeof n.datetime === 'number' ? fmtTs(new Date(n.datetime * 1000)) : fmtTs(n.datetime)}</span>}
                    </div>
                  </div>
                ))}
              </GlassCard>
            </>
          )}
        </>
      )}
    </div>
  )
}

function AnalystBar({ rec }: { rec: any }) {
  const total = (rec.strongBuy || 0) + (rec.buy || 0) + (rec.hold || 0) + (rec.sell || 0) + (rec.strongSell || 0)
  if (total === 0) return null
  const pct = (n: number) => `${Math.round((n / total) * 100)}%`
  const segments = [
    { val: rec.strongBuy || 0, col: '#15803d' },
    { val: rec.buy || 0, col: '#34d47f' },
    { val: rec.hold || 0, col: 'rgba(128,128,140,0.35)' },
    { val: rec.sell || 0, col: '#f0a232' },
    { val: rec.strongSell || 0, col: '#f2645f' },
  ].filter((s) => s.val > 0)
  const bullish = (rec.strongBuy || 0) + (rec.buy || 0)
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
        <span className="mono" style={{ fontSize: 12 }}>{rec.symbol}</span>
        <span className="mono text-green" style={{ fontSize: 9 }}>{bullish} buy</span>
      </div>
      <div style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', gap: 1 }}>
        {segments.map((s, i) => <div key={i} style={{ width: pct(s.val), background: s.col, minWidth: 3 }} />)}
      </div>
    </div>
  )
}
