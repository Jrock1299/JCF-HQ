/**
 * Dashboard — JCF HQ Mission Control home page
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import {
  getTradesFile, getMarketBias, getPlaidData,
  getStoredData, getRobinhoodData, getTrustWalletData,
} from '../api/client.js'
import { fakeAmt } from '../context/DemoContext.jsx'
import { useIsMobile } from '../hooks/useIsMobile.js'

const STATS_POLL_MS = 120_000
const COST_POLL_MS  = 300_000
const GOAL_2037 = 10_000_000
const INS_DEFAULT = 900_000

function todayStr() { return new Date().toISOString().split('T')[0] }

function fmtCompact(n) {
  if (n == null) return '—'
  const abs = Math.abs(n), sign = n < 0 ? '-' : ''
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000)     return `${sign}$${(abs / 1_000).toFixed(1)}K`
  return `${sign}$${abs.toFixed(2)}`
}

function fmtSign(n) {
  const v = parseFloat(n || 0)
  return (v >= 0 ? '+' : '-') + '$' + Math.abs(v).toFixed(2)
}

function fmtDol(v) {
  return '$' + parseFloat(v || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function calcTodayPnl(trades = []) {
  const today = todayStr()
  return trades.reduce((sum, t) => {
    const ds = (t.close_date || t.close_time || t.close || t.open_time || t.date || '').split('T')[0]
    return ds === today ? sum + (parseFloat(t.pnl) || 0) : sum
  }, 0)
}

const ALL_AGENTS = [
  { id: 'huncho',     name: 'Huncho',     color: '#c9a84c' },
  { id: 'blade',      name: 'Blade',      color: '#f87171' },
  { id: 'crisp',      name: 'Crisp',      color: '#4ade80' },
  { id: 'jerry',      name: 'Jerry',      color: '#fb923c' },
  { id: 'phantom',    name: 'Phantom',    color: '#818cf8' },
  { id: 'lens',       name: 'Lens',       color: '#22d3ee' },
  { id: 'norman',     name: 'Norman',     color: '#34d399' },
  { id: 'victoria',   name: 'Victoria',   color: '#f9a8d4' },
  { id: 'forge',      name: 'Forge',      color: '#fbbf24' },
  { id: 'lucy',       name: 'Lucy',       color: '#c9a84c' },
  { id: 'strategist', name: 'Strategist', color: '#c9a84c' },
  { id: 'tao',        name: 'Tao',        color: '#c9a84c' },
]

export default function Dashboard({ demoMode, isActive = true }) {
  const isMobile = useIsMobile()
  const [trades,       setTrades]       = useState(null)
  const [bias,         setBias]         = useState(null)
  const [plaid,        setPlaid]        = useState(null)
  const [stored,       setStored]       = useState(null)
  const [rh,           setRh]           = useState(null)
  const [tw,           setTw]           = useState(null)
  const [jerryPf,      setJerryPf]      = useState(null)
  const [phantomPf,    setPhantomPf]    = useState(null)
  const [agentStatus,  setAgentStatus]  = useState({})
  const [apiCosts,     setApiCosts]     = useState(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const statsTimer = useRef(null)
  const costTimer  = useRef(null)

  const loadStats = useCallback(async () => {
    try {
      const [tl, mb, pd, st, rh_, tw_] = await Promise.allSettled([
        getTradesFile(), getMarketBias(), getPlaidData(),
        getStoredData(), getRobinhoodData(), getTrustWalletData(),
      ])
      if (tl.status  === 'fulfilled') setTrades(tl.value)
      if (mb.status  === 'fulfilled') setBias(mb.value)
      if (pd.status  === 'fulfilled') setPlaid(pd.value)
      if (st.status  === 'fulfilled') setStored(st.value)
      if (rh_.status === 'fulfilled') setRh(rh_.value)
      if (tw_.status === 'fulfilled') setTw(tw_.value)

      try {
        const jResp = await fetch('/hq/jerry-portfolio')
        if (jResp.ok) setJerryPf(await jResp.json())
      } catch {}
      try {
        const pResp = await fetch('/hq/phantom-portfolio')
        if (pResp.ok) setPhantomPf(await pResp.json())
      } catch {}
      try {
        const sResp = await fetch('/hq/agent-status')
        if (sResp.ok) setAgentStatus(await sResp.json())
      } catch {}
      try {
        const cResp = await fetch('/hq/api-costs')
        if (cResp.ok) setApiCosts(await cResp.json())
      } catch {}
    } catch (err) { console.error('[Dashboard] stats error', err) }
    finally { setStatsLoading(false) }
  }, [])

  const loadCosts = useCallback(async () => {
    try {
      const cResp = await fetch('/hq/api-costs')
      if (cResp.ok) setApiCosts(await cResp.json())
    } catch {}
  }, [])

  useEffect(() => { loadStats() }, [loadStats])
  useEffect(() => { loadCosts() }, [loadCosts])
  useEffect(() => {
    if (!isActive) { clearInterval(statsTimer.current); clearInterval(costTimer.current); return }
    statsTimer.current = setInterval(loadStats, STATS_POLL_MS)
    costTimer.current  = setInterval(loadCosts, COST_POLL_MS)
    return () => { clearInterval(statsTimer.current); clearInterval(costTimer.current) }
  }, [isActive, loadStats, loadCosts])

  const now      = new Date()
  const hour     = now.getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const dateStr  = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
  const demoGreetingName = demoMode ? 'Trader' : 'Jase'

  // Net worth
  const plaidTotal  = plaid?.accounts?.reduce((s, a) => s + (parseFloat(a.balance) || 0), 0) ?? 0
  const tlBal       = parseFloat(trades?.balance || 0)
  const rhBal       = parseFloat(rh?.total_equity || rh?.equity || 0)
  const twBal       = parseFloat(tw?.total_usd || 0)
  const manualAccts = stored?.accounts || {}
  const insBal      = parseFloat(manualAccts?.ins?.balance ?? manualAccts?.life_insurance?.balance ?? INS_DEFAULT)
  const myBankroll  = parseFloat(stored?.my_bankroll?.current || stored?.my_bankroll?.bankroll || 0)
  const _yrStart    = (() => { const d = new Date(); d.setMonth(0, 1); d.setHours(0, 0, 0, 0); return d })()
  const incYtd      = (stored?.income_entries || []).filter(e => new Date(e.date) >= _yrStart).reduce((s, e) => s + (parseFloat(e.amount) || 0), 0)
  const netWorth    = plaidTotal + tlBal + rhBal + twBal + insBal + myBankroll + incYtd

  const goalPct  = Math.min(100, (netWorth / GOAL_2037) * 100)
  const daysLeft = Math.max(0, Math.round((new Date('2037-12-31') - new Date()) / 86400000))
  const reqMo    = netWorth < GOAL_2037 ? (GOAL_2037 - netWorth) / (daysLeft / 30) : 0

  const tradingPnlToday = trades ? calcTodayPnl(trades.trades || []) : 0
  const jerryDailyPnl   = parseFloat(jerryPf?.daily_pnl ?? jerryPf?.total_pnl ?? 0)
  const phantomDailyPnl = parseFloat(phantomPf?.daily_pnl ?? phantomPf?.total_pnl ?? 0)
  const ytdPnl          = (trades?.trades || []).reduce((s, t) => s + (parseFloat(t.pnl) || 0), 0)

  const agentRows = [
    { id: 'blade',   name: 'Blade',   type: 'Forex',      pnl: tradingPnlToday, color: '#f87171' },
    { id: 'crisp',   name: 'Crisp',   type: 'Crypto',     pnl: 0,               color: '#4ade80' },
    { id: 'jerry',   name: 'Jerry',   type: 'Stocks',     pnl: jerryDailyPnl,   color: '#fb923c' },
    { id: 'phantom', name: 'Phantom', type: 'Futures',    pnl: phantomDailyPnl, color: '#818cf8' },
    { id: 'tao',     name: 'Tao',     type: 'Staking',    pnl: 0,               color: '#c9a84c' },
  ]
  const agentPnlTotal = agentRows.reduce((s, r) => s + r.pnl, 0)
  const activeAgents  = ALL_AGENTS.filter(a => agentStatus[a.id] === 'active')

  // Demo values
  const D        = demoMode
  const dNw      = fakeAmt('dash.nw',  52000, 78000)
  const dReqMo   = fakeAmt('dash.req', 3500,  8000)
  const dGoalPct = dNw / GOAL_2037 * 100
  const dTdPnl   = fakeAmt('dash.pnl', 80, 420)

  const displayNw      = D ? fmtCompact(dNw)   : fmtCompact(netWorth)
  const displayGoalPct = D ? dGoalPct           : goalPct
  const displayReqMo   = D ? fmtCompact(dReqMo) : fmtCompact(reqMo)

  return (
    <div>
      {/* ── Greeting ─────────────────────────────────────────────────── */}
      <div className="flex items-end justify-between mb-6">
        <div className="min-w-0">
          <div className="text-[9px] tracking-[3px] uppercase text-muted mb-1">{dateStr}</div>
          <h1 style={{ fontFamily: '"Playfair Display", serif', fontSize: isMobile ? 22 : 26, marginBottom: 0, color: 'var(--text-primary)' }}>
            {greeting}, <span style={{ color: 'var(--gold)' }}>{demoGreetingName}</span>
          </h1>
        </div>
        <div className="hidden md:flex items-center gap-2 text-[9px] tracking-[2px] uppercase text-muted shrink-0 ml-4 pb-1">
          <span className="status-dot" />
          <span>Live</span>
        </div>
      </div>

      {/* ── A) Wealth Goal Card ──────────────────────────────────────── */}
      <div className="glass" style={{
        border: '1px solid rgba(201,168,76,0.2)',
        borderTop: '2px solid var(--gold)',
        padding: isMobile ? '20px 18px' : '28px 32px',
        marginBottom: 14,
        position: 'relative',
        overflow: 'hidden',
      }}>
        <div style={{ position: 'absolute', top: -60, right: -60, width: 300, height: 300, background: 'radial-gradient(circle,rgba(201,168,76,0.07) 0%,transparent 70%)', pointerEvents: 'none' }} />

        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16, flexWrap: isMobile ? 'wrap' : 'nowrap', gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 9, letterSpacing: 4, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>2037 Wealth Goal</div>
            {statsLoading
              ? <div className="animate-pulse-slow" style={{ height: 44, width: 280, background: 'rgba(255,255,255,0.04)', borderRadius: 6 }} />
              : <div style={{ fontFamily: '"Playfair Display",serif', fontSize: isMobile ? 28 : 36, fontWeight: 700, color: 'var(--gold)', lineHeight: 1, textShadow: '0 0 40px rgba(201,168,76,0.2)' }}>
                  <span>{displayNw}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: isMobile ? 16 : 22 }}> / $10.00M</span>
                </div>
            }
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 5 }}>{daysLeft.toLocaleString()} days remaining · Started Jan 1, 2024</div>
          </div>
          <div style={{ display: 'flex', gap: isMobile ? 16 : 32, textAlign: 'right', flexShrink: 0 }}>
            <div>
              <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Progress</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 14, color: 'var(--gold)' }}>{displayGoalPct.toFixed(1)}%</div>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Required / Mo</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 14, color: 'var(--text-primary)' }}>{displayReqMo}</div>
            </div>
          </div>
        </div>

        <div style={{ height: 6, background: 'rgba(255,255,255,0.04)', borderRadius: 3, marginBottom: 10, overflow: 'hidden', position: 'relative' }}>
          <div style={{ height: '100%', width: `${displayGoalPct}%`, background: 'linear-gradient(90deg,var(--gold),var(--gold-light))', borderRadius: 3, boxShadow: '0 0 12px rgba(201,168,76,0.5)', transition: 'width .8s' }} />
        </div>

        {!isMobile && (
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
            {[
              { label: '$0',    sub: 'Start'   },
              { label: displayNw, sub: 'Today ▲' },
              { label: '$1M',   sub: 'Next'    },
              { label: '$2.5M', sub: '2028'    },
              { label: '$5M',   sub: '2031'    },
              { label: '$10M',  sub: '2037'    },
            ].map((m, i) => (
              <div key={i} style={{ textAlign: 'center' }}>
                <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: i === 1 ? 'var(--gold)' : 'var(--text-muted)' }}>{m.label}</div>
                <div style={{ fontSize: 8, color: 'var(--text-muted)', opacity: 0.6 }}>{m.sub}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── B) Agent P&L + Trading P&L side by side ─────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 12, marginBottom: 14 }}>

        {/* Agent P&L Today */}
        <div className="glass" style={{ padding: '20px 22px' }}>
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 9, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>Agent P&L Today</div>
            <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 30, color: agentPnlTotal >= 0 ? 'var(--green)' : 'var(--red)', lineHeight: 1 }}>
              {statsLoading ? '—' : D ? fmtSign(dTdPnl * 1.3) : fmtSign(agentPnlTotal)}
            </div>
          </div>
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: 12 }}>
            {agentRows.map(row => {
              const pnlColor = row.id === 'tao' ? 'var(--gold)'
                : row.pnl > 0 ? 'var(--green)'
                : row.pnl < 0 ? 'var(--red)'
                : 'rgba(255,255,255,0.3)'
              return (
                <div key={row.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: agentStatus[row.id] === 'active' ? '#4ade80' : 'rgba(255,255,255,0.2)', flexShrink: 0, boxShadow: agentStatus[row.id] === 'active' ? '0 0 5px #4ade8080' : 'none' }} />
                  <span style={{ fontSize: 13, fontWeight: 600, color: row.color, flex: 1 }}>{row.name}</span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>{row.type}</span>
                  <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: statsLoading ? 'rgba(255,255,255,0.2)' : pnlColor }}>
                    {statsLoading ? '—' : D ? fmtSign(fakeAmt(`dash.agent.${row.id}`, -20, 120)) : (row.pnl !== 0 ? fmtSign(row.pnl) : '—')}
                  </span>
                </div>
              )
            })}
          </div>
        </div>

        {/* Trading P&L Today */}
        <div className="glass" style={{ padding: '20px 22px' }}>
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 9, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>Trading P&L Today</div>
            <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 30, color: tradingPnlToday >= 0 ? 'var(--green)' : 'var(--red)', lineHeight: 1 }}>
              {statsLoading ? '—' : D ? fmtSign(dTdPnl) : fmtSign(tradingPnlToday)}
            </div>
          </div>
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: 12 }}>
            {[
              { label: 'Hero FX Balance', val: D ? fmtDol(fakeAmt('dash.tl.bal', 18000, 45000)) : fmtDol(tlBal), color: 'var(--text-primary)' },
              { label: 'YTD P&L',         val: D ? fmtSign(fakeAmt('dash.tl.ytd', 800, 4000))  : fmtSign(ytdPnl), color: ytdPnl >= 0 ? 'var(--green)' : 'var(--red)' },
              { label: 'Session P&L',     val: D ? fmtSign(dTdPnl) : fmtSign(tradingPnlToday), color: tradingPnlToday >= 0 ? 'var(--green)' : 'var(--red)' },
            ].map(row => (
              <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{row.label}</span>
                <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: statsLoading ? 'rgba(255,255,255,0.2)' : row.color }}>{statsLoading ? '—' : row.val}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── B2) API Costs Card ──────────────────────────────────────── */}
      <ApiCostsCard costs={apiCosts} isMobile={isMobile} />

      {/* ── C) Active Agents Strip ───────────────────────────────────── */}
      <div className="glass" style={{ padding: '12px 18px', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', flexShrink: 0 }}>Active now</span>
        {activeAgents.length === 0
          ? <span style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>No agents currently active</span>
          : activeAgents.map(a => (
            <span key={a.id} style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              padding: '4px 12px', borderRadius: 20,
              background: `${a.color}12`, border: `1px solid ${a.color}30`,
            }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#4ade80', boxShadow: '0 0 5px #4ade8080' }} />
              <span style={{ fontSize: 12, color: a.color, fontWeight: 600 }}>{a.name}</span>
            </span>
          ))
        }
      </div>

      {/* ── D) Intelligence: Morning Report + Priorities ─────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Intelligence</h3><div className="section-line" /></div>
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 340px', gap: 12, marginBottom: 14 }}>
        <CollapsibleCard title="Morning Report"    loading={statsLoading} htmlContent={bias?.morning_report} emptyMsg="Waiting for Huncho's morning report…" />
        <CollapsibleCard title="Today's Priorities" loading={statsLoading} htmlContent={bias?.priorities}    emptyMsg="No priorities loaded yet." />
      </div>
    </div>
  )
}

const AGENT_COLORS = {
  lens:    '#22d3ee', victoria: '#f9a8d4',
  jerry:   '#fb923c', phantom:  '#818cf8',
  norman:   '#34d399', forge:   '#fbbf24', naomi:    '#f472b6',
  lucy:     '#c9a84c', blade:   '#f87171', crisp:    '#4ade80',
  edge:     '#38bdf8', huncho:  '#c9a84c',
}

function ApiCostsCard({ costs, isMobile }) {
  if (!costs) return null

  const today   = costs.today   || { total: 0, breakdown: {} }
  const mtd     = costs.mtd     || { total: 0, breakdown: {} }
  const proj    = costs.projected_monthly || 0

  // Build sorted agent list by today's cost descending
  const agents = Object.keys(today.breakdown)
    .filter(k => (today.breakdown[k] || 0) > 0 || (mtd.breakdown[k] || 0) > 0)
    .sort((a, b) => (today.breakdown[b] || 0) - (today.breakdown[a] || 0))

  const maxToday = Math.max(...agents.map(k => today.breakdown[k] || 0), 0.001)

  return (
    <div className="glass" style={{ padding: isMobile ? '18px 16px' : '20px 24px', marginBottom: 14 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16, lineHeight: 1 }}>$</span>
          <span style={{ fontSize: 9, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)' }}>API Costs</span>
        </div>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>
          Projected: ~${proj.toFixed(2)}/mo
        </span>
      </div>

      {/* Today / MTD totals */}
      <div style={{ display: 'flex', gap: 24, marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 3 }}>Today</div>
          <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 18, color: 'var(--text-primary)' }}>
            ${today.total.toFixed(2)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 3 }}>MTD</div>
          <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 18, color: 'var(--text-primary)' }}>
            ${mtd.total.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Per-agent bars */}
      {agents.length === 0
        ? <p style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', margin: 0 }}>No cost data for today</p>
        : (
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '6px 24px' }}>
            {agents.map(agent => {
              const cost    = today.breakdown[agent] || 0
              const barPct  = maxToday > 0 ? (cost / maxToday) * 100 : 0
              const color   = AGENT_COLORS[agent] || '#c9a84c'
              const barColor = cost >= 3 ? '#f87171' : cost >= 1 ? '#fbbf24' : color
              return (
                <div key={agent} style={{ paddingBottom: 6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                    <span style={{ fontSize: 11, fontWeight: 600, color, textTransform: 'capitalize' }}>{agent}</span>
                    <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, color: barColor }}>
                      ${cost.toFixed(2)}
                    </span>
                  </div>
                  <div style={{ height: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{
                      height: '100%', width: `${barPct}%`,
                      background: barColor,
                      borderRadius: 2,
                      boxShadow: cost >= 1 ? `0 0 6px ${barColor}80` : 'none',
                      transition: 'width .6s',
                    }} />
                  </div>
                </div>
              )
            })}
          </div>
        )
      }
    </div>
  )
}

function CollapsibleCard({ title, loading, htmlContent, emptyMsg }) {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <div className="glass">
      <div onClick={() => setCollapsed(c => !c)}
        style={{ padding: '18px 22px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}>
        <span style={{ fontFamily: '"Playfair Display", serif', fontSize: 18, color: 'var(--text-primary)' }}>{title}</span>
        <span style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)' }}>{collapsed ? 'expand' : 'collapse'}</span>
      </div>
      {!collapsed && (
        <div style={{ padding: '0 22px 18px' }}>
          {loading
            ? <div className="space-y-2">{[80,65,90,55,70].map((w,i) => <div key={i} className="h-3 rounded animate-pulse-slow" style={{ width: `${w}%`, background: 'rgba(255,255,255,0.04)' }} />)}</div>
            : htmlContent
              ? <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.8 }} dangerouslySetInnerHTML={{ __html: htmlContent }} />
              : <p style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>{emptyMsg}</p>
          }
        </div>
      )}
    </div>
  )
}
