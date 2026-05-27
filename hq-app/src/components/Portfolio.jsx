/**
 * Portfolio — 2037 Wealth Goal hero, net worth snapshot, monthly cash flow, P&L summary
 * Data: robinhood_data.json, trustwallet_data.json, tradelocker_trades.json,
 *       oracle_picks.json, GET /hq/data (stored). HYSA + cash flow: localStorage.
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import {
  getStoredData, getTradesFile, getOracleFile,
  getRobinhoodData, getTrustWalletData, getTaoPortfolio, getKrakenHoldings,
  setAccount,
} from '../api/client.js'
import { fakeAmt } from '../context/DemoContext.jsx'
import { useIsMobile, useIsSmall } from '../hooks/useIsMobile.js'

const POLL_MS    = 60_000
const GOAL_2037  = 10_000_000
const INS_DEFAULT = 900_000   // Life insurance cash value (manual)

const HYSA_KEY     = 'portfolio.hysa_balance'
const INCOME_KEY   = 'portfolio.cashflow.income'
const EXPENSE_KEY  = 'portfolio.cashflow.expense'

const INCOME_CATEGORIES  = ['Trading Payout', 'Etsy Sale', 'GOAT Payout', 'Kalshi Withdrawal', 'Other']
const EXPENSE_CATEGORIES = ['Rent', 'Subscriptions', 'Food', 'Travel', 'Entertainment', 'Other']

function fmtDol(v, dec = 2) {
  return '$' + parseFloat(v || 0).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}
function fmtCompact(n) {
  if (n == null) return '—'
  const abs = Math.abs(n), s = n < 0 ? '-' : ''
  if (abs >= 1_000_000) return s + '$' + (abs / 1_000_000).toFixed(2) + 'M'
  if (abs >= 1_000)     return s + '$' + (abs / 1_000).toFixed(1) + 'K'
  return s + '$' + abs.toFixed(2)
}
function fmtSign(n) {
  const v = parseFloat(n || 0)
  return (v >= 0 ? '+' : '-') + '$' + Math.abs(v).toFixed(2)
}

function weekStart() {
  const d = new Date(); d.setHours(0,0,0,0)
  d.setDate(d.getDate() - d.getDay())
  return d
}
function monthStart() {
  const d = new Date(); d.setDate(1); d.setHours(0,0,0,0); return d
}
function yearStart() {
  const d = new Date(); d.setMonth(0,1); d.setHours(0,0,0,0); return d
}
function todayStart() {
  const d = new Date(); d.setHours(0,0,0,0); return d
}
function currentMonthKey() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function tradePeriodPnl(trades = [], since) {
  return trades.reduce((s, t) => {
    const ds = t.close_date || t.close_time || t.close || t.open_time || t.date || ''
    return new Date(ds) >= since ? s + (parseFloat(t.pnl) || 0) : s
  }, 0)
}
function betPeriodPnl(bets = [], since) {
  return bets.reduce((s, b) => {
    return new Date(b.date || '') >= since ? s + (parseFloat(b.pnl) || 0) : s
  }, 0)
}

function loadLS(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch { return fallback }
}
function saveLS(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch {}
}

export default function Portfolio({ demoMode, isActive = true }) {
  const isMobile = useIsMobile()
  const isSmall  = useIsSmall()

  const [stored,  setStored]  = useState(null)
  const [trades,  setTrades]  = useState(null)
  const [oracle,  setOracle]  = useState(null)
  const [rh,      setRh]      = useState(null)
  const [tw,      setTw]      = useState(null)
  const [tao,     setTao]     = useState(null)
  const [kraken,  setKraken]  = useState(null)
  const [loading, setLoading] = useState(true)
  const [editIns, setEditIns] = useState(false)
  const [editHysa, setEditHysa] = useState(false)
  const [hysaBal, setHysaBal] = useState(() => parseFloat(loadLS(HYSA_KEY, 0)))
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const [st, tr, or_, rh_, tw_, taoD, kr_] = await Promise.allSettled([
        getStoredData(), getTradesFile(), getOracleFile(),
        getRobinhoodData(), getTrustWalletData(), getTaoPortfolio(),
        getKrakenHoldings(),
      ])
      if (st.status   === 'fulfilled') setStored(st.value)
      if (tr.status   === 'fulfilled') setTrades(tr.value)
      if (or_.status  === 'fulfilled') setOracle(or_.value)
      if (rh_.status  === 'fulfilled') setRh(rh_.value)
      if (tw_.status  === 'fulfilled') setTw(tw_.value)
      if (taoD.status === 'fulfilled') setTao(taoD.value)
      if (kr_.status  === 'fulfilled') setKraken(kr_.value)
    } catch (e) { console.error('[Portfolio]', e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!isActive) { clearInterval(timer.current); return }
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [isActive, load])

  // ── Account balances ────────────────────────────────────────────────────
  const tlBal         = parseFloat(trades?.balance || 0)
  const rhBal         = parseFloat(rh?.equity || rh?.total_equity || rh?.stocks || 0)
  const twBal         = parseFloat(tw?.total_usd || 0)
  const manualAccts   = stored?.accounts || {}
  const insBal        = parseFloat(manualAccts?.ins?.balance ?? manualAccts?.life_insurance?.balance ?? INS_DEFAULT)
  const myBankroll    = parseFloat(stored?.my_bankroll?.bankroll || 0)

  // TAO portfolio value
  const taoPrice      = parseFloat(tao?.tao_price_usd || 0)
  const taoRootTao    = parseFloat(tao?.root_staked_tao || 0)
  const taoSubnetTao  = (tao?.subnet_positions || []).reduce(
    (s, p) => s + parseFloat(p.current_value_tao || p.staked_tao || 0), 0
  )
  const taoTotalTao   = taoRootTao + taoSubnetTao
  const taoUsd        = taoTotalTao * taoPrice

  const krakenBal     = parseFloat(kraken?.total_usd || 0)

  // Net worth: HYSA + trading/brokerage + crypto + insurance + bankroll + TAO
  const netWorth = hysaBal + tlBal + rhBal + twBal + krakenBal + insBal + myBankroll + taoUsd
  const goalPct  = Math.min(100, (netWorth / GOAL_2037) * 100)
  const daysLeft = Math.max(0, Math.round((new Date('2037-12-31') - new Date()) / 86400000))
  const reqMo    = netWorth < GOAL_2037 ? (GOAL_2037 - netWorth) / (daysLeft / 30) : 0

  // ── Trading P&L ─────────────────────────────────────────────────────────
  const tradeList  = trades?.trades ?? []
  const tradeToday = tradePeriodPnl(tradeList, todayStart())
  const tradeWeek  = tradePeriodPnl(tradeList, weekStart())
  const tradeMo    = tradePeriodPnl(tradeList, monthStart())
  const tradeYtd   = tradePeriodPnl(tradeList, yearStart())

  // ── Bets P&L ────────────────────────────────────────────────────────────
  const oraclePnl  = parseFloat(oracle?.total_pnl || 0)
  const myBets     = stored?.my_bets ?? stored?.bets ?? []
  const myPnl      = myBets.reduce((s, b) => s + (parseFloat(b.pnl) || 0), 0)
  const myWins     = myBets.filter(b => (b.result||'').toLowerCase()==='w'||(b.result||'').toLowerCase()==='win').length
  const betsToday  = betPeriodPnl(myBets, todayStart())
  const betsMo     = betPeriodPnl(myBets, monthStart())
  const betsYtd    = betPeriodPnl(myBets, yearStart())

  const pnlToday = tradeToday + betsToday
  const pnlMo    = tradeMo    + betsMo
  const pnlYtd   = tradeYtd   + betsYtd

  // ── Demo fakes ──────────────────────────────────────────────────────────
  const D = demoMode
  const dNw       = fakeAmt('port.nw',      52000,  88000)
  const dRh       = fakeAmt('port.rh',       8000,  24000)
  const dTl       = fakeAmt('port.tl',      12000,  38000)
  const dTw       = fakeAmt('port.tw',       2500,  11000)
  const dHysa     = fakeAmt('port.hysa',     5000,  22000)
  const dIns      = fakeAmt('port.ins',     18000,  55000)
  const dBr       = fakeAmt('port.br',        400,   1500)
  const dPnlToday = fakeAmt('port.pnl.td',    50,    380)
  const dPnlMo    = fakeAmt('port.pnl.mo',   400,   2200)
  const dPnlYtd   = fakeAmt('port.pnl.ytd', 1800,   7500)
  const dReqMo    = fakeAmt('port.req',      3500,   8000)
  const dGoalPct  = dNw / GOAL_2037 * 100

  const displayNw      = D ? fmtCompact(dNw)   : fmtCompact(netWorth)
  const displayGoalPct = D ? dGoalPct            : goalPct
  const displayReqMo   = D ? fmtCompact(dReqMo) : fmtCompact(reqMo)

  const strmCols  = isMobile ? '1fr' : '1fr 1fr'
  const footCols  = isMobile ? 'repeat(2,1fr)' : 'repeat(4,1fr)'

  return (
    <div>
      <h1 className="page-title">Portfolio</h1>

      {/* ── 2037 Wealth Goal Hero ──────────────────────────────────── */}
      <div className="glass" style={{ border: '1px solid rgba(201,168,76,0.2)', padding: isMobile ? '20px 18px' : '28px 32px', marginBottom: 14, position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: -60, right: -60, width: 300, height: 300, background: 'radial-gradient(circle,rgba(201,168,76,0.07) 0%,transparent 70%)', pointerEvents: 'none' }} />

        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20, flexWrap: isMobile ? 'wrap' : 'nowrap', gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 9, letterSpacing: 4, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>2037 Wealth Goal</div>
            {loading
              ? <div className="animate-pulse-slow" style={{ height: 44, width: 280, background: 'rgba(255,255,255,0.04)', borderRadius: 6 }} />
              : <div style={{ fontFamily: '"Playfair Display",serif', fontSize: isMobile ? 28 : 36, fontWeight: 700, color: 'var(--gold)', lineHeight: 1, textShadow: '0 0 40px rgba(201,168,76,0.2)' }}>
                  <span>{displayNw}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: isMobile ? 16 : 22 }}> / $10.00M</span>
                </div>
            }
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 5 }}>{daysLeft.toLocaleString()} days remaining · Started Jan 1, 2024</div>
          </div>
          <div style={{ display: 'flex', gap: isMobile ? 16 : 32, textAlign: 'right', shrink: 0 }}>
            <div>
              <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Progress</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 14, color: 'var(--gold)' }}>{displayGoalPct.toFixed(1)}%</div>
            </div>
            <div>
              <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Required / Mo</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 14, color: 'var(--text-primary)' }}>{displayReqMo}</div>
            </div>
          </div>
        </div>

        <div style={{ height: 6, background: 'rgba(255,255,255,0.04)', borderRadius: 3, marginBottom: 10, overflow: 'visible', position: 'relative' }}>
          <div style={{ height: '100%', width: `${displayGoalPct}%`, background: 'linear-gradient(90deg,var(--gold),var(--gold-light))', borderRadius: 3, boxShadow: '0 0 12px rgba(201,168,76,0.5)', position: 'relative', transition: 'width .8s' }}>
            <span style={{ position: 'absolute', right: -4, top: -22, fontSize: 9, color: 'var(--gold)', fontFamily: '"IBM Plex Mono",monospace', background: 'var(--navy)', padding: '1px 4px', borderRadius: 2 }}>▲ {displayGoalPct.toFixed(1)}%</span>
          </div>
        </div>

        {!isMobile && (
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
            {[
              { label: '$0', sub: 'Start' },
              { label: displayNw, sub: 'Today ▲' },
              { label: '$1M', sub: 'Next' },
              { label: '$2.5M', sub: '2028' },
              { label: '$5M', sub: '2031' },
              { label: '$10M', sub: '2037' },
            ].map((m, i) => (
              <div key={i} style={{ textAlign: 'center' }}>
                <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: i === 1 ? 'var(--gold)' : 'var(--text-muted)' }}>{m.label}</div>
                <div style={{ fontSize: 8, color: 'var(--text-muted)', opacity: 0.6 }}>{m.sub}</div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: footCols, gap: 0, paddingTop: 18, borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          <FooterStat label="Current Net Worth"      val={displayNw}                          sub="Across all accounts"    loading={loading} />
          <FooterStat label="Days Remaining"         val={daysLeft.toLocaleString()}          sub="Until Dec 31, 2037"     loading={loading} />
          <FooterStat label="Required Monthly"       val={displayReqMo}                       sub="To hit goal on time"    loading={loading} />
          <FooterStat label="Projected at Current Rate" val="—"                               sub="Based on monthly avg"   loading={false} />
        </div>
      </div>

      {/* ── Net Worth Snapshot ───────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Net Worth Snapshot</h3><div className="section-line" /></div>
      <div className="glass" style={{ marginBottom: 14 }}>
        {(() => {
          const acctRows = [
            { label: D ? 'Brokerage Account' : 'Robinhood',      sub: 'Brokerage', val: D ? dRh  : rhBal,    badge: 'live'   },
            { label: D ? 'Trading Account'   : 'TradeLocker',    sub: 'Trading',    val: D ? dTl  : tlBal,    badge: 'live'   },
            { label: D ? 'Crypto Wallet'     : 'Trust Wallet',   sub: 'Crypto',     val: D ? dTw  : twBal,    badge: 'live'   },
            { label: D ? 'Crypto Exchange'   : 'Kraken',         sub: 'Crypto',     val: D ? fakeAmt('port.kr', 3000, 12000) : krakenBal, badge: 'live' },
            { label: D ? 'High-Yield Savings' : 'HYSA',          sub: 'Cash',       val: D ? dHysa : hysaBal, badge: 'manual', onEdit: D ? undefined : () => setEditHysa(true) },
            { label: D ? 'Insurance'         : 'Life Insurance', sub: 'Cash Value', val: D ? dIns : insBal,   badge: 'manual', onEdit: D ? undefined : () => setEditIns(true) },
          ]
          const cols = isMobile ? 'repeat(2,1fr)' : `repeat(${acctRows.length},1fr)`
          return (
            <div style={{ display: 'grid', gridTemplateColumns: cols, gap: 0 }}>
              {acctRows.map((acct, i) => (
                <div key={i} style={{
                  padding: '16px 18px',
                  borderRight: i < acctRows.length - 1 && !isMobile ? '1px solid rgba(255,255,255,0.05)' : 'none',
                  borderBottom: isMobile && i < acctRows.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <div style={{ fontSize: 9, letterSpacing: 1.5, textTransform: 'uppercase', color: 'var(--text-muted)' }}>{acct.sub}</div>
                    {acct.badge === 'live'
                      ? <span style={{ fontSize: 7, padding: '1px 5px', borderRadius: 10, background: 'rgba(74,222,128,0.1)', color: '#4ade80', border: '1px solid rgba(74,222,128,0.2)', letterSpacing: 1 }}>LIVE</span>
                      : <span style={{ fontSize: 7, padding: '1px 5px', borderRadius: 10, background: 'rgba(255,255,255,0.04)', color: 'var(--text-muted)', border: '1px solid rgba(255,255,255,0.08)', letterSpacing: 1 }}>MANUAL</span>}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 6, fontWeight: 600 }}>{acct.label}</div>
                  {loading
                    ? <div className="animate-pulse-slow" style={{ height: 22, width: 80, background: 'rgba(255,255,255,0.04)', borderRadius: 4 }} />
                    : <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: 'var(--text-primary)' }}>{fmtDol(acct.val)}</div>
                  }
                  {acct.onEdit && <button className="edit-btn mt-2" onClick={acct.onEdit}>Edit</button>}
                </div>
              ))}
            </div>
          )
        })()}
      </div>

      {/* ── P&L Summary ───────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>P&L Summary</h3><div className="section-line" /></div>
      <div className="glass" style={{ marginBottom: 14 }}>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '80px 1fr 1fr 1fr' : '140px 1fr 1fr 1fr', padding: '10px 18px', borderBottom: '1px solid rgba(255,255,255,0.05)', fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
          <span />
          <span>Today</span>
          <span>This Month</span>
          <span>YTD</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '80px 1fr 1fr 1fr' : '140px 1fr 1fr 1fr', padding: '12px 18px', borderBottom: '1px solid rgba(255,255,255,0.05)', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)', fontWeight: 600 }}>Trading</div>
            <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>Crisp + Blade</div>
          </div>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: (D ? dPnlToday : tradeToday) >= 0 ? 'var(--green)' : 'var(--red)' }}>{D ? fmtSign(dPnlToday) : fmtSign(tradeToday)}</div>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: (D ? dPnlMo : tradeMo) >= 0 ? 'var(--green)' : 'var(--red)' }}>{D ? fmtSign(dPnlMo) : fmtSign(tradeMo)}</div>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: (D ? dPnlYtd : tradeYtd) >= 0 ? 'var(--green)' : 'var(--red)' }}>{D ? fmtSign(dPnlYtd) : fmtSign(tradeYtd)}</div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '80px 1fr 1fr 1fr' : '140px 1fr 1fr 1fr', padding: '12px 18px', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)', fontWeight: 600 }}>Sports Betting</div>
            <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>You + Oracle</div>
          </div>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: (D ? dPnlToday * 0.3 : betsToday) >= 0 ? 'var(--green)' : 'var(--red)' }}>{D ? fmtSign(dPnlToday * 0.3) : fmtSign(betsToday)}</div>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: (D ? dPnlMo * 0.3 : betsMo) >= 0 ? 'var(--green)' : 'var(--red)' }}>{D ? fmtSign(dPnlMo * 0.3) : fmtSign(betsMo)}</div>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: (D ? dPnlYtd * 0.3 : betsYtd) >= 0 ? 'var(--green)' : 'var(--red)' }}>{D ? fmtSign(dPnlYtd * 0.3) : fmtSign(betsYtd)}</div>
        </div>
      </div>

      {/* ── Income Streams (Trading + Sports) ──────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Income Streams</h3><div className="section-line" /></div>
      <div style={{ display: 'grid', gridTemplateColumns: strmCols, gap: 14 }}>
        <div className="glass" style={{ padding: '22px 24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18 }}>Trading P&L</div>
            <span className="pill pill-green">Crisp + Blade</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', marginBottom: 14 }}>
            {[['This Week', tradeWeek], ['This Month', tradeMo], ['YTD', tradeYtd]].map(([lbl, val], ki) => {
              const dv = [fakeAmt('port.tw.wk', 100, 600), fakeAmt('port.tw.mo', 400, 2000), fakeAmt('port.tw.ytd', 1500, 6000)][ki]
              return (
                <div key={lbl} style={{ paddingRight: 14, borderRight: '1px solid rgba(255,255,255,0.04)', marginRight: 14 }}>
                  <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>{lbl}</div>
                  <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: (D ? dv : val) >= 0 ? 'var(--green)' : 'var(--red)' }}>{D ? fmtSign(dv) : fmtSign(val)}</div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="glass" style={{ padding: '22px 24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18 }}>Sports Betting</div>
            <span className="pill pill-purple">You + Oracle</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', marginBottom: 14 }}>
            {[['This Week', 0], ['This Month', myPnl], ['YTD', myPnl + oraclePnl]].map(([lbl, val], ki) => {
              const dv = [fakeAmt('port.bt.wk', 20, 180), fakeAmt('port.bt.mo', 80, 500), fakeAmt('port.bt.ytd', 300, 1800)][ki]
              return (
                <div key={lbl} style={{ paddingRight: 14, borderRight: '1px solid rgba(255,255,255,0.04)', marginRight: 14 }}>
                  <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>{lbl}</div>
                  <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18, color: (D ? dv : val) >= 0 ? 'var(--green)' : 'var(--red)' }}>{D ? fmtSign(dv) : fmtSign(val)}</div>
                </div>
              )
            })}
          </div>
          <div style={{ height: 1, background: 'rgba(255,255,255,0.04)', marginBottom: 10 }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>You</div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{myWins}W - {myBets.length - myWins}L</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: 'var(--text-muted)' }}>{D ? fmtSign(fakeAmt('port.mypnl', 50, 600)) : fmtSign(myPnl)}</div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>Bankroll: {D ? fmtDol(dBr) : fmtDol(myBankroll)}</div>
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0' }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>Oracle</div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{oracle?.record ?? '—'}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: 'var(--text-muted)' }}>{D ? fmtSign(fakeAmt('port.oraclepnl', 100, 900)) : fmtSign(oraclePnl)}</div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>Bankroll: {D ? fmtDol(fakeAmt('port.obr', 600, 1800)) : fmtDol(oracle?.bankroll || 0)}</div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Monthly Cash Flow ─────────────────────────────────────── */}
      <div className="section-head" style={{ marginTop: 20 }}>
        <div className="section-line" /><h3>Monthly Cash Flow</h3><div className="section-line" />
      </div>
      <CashFlowTracker isMobile={isMobile} demoMode={demoMode} />

      {/* ── Modals ──────────────────────────────────────────────── */}
      {editIns && (
        <EditValueModal
          title="Edit Life Insurance"
          label="Cash Value ($)"
          current={insBal}
          onSave={async v => { await setAccount('ins', { balance: v }); setEditIns(false); load() }}
          onClose={() => setEditIns(false)}
        />
      )}
      {editHysa && (
        <EditValueModal
          title="Edit HYSA Balance"
          label="HYSA Balance ($)"
          current={hysaBal}
          onSave={v => { saveLS(HYSA_KEY, v); setHysaBal(v); setEditHysa(false) }}
          onClose={() => setEditHysa(false)}
        />
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// SUB-COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

function FooterStat({ label, val, sub, loading }) {
  return (
    <div style={{ padding: '0 20px', borderRight: '1px solid rgba(255,255,255,0.04)' }}>
      <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 5 }}>{label}</div>
      {loading
        ? <div className="animate-pulse-slow" style={{ height: 28, width: 80, background: 'rgba(255,255,255,0.04)', borderRadius: 4, marginBottom: 4 }} />
        : <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 22, color: 'var(--gold)' }}>{val}</div>}
      <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{sub}</div>
    </div>
  )
}

function CashFlowTracker({ isMobile, demoMode }) {
  const [month, setMonth] = useState(currentMonthKey())
  const [income, setIncome]   = useState(() => loadLS(INCOME_KEY, []))
  const [expense, setExpense] = useState(() => loadLS(EXPENSE_KEY, []))

  useEffect(() => { saveLS(INCOME_KEY, income) },   [income])
  useEffect(() => { saveLS(EXPENSE_KEY, expense) }, [expense])

  const monthIncome  = income.filter(e => e.month === month)
  const monthExpense = expense.filter(e => e.month === month)
  const incomeTotal  = monthIncome.reduce((s, e)  => s + parseFloat(e.amount || 0), 0)
  const expenseTotal = monthExpense.reduce((s, e) => s + parseFloat(e.amount || 0), 0)
  const net          = incomeTotal - expenseTotal

  const allMonths = Array.from(new Set([...income.map(e => e.month), ...expense.map(e => e.month), month])).sort().reverse()

  const addIncome  = entry => setIncome(arr  => [{ ...entry, id: crypto.randomUUID() }, ...arr])
  const addExpense = entry => setExpense(arr => [{ ...entry, id: crypto.randomUUID() }, ...arr])
  const delIncome  = id    => setIncome(arr  => arr.filter(e => e.id !== id))
  const delExpense = id    => setExpense(arr => arr.filter(e => e.id !== id))

  const cols = isMobile ? '1fr' : '1fr 1fr'

  return (
    <div>
      <div className="glass" style={{ marginBottom: 14, padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)' }}>Month</div>
        <select value={month} onChange={e => setMonth(e.target.value)}
          style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', color: 'var(--text-dim)', padding: '4px 10px', borderRadius: 6, fontFamily: '"IBM Plex Mono",monospace', fontSize: 12 }}>
          {allMonths.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: cols, gap: 14, marginBottom: 14 }}>
        <CashFlowColumn
          title="Income"
          total={incomeTotal}
          totalColor="var(--green)"
          entries={monthIncome}
          categories={INCOME_CATEGORIES}
          month={month}
          onAdd={addIncome}
          onDelete={delIncome}
          demoMode={demoMode}
        />
        <CashFlowColumn
          title="Expenses"
          total={expenseTotal}
          totalColor="var(--red)"
          entries={monthExpense}
          categories={EXPENSE_CATEGORIES}
          month={month}
          onAdd={addExpense}
          onDelete={delExpense}
          demoMode={demoMode}
        />
      </div>

      <div className="glass" style={{ padding: '18px 24px', textAlign: 'center' }}>
        <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>Net Cash Flow</div>
        <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 28, color: net >= 0 ? 'var(--green)' : 'var(--red)' }}>
          {fmtSign(net)}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
          Income {fmtDol(incomeTotal)} − Expenses {fmtDol(expenseTotal)}
        </div>
      </div>
    </div>
  )
}

function CashFlowColumn({ title, total, totalColor, entries, categories, month, onAdd, onDelete, demoMode }) {
  const [form, setForm] = useState({ source: '', amount: '', category: categories[0] })
  const canSave = form.amount && (form.source || form.category)

  const submit = () => {
    if (!canSave) return
    onAdd({
      source: form.source || form.category,
      amount: parseFloat(form.amount),
      category: form.category,
      month,
      date: new Date().toISOString().split('T')[0],
    })
    setForm({ source: '', amount: '', category: categories[0] })
  }

  return (
    <div className="glass" style={{ padding: '20px 22px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18 }}>{title}</div>
        <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 22, color: totalColor }}>{fmtDol(total)}</div>
      </div>

      {!demoMode && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 90px 60px', gap: 6, marginBottom: 14 }}>
          <select value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
            style={inputStyle}>
            {categories.map(c => <option key={c}>{c}</option>)}
          </select>
          <input placeholder="Source (optional)" value={form.source}
            onChange={e => setForm(f => ({ ...f, source: e.target.value }))}
            style={inputStyle} />
          <input type="number" placeholder="Amount" value={form.amount}
            onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
            style={inputStyle} />
          <button onClick={submit} disabled={!canSave}
            style={{ background: canSave ? 'rgba(201,168,76,0.18)' : 'rgba(255,255,255,0.04)',
                     border: '1px solid ' + (canSave ? 'rgba(201,168,76,0.4)' : 'rgba(255,255,255,0.08)'),
                     color: canSave ? 'var(--gold)' : 'var(--text-muted)',
                     fontSize: 11, borderRadius: 6, cursor: canSave ? 'pointer' : 'default' }}>
            Add
          </button>
        </div>
      )}

      {!entries.length
        ? <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No {title.toLowerCase()} this month.</div>
        : (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px 80px 30px', gap: 6, padding: '4px 0 6px', fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <span>Source</span><span>Category</span><span>Amount</span><span />
            </div>
            {entries.map(e => (
              <div key={e.id} style={{ display: 'grid', gridTemplateColumns: '1fr 90px 80px 30px', gap: 6, padding: '7px 0', fontSize: 11, borderBottom: '1px solid rgba(255,255,255,0.03)', alignItems: 'center' }}>
                <span style={{ color: 'var(--text-dim)' }}>{e.source}</span>
                <span style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{e.category}</span>
                <span style={{ fontFamily: '"IBM Plex Mono",monospace', color: totalColor }}>{fmtDol(e.amount)}</span>
                {!demoMode
                  ? <button onClick={() => onDelete(e.id)} className="edit-btn">✕</button>
                  : <span />}
              </div>
            ))}
          </div>
        )}
    </div>
  )
}

const inputStyle = {
  background: 'rgba(255,255,255,0.03)',
  border: '1px solid rgba(255,255,255,0.08)',
  color: 'var(--text-dim)',
  padding: '6px 8px',
  borderRadius: 6,
  fontSize: 11,
}

function EditValueModal({ title, label, current, onSave, onClose }) {
  const [val, setVal] = useState(current)
  return (
    <div className="modal-overlay open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box">
        <button onClick={onClose} style={{ position: 'absolute', top: 14, right: 16, fontSize: 16, background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>✕</button>
        <h2 className="modal-title">{title}</h2>
        <div className="mf"><label>{label}</label><input type="number" step="any" value={val} onChange={e => setVal(e.target.value)} /></div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
          <button className="mbtn cancel" onClick={onClose}>Cancel</button>
          <button className="mbtn save" onClick={() => onSave(parseFloat(val))}>Save</button>
        </div>
      </div>
    </div>
  )
}
