/**
 * Investing — Robinhood (stocks/Roth IRA), Trust Wallet (crypto), Bittensor staking
 * Data: robinhood_data.json, trustwallet_data.json, tao_portfolio.json
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { getRobinhoodData, getRobinhoodHoldings, getTrustWalletData, getTaoPortfolio, getKrakenHoldings } from '../api/client.js'
import { useIsMobile } from '../hooks/useIsMobile.js'

const POLL_MS = 60_000
const GOLD    = '#d4a843'

function fmtDol(v, dec = 2) {
  return '$' + parseFloat(v || 0).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}
function fmtCompact(n) {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n), s = n < 0 ? '-' : ''
  if (abs >= 1_000_000) return s + '$' + (abs / 1_000_000).toFixed(2) + 'M'
  if (abs >= 1_000)     return s + '$' + (abs / 1_000).toFixed(1) + 'K'
  return s + '$' + abs.toFixed(2)
}
function fmtPct(n, showPlus = true) {
  const v = parseFloat(n || 0)
  const sign = v > 0 ? (showPlus ? '+' : '') : v < 0 ? '' : ''
  return sign + v.toFixed(2) + '%'
}
function pctColor(v) {
  return parseFloat(v || 0) >= 0 ? 'var(--green)' : 'var(--red)'
}

const TOKEN_COLORS = {
  BTC: '#f7931a', ETH: '#627eea', SOL: '#9945ff', XRP: '#346aa9',
  ADA: '#0033ad', LINK: '#2a5ada', SUI: '#4da2ff', MATIC: '#8247e5',
  AVAX: '#e84142', DOT: '#e6007a', USDC: '#2775ca', USDT: '#26a17b',
  BNB: '#f3ba2f', ATOM: '#2e3148', UNI: '#ff007a', DEFAULT: '#6b7280',
}
function tokenColor(sym) {
  return TOKEN_COLORS[(sym || '').toUpperCase()] || TOKEN_COLORS.DEFAULT
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Investing({ demoMode, isActive = true }) {
  const isMobile = useIsMobile()
  const [rh,       setRh]       = useState(null)
  const [holdings, setHoldings] = useState(null)
  const [tw,       setTw]       = useState(null)
  const [tao,      setTao]      = useState(null)
  const [kraken,   setKraken]   = useState(null)
  const [loading,  setLoading]  = useState(true)
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const [rh_, hold_, tw_, taoD, krak_] = await Promise.allSettled([
        getRobinhoodData(), getRobinhoodHoldings(), getTrustWalletData(), getTaoPortfolio(), getKrakenHoldings(),
      ])
      if (rh_.status    === 'fulfilled') setRh(rh_.value)
      if (hold_.status  === 'fulfilled') setHoldings(hold_.value)
      if (tw_.status    === 'fulfilled') setTw(tw_.value)
      if (taoD.status   === 'fulfilled') setTao(taoD.value)
      if (krak_.status  === 'fulfilled') setKraken(krak_.value)
    } catch (e) { console.error('[Investing]', e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!isActive) { clearInterval(timer.current); return }
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [isActive, load])

  // Total invested across all sections
  const rhTotal     = parseFloat(rh?.total_equity || rh?.equity || rh?.stocks || 0)
  const twTotal     = parseFloat(tw?.total_usd || 0)
  const krakenTotal = parseFloat(kraken?.total_usd || 0)
  const taoPrice    = parseFloat(tao?.tao_price_usd || 0)
  const taoRootT    = parseFloat(tao?.root_staked_tao || 0)
  const taoSubT     = (tao?.subnet_positions || []).reduce((s, p) => s + parseFloat(p.current_value_tao || p.staked_tao || 0), 0)
  const taoTotal    = (taoRootT + taoSubT) * taoPrice
  const total       = rhTotal + twTotal + krakenTotal + taoTotal

  return (
    <div>
      {/* ── Page header ───────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <h1 className="page-title" style={{ marginBottom: 0 }}>Investing</h1>
        <div style={{ display: 'flex', gap: 28, alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 8, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 3 }}>Total Invested</div>
            {loading
              ? <div className="animate-pulse-slow" style={{ height: 28, width: 110, background: 'rgba(255,255,255,0.04)', borderRadius: 4 }} />
              : <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 24, color: GOLD, lineHeight: 1 }}>{fmtCompact(total)}</div>
            }
          </div>
          <div style={{ height: 32, width: 1, background: 'rgba(255,255,255,0.06)' }} />
          <div>
            <div style={{ fontSize: 8, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 3 }}>Sources</div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Robinhood · Trust Wallet · Kraken · Bittensor</div>
          </div>
        </div>
      </div>

      {/* ── Equities ──────────────────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Equities</h3><div className="section-line" /></div>
      <RobinhoodSection rh={rh} holdings={holdings} loading={loading} isMobile={isMobile} />

      {/* ── Crypto ────────────────────────────────────────────────────────── */}
      <div className="section-head" style={{ marginTop: 22 }}><div className="section-line" /><h3>Crypto</h3><div className="section-line" /></div>
      <TrustWalletSection tw={tw} loading={loading} isMobile={isMobile} />

      {/* ── Kraken ────────────────────────────────────────────────────────── */}
      <KrakenSection kraken={kraken} total={total} loading={loading} isMobile={isMobile} />

      {/* ── Bittensor Staking ──────────────────────────────────────────────── */}
      <div className="section-head" style={{ marginTop: 22 }}><div className="section-line" /><h3>Bittensor Staking</h3><div className="section-line" /></div>
      <TaoCard tao={tao} loading={loading} isMobile={isMobile} />
    </div>
  )
}

// ── Robinhood ─────────────────────────────────────────────────────────────────

function RobinhoodSection({ rh, holdings: holdingsData, loading, isMobile }) {
  const [sortCol, setSortCol] = useState('market_value')
  const [sortDir, setSortDir] = useState('desc')

  if (loading) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="glass animate-pulse-slow" style={{ height: 100 }} />
      <div className="glass animate-pulse-slow" style={{ height: 200 }} />
    </div>
  )

  if (!rh) return (
    <div className="glass" style={{ padding: '20px 24px', fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
      Robinhood sync pending — run sync_robinhood.py to populate data.
    </div>
  )

  const stocks   = parseFloat(rh.stocks   || 0)
  const rothIra  = parseFloat(rh.roth_ira || 0)
  const options  = parseFloat(rh.options  || 0)
  const total    = parseFloat(rh.total_equity || rh.equity || stocks + rothIra + options)
  const lastUpd  = rh.last_update
    ? new Date(rh.last_update).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : null

  // Holdings from dedicated endpoint
  const rawPositions = holdingsData?.positions || []
  const holdings = rawPositions.map(h => ({
    ticker:        h.symbol || '—',
    name:          h.name   || h.symbol || '—',
    shares:        parseFloat(h.quantity || 0),
    avg_cost:      parseFloat(h.avg_buy_price || 0),
    current_price: parseFloat(h.price || 0),
    market_value:  parseFloat(h.equity || 0),
    total_return:  parseFloat(h.equity_change || 0),
    return_pct:    parseFloat(h.percent_change || 0),
    account:       (h.type || 'stock') === 'stock' ? 'Taxable' : h.type,
  }))

  // Sort
  const sorted = [...holdings].sort((a, b) => {
    const v = (sortDir === 'asc' ? 1 : -1)
    const av = a[sortCol] ?? 0, bv = b[sortCol] ?? 0
    if (typeof av === 'string') return av.localeCompare(bv) * v
    return (av - bv) * v
  })

  function SortTH({ col, label, align = 'left' }) {
    const active = sortCol === col
    return (
      <span onClick={() => { if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc'); else { setSortCol(col); setSortDir('desc') } }}
        style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 3, userSelect: 'none',
          color: active ? GOLD : 'var(--text-muted)', textAlign: align }}>
        {label}
        <span style={{ fontSize: 7, opacity: active ? 1 : 0.3 }}>{active ? (sortDir === 'asc' ? '▲' : '▼') : '▼'}</span>
      </span>
    )
  }

  return (
    <div>
      {/* Summary card */}
      <div className="glass" style={{ padding: '20px 24px', marginBottom: 10, border: '1px solid rgba(74,222,128,0.12)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ fontSize: 9, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Robinhood Portfolio</div>
            <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 28, color: 'var(--text-primary)', lineHeight: 1, marginBottom: 4 }}>{fmtDol(total)}</div>
            {lastUpd && <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>synced {lastUpd}</div>}
          </div>
          <div style={{ display: 'flex', gap: 0 }}>
            <div style={{ padding: '0 20px', borderRight: '1px solid rgba(255,255,255,0.06)' }}>
              <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Taxable</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 16, color: 'var(--green)' }}>{fmtDol(stocks)}</div>
            </div>
            {options > 0 && (
              <div style={{ padding: '0 20px', borderRight: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Options</div>
                <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 16, color: 'var(--text-primary)' }}>{fmtDol(options)}</div>
              </div>
            )}
            <div style={{ paddingLeft: 20 }}>
              <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Roth IRA</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 16, color: 'var(--gold)' }}>{fmtDol(rothIra)}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Holdings last sync line */}
      {holdingsData?.last_updated && (
        <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace', marginBottom: 6, paddingLeft: 2 }}>
          holdings synced {new Date(holdingsData.last_updated).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
        </div>
      )}

      {/* Holdings table */}
      {holdings.length === 0 ? (
        <div className="glass" style={{ padding: '28px 24px', textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: 6 }}>No holdings data — sync pending</div>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.2)' }}>Run sync_robinhood.py to populate individual holdings</div>
        </div>
      ) : (
        <div className="glass" style={{ padding: '0 0 4px', overflowX: 'auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr 64px 76px 76px 88px 80px 64px 72px', gap: 0, padding: '10px 18px 8px', fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', borderBottom: '1px solid rgba(255,255,255,0.05)', minWidth: 680 }}>
            <SortTH col="ticker"       label="Ticker" />
            <SortTH col="name"         label="Company" />
            <SortTH col="shares"       label="Shares" />
            <SortTH col="avg_cost"     label="Avg Cost" />
            <SortTH col="current_price" label="Price" />
            <SortTH col="market_value" label="Mkt Value" />
            <SortTH col="total_return" label="Return $" />
            <SortTH col="return_pct"   label="Return %" />
            <SortTH col="account"      label="Account" />
          </div>
          {sorted.map((h, i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '70px 1fr 64px 76px 76px 88px 80px 64px 72px', gap: 0, padding: '9px 18px', fontSize: 11, borderBottom: '1px solid rgba(255,255,255,0.025)', alignItems: 'center', minWidth: 680 }}>
              <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: 'var(--text-primary)', fontWeight: 600 }}>{h.ticker}</span>
              <span style={{ color: 'var(--text-dim)', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: 8 }}>{h.name}</span>
              <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--text-muted)' }}>{h.shares.toFixed(3)}</span>
              <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--text-muted)' }}>{h.avg_cost > 0 ? fmtDol(h.avg_cost) : '—'}</span>
              <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--text-muted)' }}>{h.current_price > 0 ? fmtDol(h.current_price) : '—'}</span>
              <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: 'var(--text-primary)', fontWeight: 600 }}>{fmtDol(h.market_value)}</span>
              <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, color: pctColor(h.total_return) }}>{h.total_return >= 0 ? '+' : ''}{fmtDol(h.total_return)}</span>
              <span style={{ fontSize: 11, color: pctColor(h.return_pct), fontWeight: 600 }}>{fmtPct(h.return_pct)}</span>
              <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 4, textTransform: 'uppercase', letterSpacing: 0.5,
                background: h.account === 'Roth IRA' ? 'rgba(201,168,76,0.1)' : 'rgba(255,255,255,0.05)',
                color: h.account === 'Roth IRA' ? GOLD : 'var(--text-muted)',
                border: h.account === 'Roth IRA' ? '1px solid rgba(201,168,76,0.2)' : '1px solid rgba(255,255,255,0.08)',
              }}>{h.account}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Trust Wallet ──────────────────────────────────────────────────────────────

function TrustWalletSection({ tw, loading, isMobile }) {
  const [sortBy, setSortBy] = useState('value')

  if (loading) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="glass animate-pulse-slow" style={{ height: 80 }} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10 }}>
        {[1,2,3].map(i => <div key={i} className="glass animate-pulse-slow" style={{ height: 100 }} />)}
      </div>
    </div>
  )

  if (!tw) return (
    <div className="glass" style={{ padding: '20px 24px', fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
      Trust Wallet sync pending — run sync_trustwallet.py to populate data.
    </div>
  )

  const total    = parseFloat(tw.total_usd || 0)
  const lastUpd  = tw.last_update
    ? new Date(tw.last_update).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : null

  // Build holdings array
  const rawH = tw.holdings || {}
  let holdingsArr = Array.isArray(rawH)
    ? rawH
    : Object.entries(rawH).map(([sym, data]) => ({
        symbol:      sym,
        name:        data.name || sym,
        balance:     parseFloat(data.balance || data.amount || 0),
        usd_price:   parseFloat(data.usd_price || data.price || 0),
        usd_value:   parseFloat(data.usd_value || data.value || 0),
        change_24h:  parseFloat(data.change_24h || data.price_change_24h || 0),
        change_pct:  parseFloat(data.change_pct || data.percent_change_24h || 0),
      }))

  // Sort
  const sortFn = sortBy === 'value' ? (a, b) => b.usd_value - a.usd_value
    : sortBy === 'change' ? (a, b) => b.change_pct - a.change_pct
    : (a, b) => a.symbol.localeCompare(b.symbol)
  const sorted = [...holdingsArr].sort(sortFn)

  const cols = isMobile ? 'repeat(2,1fr)' : 'repeat(3,1fr)'

  return (
    <div>
      {/* Summary card */}
      <div className="glass" style={{ padding: '20px 24px', marginBottom: 10, border: '1px solid rgba(34,211,238,0.12)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ fontSize: 9, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Trust Wallet Portfolio</div>
            <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 28, color: 'var(--text-primary)', lineHeight: 1, marginBottom: 4 }}>{fmtDol(total)}</div>
            {lastUpd && <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>synced {lastUpd}</div>}
          </div>
          <div style={{ display: 'flex', gap: 24 }}>
            <div>
              <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Assets Held</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 20, color: 'var(--cyan)' }}>{holdingsArr.length}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Sort pills */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        {[['value','By Value'],['change','By 24h Change'],['alpha','Alphabetical']].map(([k,l]) => (
          <button key={k} onClick={() => setSortBy(k)}
            style={{ padding: '4px 12px', borderRadius: 6, cursor: 'pointer', fontSize: 10, fontWeight: 500,
              background: sortBy === k ? 'rgba(34,211,238,0.1)' : 'rgba(255,255,255,0.02)',
              color: sortBy === k ? 'var(--cyan)' : 'var(--text-muted)',
              border: sortBy === k ? '1px solid rgba(34,211,238,0.25)' : '1px solid rgba(255,255,255,0.07)',
            }}>{l}</button>
        ))}
      </div>

      {/* Holdings grid */}
      {sorted.length === 0 ? (
        <div className="glass" style={{ padding: '28px 24px', textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>No token holdings found in Trust Wallet data.</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: cols, gap: 10 }}>
          {sorted.map((h, i) => {
            const col = tokenColor(h.symbol)
            const hasChange = h.change_pct !== 0
            const pct = parseFloat(h.change_pct || 0)
            return (
              <div key={i} className="glass" style={{ padding: '14px 16px', border: `1px solid ${col}18` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                  {/* Token logo placeholder */}
                  <div style={{ width: 36, height: 36, borderRadius: '50%', background: `${col}22`, border: `2px solid ${col}40`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: col, fontFamily: '"IBM Plex Mono",monospace' }}>
                      {(h.symbol || '?').slice(0, 3).toUpperCase()}
                    </span>
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 13, color: 'var(--text-primary)', fontWeight: 600 }}>{h.symbol}</div>
                    <div style={{ fontSize: 9, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.name || h.symbol}</div>
                  </div>
                  {hasChange && (
                    <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 600, color: pctColor(pct), flexShrink: 0 }}>
                      {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
                  <div>
                    <div style={{ fontSize: 8, letterSpacing: 1.5, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 2 }}>Balance</div>
                    <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, color: 'var(--text-dim)' }}>
                      {h.balance < 0.01 ? h.balance.toFixed(6) : h.balance.toFixed(4)} {h.symbol}
                    </div>
                    {h.usd_price > 0 && (
                      <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>@ {fmtDol(h.usd_price)}</div>
                    )}
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 8, letterSpacing: 1.5, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 2 }}>Value</div>
                    <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 16, color: col }}>{fmtDol(h.usd_value)}</div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Kraken ────────────────────────────────────────────────────────────────────

const KRAKEN_ACCENT = '#5741d9'   // deep purple — Kraken brand

function KrakenSection({ kraken, total: portfolioTotal, loading, isMobile }) {
  if (loading) return (
    <div style={{ marginTop: 14 }}>
      <div className="glass animate-pulse-slow" style={{ height: 80, marginBottom: 10 }} />
      <div className="glass animate-pulse-slow" style={{ height: 180 }} />
    </div>
  )

  if (!kraken || kraken.error) return (
    <div className="glass" style={{ padding: '20px 24px', marginTop: 14, fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic',
      border: `1px solid ${KRAKEN_ACCENT}22` }}>
      Kraken sync pending — run sync_kraken.py to populate data.
    </div>
  )

  const total   = parseFloat(kraken.total_usd || 0)
  const holdings = (kraken.holdings || []).filter(h => h.value_usd > 0 || h.balance > 0)
  const lastUpd = kraken.last_updated
    ? new Date(kraken.last_updated).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <div style={{ marginTop: 14 }}>
      {/* Summary card */}
      <div className="glass" style={{ padding: '20px 24px', marginBottom: 10, border: `1px solid ${KRAKEN_ACCENT}30` }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ fontSize: 9, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Kraken Portfolio</div>
            <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 28, color: 'var(--text-primary)', lineHeight: 1, marginBottom: 4 }}>{fmtDol(total)}</div>
            {lastUpd && <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>synced {lastUpd}</div>}
          </div>
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
            <div>
              <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Assets</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 20, color: KRAKEN_ACCENT }}>{holdings.length}</div>
            </div>
            {portfolioTotal > 0 && (
              <div>
                <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>% of Portfolio</div>
                <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 20, color: KRAKEN_ACCENT }}>
                  {(total / portfolioTotal * 100).toFixed(1)}%
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Holdings table */}
      {holdings.length === 0 ? (
        <div className="glass" style={{ padding: '28px 24px', textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>No holdings found in Kraken data.</div>
        </div>
      ) : (
        <div className="glass" style={{ padding: '0 0 4px', overflowX: 'auto', border: `1px solid ${KRAKEN_ACCENT}18` }}>
          {/* Header */}
          <div style={{ display: 'grid', gridTemplateColumns: '56px 80px 1fr 96px 92px 88px', gap: 0,
            padding: '10px 18px 8px', fontSize: 8, letterSpacing: 2, textTransform: 'uppercase',
            color: 'var(--text-muted)', borderBottom: '1px solid rgba(255,255,255,0.05)', minWidth: 520 }}>
            <span>Asset</span>
            <span>Ticker</span>
            <span>Balance</span>
            <span style={{ textAlign: 'right' }}>Price</span>
            <span style={{ textAlign: 'right' }}>Value</span>
            <span style={{ textAlign: 'right' }}>% of Kraken</span>
          </div>
          {holdings.map((h, i) => {
            const col = tokenColor(h.asset)
            const pct = total > 0 ? h.value_usd / total * 100 : 0
            return (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '56px 80px 1fr 96px 92px 88px', gap: 0,
                padding: '9px 18px', fontSize: 11, borderBottom: '1px solid rgba(255,255,255,0.025)',
                alignItems: 'center', minWidth: 520 }}>
                {/* Asset */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ width: 26, height: 26, borderRadius: '50%', background: `${col}22`,
                    border: `1.5px solid ${col}40`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <span style={{ fontSize: 8, fontWeight: 700, color: col, fontFamily: '"IBM Plex Mono",monospace' }}>
                      {(h.asset || '?').slice(0, 3)}
                    </span>
                  </div>
                  <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: 'var(--text-primary)', fontWeight: 600 }}>{h.asset}</span>
                </div>
                {/* Kraken ticker */}
                <span style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{h.kraken_ticker}</span>
                {/* Balance */}
                <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--text-dim)' }}>
                  {h.balance < 0.001 ? h.balance.toFixed(8) : h.balance < 1 ? h.balance.toFixed(6) : h.balance.toFixed(4)}
                </span>
                {/* Price */}
                <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--text-muted)', textAlign: 'right' }}>
                  {h.price_usd > 0 ? fmtDol(h.price_usd) : '—'}
                </span>
                {/* Value */}
                <span style={{ fontFamily: '"Playfair Display",serif', fontSize: 14, color: col, textAlign: 'right' }}>
                  {fmtDol(h.value_usd)}
                </span>
                {/* % of Kraken */}
                <div style={{ textAlign: 'right' }}>
                  <span style={{ fontSize: 9, fontFamily: '"IBM Plex Mono",monospace', color: KRAKEN_ACCENT }}>{pct.toFixed(1)}%</span>
                  <div style={{ marginTop: 3, height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${Math.min(pct, 100)}%`, background: KRAKEN_ACCENT, borderRadius: 2 }} />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Bittensor / TaoCard ───────────────────────────────────────────────────────

function TaoCard({ tao, loading, isMobile }) {
  if (loading) {
    return (
      <div className="glass animate-pulse-slow"
           style={{ height: 120, marginBottom: 14, border: '1px solid rgba(212,168,67,0.15)' }} />
    )
  }
  if (!tao) return (
    <div className="glass" style={{ padding: '20px 24px', fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
      Bittensor data unavailable — run sync_tao.py to populate data.
    </div>
  )

  const positions   = tao.subnet_positions || []
  const rootTao     = parseFloat(tao.root_staked_tao || 0)
  const taoPrice    = parseFloat(tao.tao_price_usd || 0)
  const subnetTao   = positions.reduce((s, p) => s + parseFloat(p.current_value_tao || p.staked_tao || 0), 0)
  const totalTao    = rootTao + subnetTao
  const totalUsd    = totalTao * taoPrice
  const costTao     = parseFloat(tao.total_invested_tao || 0)
  const costUsd     = parseFloat(tao.total_invested_usd || 0)
  const retPct      = costTao > 0 ? (totalTao - costTao) / costTao * 100 : 0
  const retColor    = retPct >= 0 ? 'var(--green)' : 'var(--red)'
  const dcaUsed     = tao.dca_entries_used || 0
  const rootPct     = totalTao > 0 ? rootTao / totalTao * 100 : 50

  const updatedStr  = tao.updated
    ? new Date(tao.updated).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '—'

  return (
    <div className="glass" style={{ padding: '22px 24px', marginBottom: 14, border: `1px solid rgba(212,168,67,0.2)` }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontFamily: '"Playfair Display",serif', fontSize: 22, color: GOLD, lineHeight: 1 }}>τ</span>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18 }}>Bittensor Staking</div>
        </div>
        <span className="pill" style={{ background: 'rgba(212,168,67,0.1)', color: GOLD, border: `1px solid rgba(212,168,67,0.25)`, fontSize: 7 }}>● live</span>
      </div>

      {/* Stats row */}
      <div style={{ display: 'flex', gap: isMobile ? 16 : 32, marginBottom: 16, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Portfolio Value</div>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 20, color: GOLD }}>
            {totalTao.toFixed(4)} τ
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace', marginTop: 2 }}>
            ${totalUsd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Return</div>
          <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 18, color: retColor }}>
            {(retPct >= 0 ? '+' : '') + retPct.toFixed(1) + '%'}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2 }}>
            from {costTao.toFixed(3)} τ (${costUsd.toFixed(2)})
          </div>
        </div>
        <div>
          <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>DCA Status</div>
          <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 14, color: 'var(--text-primary)', marginBottom: 6 }}>
            {dcaUsed}/5 entries deployed
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {[1,2,3,4,5].map(i => (
              <div key={i} style={{
                width: 10, height: 10, borderRadius: 2,
                background: i <= dcaUsed ? GOLD : 'rgba(255,255,255,0.06)',
                border: `1px solid ${i <= dcaUsed ? GOLD : 'rgba(255,255,255,0.12)'}`,
                boxShadow: i <= dcaUsed ? `0 0 4px rgba(212,168,67,0.4)` : 'none',
              }} />
            ))}
          </div>
        </div>
      </div>

      {/* Allocation bar */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 5 }}>
          <span>Allocation</span>
          <span>Root {rootPct.toFixed(0)}% · Subnets {(100 - rootPct).toFixed(0)}%</span>
        </div>
        <div style={{ height: 4, background: 'rgba(255,255,255,0.04)', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${rootPct}%`, background: `linear-gradient(90deg, ${GOLD}, rgba(212,168,67,0.55))`, borderRadius: 2 }} />
        </div>
      </div>

      <div style={{ height: 1, background: 'rgba(255,255,255,0.04)', marginBottom: 10 }} />

      {/* Positions list */}
      <div>
        {/* Root stake */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: GOLD, boxShadow: `0 0 5px rgba(212,168,67,0.5)` }} />
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>Root</span>
            <span style={{ fontSize: 7, padding: '1px 5px', borderRadius: 3, background: 'rgba(212,168,67,0.1)', color: GOLD, border: `1px solid rgba(212,168,67,0.2)`, textTransform: 'uppercase' }}>SN0</span>
          </div>
          <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, color: 'var(--text-muted)' }}>
            {rootTao.toFixed(6)} τ
          </span>
        </div>

        {/* Subnet positions */}
        {positions.map(pos => {
          const cur      = parseFloat(pos.current_value_tao || pos.staked_tao || 0)
          const pnl      = pos.pnl_pct ?? 0
          const pnlColor = pnl >= 0 ? 'var(--green)' : 'var(--red)'
          const score    = pos.score || 0
          const scoreHue = score >= 70 ? '74,222,128' : score >= 50 ? '212,168,67' : '156,163,175'
          const scoreCol = score >= 70 ? 'var(--green)' : score >= 50 ? GOLD : 'var(--text-muted)'
          const tiers    = pos.tiers_hit || []

          return (
            <div key={pos.netuid} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: `rgba(212,168,67,0.4)` }} />
                <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  {pos.name}
                  <span style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 4 }}>SN{pos.netuid}</span>
                </span>
                <span style={{ fontSize: 7, padding: '1px 4px', borderRadius: 3, background: `rgba(${scoreHue},0.08)`, color: scoreCol, border: `1px solid rgba(${scoreHue},0.2)` }}>
                  {score.toFixed(0)}
                </span>
                {tiers.length > 0 && (
                  <span style={{ fontSize: 7, padding: '1px 4px', borderRadius: 3, background: 'rgba(74,222,128,0.08)', color: 'var(--green)', border: '1px solid rgba(74,222,128,0.2)' }}>
                    T{tiers.join('')}
                  </span>
                )}
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, color: 'var(--text-muted)' }}>{cur.toFixed(6)} τ</div>
                <div style={{ fontSize: 9, color: pnlColor }}>{(pnl >= 0 ? '+' : '') + pnl.toFixed(1) + '%'}</div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Footer */}
      <div style={{ marginTop: 10, fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace', display: 'flex', justifyContent: 'space-between' }}>
        <span>τ ${taoPrice.toFixed(2)} · finney</span>
        <span>updated {updatedStr}</span>
      </div>
    </div>
  )
}
