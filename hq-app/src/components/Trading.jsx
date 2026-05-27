/**
 * Trading — multi-account, log trade, market filter, P&L calendar, trade log
 * Data: tradelocker_trades.json, /hq/data (manual_trades, trading_accounts)
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { getTradesFile, getStoredData, updateStoredData, patchTradelockerTrade, getAgentPnl, getAgentTrades, getGoatFile } from '../api/client.js'
import { fakeAmt } from '../context/DemoContext.jsx'
import { useIsMobile } from '../hooks/useIsMobile.js'

const POLL_MS = 30_000
const PERIOD_START = '2026-03-06'
const GOAL = 10000

const DEFAULT_ACCOUNT = {
  id: 'hero-fx-live',
  name: 'Hero FX — Live',
  broker: 'Hero FX',
  profit_split: '100%',
  start_date: '2026-03-06',
  target: 10000,
  status: 'Active',
}

const GOAT_ACCOUNT = {
  id: 'goat-funded-live-25k',
  name: 'Goat Funded Live 25k',
  broker: 'Goat Funded Trader',
  profit_split: '80%',
  start_date: '2026-04-01',
  target: 25000,
  status: 'Active',
}

const MARKET_FILTERS = [
  { key: 'all',         label: 'All' },
  { key: 'tradelocker', label: 'TradeLocker' },
  { key: 'phemex',      label: 'Phemex' },
  { key: 'oanda',       label: 'OANDA' },
  { key: 'manual',      label: 'Manual' },
]

const SOURCE_BADGE = {
  tradelocker: { label: 'TL',    bg: 'rgba(74,222,128,0.12)',  bd: 'rgba(74,222,128,0.3)',   col: '#4ade80' },
  phemex:      { label: 'PHX',   bg: 'rgba(167,139,250,0.12)', bd: 'rgba(167,139,250,0.3)',  col: '#a78bfa' },
  oanda:       { label: 'OANDA', bg: 'rgba(96,165,250,0.12)',  bd: 'rgba(96,165,250,0.3)',   col: '#60a5fa' },
  manual:      { label: 'MAN',   bg: 'rgba(255,255,255,0.06)', bd: 'rgba(255,255,255,0.15)', col: 'rgba(255,255,255,0.45)' },
}

function todayStr(){return new Date().toISOString().split('T')[0]}
function fmtD(v){const n=parseFloat(v)||0;return(n>=0?'+':'')+'\u0024'+Math.abs(n).toFixed(2)}
function fmtDol(v){return '\u0024'+parseFloat(v||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fmtShortDate(ts){if(!ts)return'—';try{const d=new Date(ts);return['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()]+' '+d.getDate()}catch{return'—'}}

export default function Trading({ demoMode, isActive=true }) {
  const isMobile = useIsMobile()
  const [trades,      setTrades]      = useState(null)
  const [storedData,  setStoredData]  = useState(null)
  const [goatData,    setGoatData]    = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [agentPnl,    setAgentPnl]    = useState(null)
  const [agentTrades, setAgentTrades] = useState(null)
  const [editIdx,     setEditIdx]     = useState(null)
  const [page,        setPage]        = useState(0)
  const [marketFilter,setMarketFilter]= useState('all')
  const [activeAcctId,setActiveAcctId]= useState('hero-fx-live')
  const [showLog,     setShowLog]     = useState(false)
  const [showAddAcct, setShowAddAcct] = useState(false)
  const [nameOverrides, setNameOverrides] = useState(() => {
    try { return JSON.parse(localStorage.getItem('tradingAccountNames') || '{}') } catch { return {} }
  })
  const [editingAcctId, setEditingAcctId] = useState(null)
  const [editNameVal,   setEditNameVal]   = useState('')
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const [t, sd, gd, ap, at] = await Promise.allSettled([getTradesFile(), getStoredData(), getGoatFile(), getAgentPnl(), getAgentTrades()])
      if (t.status  === 'fulfilled') setTrades(t.value)
      if (sd.status === 'fulfilled') setStoredData(sd.value)
      if (gd.status === 'fulfilled') setGoatData(gd.value)
      if (ap.status === 'fulfilled') setAgentPnl(ap.value)
      if (at.status === 'fulfilled') setAgentTrades(at.value)
    } catch(e) { console.error('[Trading]', e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!isActive) { clearInterval(timer.current); return }
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [isActive, load])

  // Build Goat accounts from synced file (multi-account format) or fall back to hardcoded
  const goatFileAccounts = (() => {
    if (!goatData) return null
    // New multi-account format: { accounts: [{id, name, balance, type, trades}, ...] }
    if (Array.isArray(goatData.accounts)) {
      return goatData.accounts.map(a => ({
        id: String(a.id),
        name: a.name || 'Goat Account',
        broker: 'Goat Funded Trader',
        profit_split: '80%',
        start_date: '2026-04-01',
        target: a.name?.includes('100k') ? 100000 : a.name?.includes('25k') ? 25000 : 25000,
        status: 'Active',
        balance: a.balance,
        type: a.type || 'LIVE',
        _trades: a.trades || [],
        _pnl: a.pnl,
      }))
    }
    // Legacy single-account format: { balance, trades, ... }
    return [{
      ...GOAT_ACCOUNT,
      balance: goatData.balance,
      type: 'LIVE',
      _trades: goatData.trades || [],
    }]
  })()

  // Stored accounts excluding any that duplicate goat accounts by name
  const storedAccts = (storedData?.trading_accounts ?? [])
  const goatNames = new Set((goatFileAccounts || [GOAT_ACCOUNT]).map(a => (a.name || '').toLowerCase()))
  const nonDupStoredAccts = storedAccts.filter(a => {
    if (a.id === DEFAULT_ACCOUNT.id) return false
    // Exclude stored accounts whose names match goat accounts (dedup)
    if ((a.name || '').toLowerCase().includes('goat') || goatNames.has((a.name || '').toLowerCase())) return false
    return true
  })

  const goatAccounts = goatFileAccounts || [GOAT_ACCOUNT]
  const accounts = [DEFAULT_ACCOUNT, ...goatAccounts, ...nonDupStoredAccts]
    .map(a => nameOverrides[a.id] ? { ...a, name: nameOverrides[a.id] } : a)
  const activeAccount = accounts.find(a => a.id === activeAcctId) || DEFAULT_ACCOUNT

  function commitAcctRename(acctId) {
    const trimmed = editNameVal.trim()
    const next = { ...nameOverrides }
    if (!trimmed) { delete next[acctId] } else { next[acctId] = trimmed }
    setNameOverrides(next)
    try { localStorage.setItem('tradingAccountNames', JSON.stringify(next)) } catch {}
    setEditingAcctId(null)
  }

  // Merged trade list — TL trades + manual trades
  const tlTrades = (trades?.trades ?? []).map((t, i) => ({
    ...t, source: 'tradelocker', account_id: 'hero-fx-live', _origIdx: i, _isManual: false,
  }))
  const manualTrades = (storedData?.manual_trades ?? []).map((t, i) => ({
    ...t, _origIdx: i, _isManual: true,
  }))
  const allTrades = [...tlTrades, ...manualTrades]

  // Account-filtered base (for stats, calendar)
  const acctTrades = activeAcctId === 'hero-fx-live'
    ? allTrades.filter(t => !t.account_id || t.account_id === 'hero-fx-live')
    : allTrades.filter(t => t.account_id === activeAcctId)

  // Market-filtered for trade log display
  const displayTrades = marketFilter === 'all'
    ? acctTrades
    : acctTrades.filter(t => t.source === marketFilter)

  const today = todayStr()
  const PAGE_SIZE = 10
  const tradeDate = t => t.close_date || t.open_date || t.date || ''
  const sorted    = [...displayTrades].sort((a, b) => tradeDate(b).localeCompare(tradeDate(a)))
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const safePage   = Math.min(page, totalPages - 1)
  const pageTrades = sorted.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE)

  // Stats from account-filtered trades (all markets)
  const tradeList  = acctTrades
  const periodTrades = tradeList.filter(t => {
    const ds = (t.close_date||t.close_time||t.close||t.open_time||t.date||'').split('T')[0]
    return ds >= PERIOD_START
  })
  const periodPnl = periodTrades.reduce((s, t) => s + (parseFloat(t.pnl) || 0), 0)
  const todayPnl  = tradeList.reduce((s, t) => {
    const ds = (t.close_date||t.close_time||t.close||t.open_time||t.date||'').split('T')[0]
    return ds === today ? s + (parseFloat(t.pnl) || 0) : s
  }, 0)
  const wins   = tradeList.filter(t => parseFloat(t.pnl) > 0).length
  const losses = tradeList.filter(t => parseFloat(t.pnl) < 0).length
  const wr     = tradeList.length ? Math.round(wins / tradeList.length * 100) : 0
  const progPct = Math.min(100, (periodPnl / GOAL) * 100)

  // Calendar from account-filtered trades
  const calMap = {}
  tradeList.forEach(t => {
    const ds = (t.close_date||t.close_time||t.close||t.open_time||t.date||'').split('T')[0]
    if (!ds) return
    calMap[ds] = (calMap[ds] || 0) + (parseFloat(t.pnl) || 0)
  })

  // Demo fakes
  const D = demoMode
  const dBalance   = fakeAmt('trd.bal',   18000, 45000)
  const dPeriodPnl = fakeAmt('trd.ppl',     200,  1800)
  const dTodayPnl  = fakeAmt('trd.tdpnl',    40,   380)
  const dProgPct   = Math.min(100, (dPeriodPnl / GOAL) * 100)

  const activeBalance = activeAcctId === 'hero-fx-live'
    ? trades?.balance
    : (activeAccount?.balance ?? activeAccount?.balance)

  async function handleSave(idx, form) {
    const patch = {}
    if (form.pnl !== '')         patch.pnl         = parseFloat(form.pnl)
    if (form.entry_price !== '') patch.entry_price  = parseFloat(form.entry_price)
    if (form.exit_price !== '')  patch.exit_price   = parseFloat(form.exit_price)
    if (form.qty !== '')         patch.qty          = parseFloat(form.qty)
    if (form.side !== '')        patch.side         = form.side
    try { await patchTradelockerTrade(idx, patch) } catch(e) { console.error('[handleSave]', e) }
    setEditIdx(null); load()
  }

  async function handleLogTrade(form) {
    const trade = {
      date:        form.date,
      source:      form.source,
      account_id:  activeAcctId,
      symbol:      form.symbol,
      side:        form.direction,
      lots:        form.qty || null,
      entry_price: form.entry_price || null,
      exit_price:  form.exit_price || null,
      pnl:         parseFloat(form.pnl) || 0,
      notes:       form.notes || null,
      manual_edit: true,
    }
    const current = storedData?.manual_trades ?? []
    try { await updateStoredData({ manual_trades: [...current, trade] }) } catch(e) { console.error('[logTrade]', e) }
    setShowLog(false); load()
  }

  async function handleAddAccount(form) {
    const acct = {
      id:          `acct-${Date.now().toString(36)}`,
      name:        form.name,
      broker:      form.broker,
      balance:     parseFloat(form.balance) || 0,
      profit_split:form.profit_split,
      start_date:  form.start_date,
      target:      parseFloat(form.target) || 0,
      status:      form.status,
    }
    const current = storedData?.trading_accounts ?? []
    try { await updateStoredData({ trading_accounts: [...current, acct] }) } catch(e) { console.error('[addAcct]', e) }
    setShowAddAcct(false); load()
  }

  const statCols  = isMobile ? 'repeat(2,1fr)' : 'repeat(4,1fr)'
  const heroLayout = isMobile ? '1fr' : '1fr auto'

  // Grid columns for trade log table — src | date | symbol | dir | lots | open | close | pnl | btn
  const TBL_COLS = isMobile
    ? '46px 72px 72px 44px 58px 58px 60px 60px'
    : '46px 88px 82px 46px 52px 72px 72px 72px 78px'

  return (
    <div>
      <h1 className="page-title">Trading Operations</h1>

      {/* ── Account Selector ─────────────────────────────────────────── */}
      <div style={{display:'flex',gap:8,marginBottom:12,flexWrap:'wrap',alignItems:'center'}}>
        {accounts.map(acct => {
          const isEditing = editingAcctId === acct.id
          const isActive  = activeAcctId === acct.id
          if (isEditing) {
            return (
              <div key={acct.id} style={{display:'flex',alignItems:'center',gap:4,
                padding:'3px 6px',borderRadius:8,background:'rgba(201,168,76,0.06)',
                border:'1px solid rgba(201,168,76,0.35)'}}>
                <input autoFocus value={editNameVal}
                  onChange={e => setEditNameVal(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter')  commitAcctRename(acct.id)
                    if (e.key === 'Escape') setEditingAcctId(null)
                  }}
                  style={{padding:'4px 8px',borderRadius:6,fontSize:11,fontWeight:600,
                    background:'rgba(0,0,0,0.25)',color:'var(--gold)',
                    border:'1px solid rgba(201,168,76,0.3)',outline:'none',
                    fontFamily:'inherit',minWidth:180}}/>
                <button onClick={() => commitAcctRename(acct.id)} title="Save"
                  style={{padding:'3px 7px',borderRadius:5,cursor:'pointer',fontSize:10,
                    background:'rgba(74,222,128,0.14)',color:'var(--green)',
                    border:'1px solid rgba(74,222,128,0.35)'}}>✓</button>
                <button onClick={() => setEditingAcctId(null)} title="Cancel"
                  style={{padding:'3px 7px',borderRadius:5,cursor:'pointer',fontSize:10,
                    background:'rgba(255,255,255,0.02)',color:'var(--text-muted)',
                    border:'1px solid rgba(255,255,255,0.08)'}}>✕</button>
              </div>
            )
          }
          const btnBg     = isActive ? 'rgba(201,168,76,0.1)' : 'rgba(255,255,255,0.02)'
          const btnColor  = isActive ? 'var(--gold)' : 'var(--text-muted)'
          const btnBorder = isActive ? '1px solid rgba(201,168,76,0.3)' : '1px solid rgba(255,255,255,0.07)'
          return (
            <div key={acct.id} style={{display:'flex',alignItems:'stretch'}}>
              <button onClick={() => { setActiveAcctId(acct.id); setPage(0) }}
                style={{
                  padding:'6px 10px 6px 14px',borderRadius:'8px 0 0 8px',
                  cursor:'pointer',fontSize:11,fontWeight:600,
                  background:btnBg,color:btnColor,border:btnBorder,borderRight:'none',
                  transition:'all .15s',
                }}>
                {acct.name}
                {acct.type === 'EVAL' && (
                  <span style={{marginLeft:6,fontSize:8,padding:'1px 5px',borderRadius:3,background:'rgba(250,204,21,0.12)',color:'#facc15',border:'1px solid rgba(250,204,21,0.3)',textTransform:'uppercase',letterSpacing:0.5}}>EVAL</span>
                )}
                {acct.type === 'LIVE' && acct.id !== DEFAULT_ACCOUNT.id && (
                  <span style={{marginLeft:6,fontSize:8,padding:'1px 5px',borderRadius:3,background:'rgba(74,222,128,0.1)',color:'#4ade80',border:'1px solid rgba(74,222,128,0.25)',textTransform:'uppercase',letterSpacing:0.5}}>LIVE</span>
                )}
                {acct.status && acct.status !== 'Active' && !acct.type && (
                  <span style={{marginLeft:6,fontSize:9,opacity:0.65,textTransform:'uppercase'}}>{acct.status}</span>
                )}
              </button>
              <button onClick={() => { setEditNameVal(acct.name); setEditingAcctId(acct.id) }}
                title="Rename account"
                style={{
                  padding:'6px 9px',borderRadius:'0 8px 8px 0',cursor:'pointer',fontSize:11,
                  background:btnBg,color:btnColor,border:btnBorder,
                  borderLeft:'1px solid rgba(255,255,255,0.05)',
                  opacity:0.7,transition:'opacity .15s',
                }}
                onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                onMouseLeave={e => e.currentTarget.style.opacity = '0.7'}>
                ✎
              </button>
            </div>
          )
        })}
        <button onClick={() => setShowAddAcct(true)}
          style={{padding:'6px 12px',borderRadius:8,cursor:'pointer',fontSize:11,
            background:'rgba(255,255,255,0.02)',color:'var(--text-muted)',border:'1px solid rgba(255,255,255,0.06)'}}>
          + Add Account
        </button>
      </div>

      {/* ── Active account hero ──────────────────────────────────────── */}
      <div className="glass" style={{border:'1px solid rgba(201,168,76,0.2)',position:'relative',overflow:'hidden',marginBottom:16}}>
        <div style={{position:'absolute',bottom:0,left:0,right:0,height:2,background:'linear-gradient(90deg,var(--gold),transparent)'}}/>
        {loading
          ? <div style={{padding:'22px 26px',height:120}} className="animate-pulse-slow"/>
          : (
            <div style={{display:'grid',gridTemplateColumns:heroLayout,gap:24,padding:'22px 26px'}}>
              <div>
                <div style={{fontSize:8,letterSpacing:4,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:4}}>
                  Active Account — {activeAccount.broker || activeAccount.name}
                </div>
                <div style={{fontFamily:'"Playfair Display",serif',fontSize:isMobile?18:24,color:'var(--text-primary)',marginBottom:14}}>
                  {D
                    ? `Trading Account · ${fmtDol(dBalance)}`
                    : (activeBalance
                        ? `${activeAccount.name} · $${parseFloat(activeBalance).toLocaleString('en-US',{maximumFractionDigits:0})}`
                        : activeAccount.name)}
                </div>
                <div style={{display:'flex',gap:22,flexWrap:'wrap',marginBottom:14}}>
                  <Metric label="Balance"      value={D ? fmtDol(dBalance) : (activeBalance ? fmtDol(activeBalance) : '—')} color="var(--green)"/>
                  <Metric label="P&L"          value={D ? fmtD(dPeriodPnl) : fmtD(periodPnl)} color={(D?dPeriodPnl:periodPnl)>=0?'var(--green)':'var(--red)'}/>
                  <Metric label="Profit Split" value={activeAccount.profit_split || '100%'}      color="var(--text-primary)"/>
                  <Metric label="Start Date"   value={activeAccount.start_date ? fmtShortDate(activeAccount.start_date) : "Mar 6, '26"} color="var(--text-primary)"/>
                </div>
                {/* Progress bar */}
                {activeAcctId === 'hero-fx-live' && (
                  <div style={{marginBottom:4}}>
                    <div style={{fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:5}}>Target Progress — $10,000</div>
                    <div style={{display:'flex',justifyContent:'space-between',fontSize:9,color:'var(--text-muted)',marginBottom:6}}>
                      <span style={{fontFamily:'"IBM Plex Mono",monospace'}}>$0</span>
                      <span style={{color:'var(--gold)',fontFamily:'"IBM Plex Mono",monospace'}}>${(D?dPeriodPnl:periodPnl).toFixed(0)} of ${GOAL.toLocaleString()} needed</span>
                      <span style={{fontFamily:'"IBM Plex Mono",monospace'}}>$10,000</span>
                    </div>
                    <div style={{height:4,background:'rgba(255,255,255,0.04)',borderRadius:2,overflow:'hidden'}}>
                      <div style={{height:'100%',width:`${D?dProgPct:progPct}%`,background:'linear-gradient(90deg,var(--gold),var(--gold-light))',boxShadow:'0 0 8px rgba(201,168,76,0.5)',transition:'width .5s',borderRadius:2}}/>
                    </div>
                  </div>
                )}
                {activeAcctId !== 'hero-fx-live' && activeAccount.target > 0 && (
                  <div style={{marginBottom:4}}>
                    <div style={{fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:5}}>
                      Target — ${parseFloat(activeAccount.target).toLocaleString()}
                    </div>
                    <div style={{height:4,background:'rgba(255,255,255,0.04)',borderRadius:2,overflow:'hidden'}}>
                      <div style={{height:'100%',width:`${Math.min(100,(periodPnl/(activeAccount.target||1))*100)}%`,background:'linear-gradient(90deg,var(--gold),var(--gold-light))',borderRadius:2}}/>
                    </div>
                  </div>
                )}
              </div>
              {!isMobile && (
                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,minWidth:200}}>
                  <StatBlock label="Today P&L"  value={D ? fmtD(dTodayPnl) : fmtD(todayPnl)} color={(D?dTodayPnl:todayPnl)>=0?'var(--green)':'var(--red)'}/>
                  <StatBlock label="TradeLocker" value="✓ Synced" color="var(--green)"/>
                </div>
              )}
            </div>
          )}
      </div>

      {/* ── Trading stats (consolidated) ─────────────────────────────── */}
      <div className="section-head"><div className="section-line"/><h3>Trading Stats</h3><div className="section-line"/></div>
      <div className="glass" style={{padding:'20px 22px',marginBottom:16}}>
        <div style={{display:'grid',gridTemplateColumns:statCols,gap:20}}>
          {/* Row 1 */}
          <InlineStat label="Trades"      val={tradeList.length} loading={loading}/>
          <InlineStat label="Avg Lots"    val={tradeList.length ? (tradeList.reduce((s,t)=>s+(parseFloat(t.lots||t.qty||0)),0)/tradeList.length).toFixed(2) : '-'} color="var(--gold)" loading={loading}/>
          <div>
            <div style={{fontSize:9,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:8}}>Win Rate</div>
            {loading
              ? <div className="animate-pulse-slow" style={{height:32,width:60,background:'rgba(255,255,255,0.04)',borderRadius:4}}/>
              : <div>
                  <div style={{display:'flex',alignItems:'flex-end',justifyContent:'space-between',marginBottom:6}}>
                    <div style={{fontFamily:'"Playfair Display",serif',fontSize:isMobile?26:32,color:'var(--green)'}}>{wr}%</div>
                    <div style={{display:'flex',gap:4,paddingBottom:2}}>
                      <span className="pill pill-green">W{wins}</span>
                      <span className="pill pill-red">L{losses}</span>
                    </div>
                  </div>
                  <div style={{height:3,background:'rgba(255,255,255,0.04)',borderRadius:2,overflow:'hidden'}}>
                    <div style={{height:'100%',width:`${wr}%`,background:'linear-gradient(90deg,var(--green),rgba(74,222,128,0.5))',borderRadius:2}}/>
                  </div>
                </div>}
          </div>
          <InlineStat label="Most Traded" val={mostTraded(tradeList)} color="var(--cyan)" loading={loading}/>

          {/* Divider */}
          {!isMobile && <div style={{gridColumn:'1/-1',height:1,background:'rgba(255,255,255,0.05)',margin:'4px 0'}}/>}

          {/* Row 2 */}
          <InlineStat label="Profit Factor" val={profitFactor(tradeList)} color="var(--gold)" loading={loading}/>
          <InlineStat label="Consistency"   val={`${consistency(tradeList)}%`} color="var(--blue)" loading={loading}/>
          <div>
            <div style={{fontSize:9,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:8}}>Avg Win / Avg Loss</div>
            {loading
              ? <div className="animate-pulse-slow" style={{height:28,background:'rgba(255,255,255,0.04)',borderRadius:4}}/>
              : <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-end'}}>
                  <div><div style={{fontSize:8,color:'var(--text-muted)',marginBottom:2}}>Win</div><div style={{fontFamily:'"Playfair Display",serif',fontSize:isMobile?18:22,color:'var(--green)'}}>{'$'+avgWin(tradeList).toFixed(2)}</div></div>
                  <div style={{textAlign:'right'}}><div style={{fontSize:8,color:'var(--text-muted)',marginBottom:2}}>Loss</div><div style={{fontFamily:'"Playfair Display",serif',fontSize:isMobile?18:22,color:'var(--red)'}}>{'$'+avgLoss(tradeList).toFixed(2)}</div></div>
                </div>}
          </div>
          <div>
            <div style={{fontSize:9,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:8}}>Green / Red Days</div>
            {loading
              ? <div className="animate-pulse-slow" style={{height:32,width:60,background:'rgba(255,255,255,0.04)',borderRadius:4}}/>
              : (() => {
                  const days = {}
                  tradeList.forEach(t => {
                    const ds = (t.close_date||t.open_date||t.date||'').split('T')[0]
                    if (!ds) return
                    days[ds] = (days[ds] || 0) + (parseFloat(t.pnl) || 0)
                  })
                  const greenDays = Object.values(days).filter(v => v > 0).length
                  const redDays   = Object.values(days).filter(v => v < 0).length
                  return (
                    <div style={{fontFamily:'"Playfair Display",serif',fontSize:isMobile?20:26}}>
                      <span style={{color:'var(--green)'}}>{greenDays}G</span>
                      <span style={{color:'var(--text-muted)',fontSize:16,margin:'0 4px'}}>·</span>
                      <span style={{color:'var(--red)'}}>{redDays}R</span>
                    </div>
                  )
                })()
            }
          </div>
        </div>
      </div>

      {/* ── Bot Performance ──────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line"/><h3>Bot Performance</h3><div className="section-line"/></div>
      <div style={{display:'grid',gridTemplateColumns:isMobile?'1fr':'1fr 1fr 1fr',gap:12,marginBottom:16}}>
        <BotCard
          name="Blade"
          color="#d4a843"
          agentKey="blade"
          agentPnl={agentPnl}
          agentTrades={agentTrades}
          today={today}
          loading={loading}
        />
        <BotCard
          name="Edge"
          color="#60a5fa"
          agentKey="edge"
          agentPnl={agentPnl}
          agentTrades={agentTrades}
          today={today}
          loading={loading}
        />
        <BotCard
          name="Crisp"
          color="#4ade80"
          agentKey="crisp"
          agentPnl={agentPnl}
          agentTrades={agentTrades}
          today={today}
          loading={loading}
        />
      </div>

      {/* ── P&L Calendar ─────────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line"/><h3>P&L Calendar</h3><div className="section-line"/></div>
      <PnlCalendar calMap={calMap} loading={loading} isMobile={isMobile}/>

      {/* ── Trade log ────────────────────────────────────────────────── */}
      <div className="section-head" style={{marginTop:4}}>
        <div className="section-line"/>
        <h3>Trade Log</h3>
        <div className="section-line"/>
        <span className="pill pill-green ml-1 shrink-0">TradeLocker ✓</span>
        {!D && (
          <button onClick={() => setShowLog(true)}
            style={{marginLeft:8,padding:'4px 12px',borderRadius:6,cursor:'pointer',fontSize:11,fontWeight:600,
              background:'rgba(201,168,76,0.1)',color:'var(--gold)',border:'1px solid rgba(201,168,76,0.3)',
              whiteSpace:'nowrap',transition:'all .15s'}}>
            + Log Trade
          </button>
        )}
      </div>

      {/* Market filter */}
      <div style={{display:'flex',gap:6,marginBottom:10,flexWrap:'wrap'}}>
        {MARKET_FILTERS.map(f => (
          <button key={f.key} onClick={() => { setMarketFilter(f.key); setPage(0) }}
            style={{padding:'4px 12px',borderRadius:6,cursor:'pointer',fontSize:11,fontWeight:500,
              background: marketFilter===f.key ? 'rgba(201,168,76,0.08)' : 'rgba(255,255,255,0.02)',
              color:      marketFilter===f.key ? 'var(--gold)' : 'var(--text-muted)',
              border:     marketFilter===f.key ? '1px solid rgba(201,168,76,0.22)' : '1px solid rgba(255,255,255,0.06)',
              transition:'all .15s'}}>
            {f.label}
          </button>
        ))}
      </div>

      {loading
        ? <SkeletonTable/>
        : !sorted.length
          ? <div className="glass" style={{padding:'14px 18px',fontSize:11,color:'var(--text-muted)',fontStyle:'italic'}}>No trades found.</div>
          : (
            <div className="glass" style={{overflowX:'auto'}}>
              <div style={{padding:'8px 14px 4px',display:'grid',gridTemplateColumns:TBL_COLS,gap:6,fontSize:9,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',borderBottom:'1px solid rgba(255,255,255,0.06)',minWidth:560}}>
                {(isMobile
                  ? ['Src','Date','Sym','Dir','Lots','Open','Close','P&L']
                  : ['Src','Date','Symbol','Dir','Lots','Open','Close','P&L','']
                ).map(h => <span key={h}>{h}</span>)}
              </div>
              {pageTrades.map((t, i) => {
                const idx = t._origIdx
                const pnl = parseFloat(t.pnl) || 0
                const displayPnl = D ? fakeAmt('trd.row.'+idx+(t._isManual?'m':''), -150, 350) : pnl
                const rawDir = (t.side || t.direction || '').toLowerCase()
                const isLong  = rawDir === 'long'  || rawDir === 'buy'
                const isShort = rawDir === 'short' || rawDir === 'sell'
                const ds = (t.close_date || t.open_date || t.date || '').split('T')[0]
                const src = SOURCE_BADGE[t.source] || SOURCE_BADGE.manual
                return (
                  <div key={`${t._isManual?'m':'t'}-${idx}-${i}`}
                    style={{padding:'7px 14px',display:'grid',gridTemplateColumns:TBL_COLS,gap:6,fontSize:11,
                      borderBottom:'1px solid rgba(255,255,255,0.025)',alignItems:'center',minWidth:560}}>
                    <span>
                      <span style={{fontSize:8,padding:'2px 5px',borderRadius:3,background:src.bg,color:src.col,border:`1px solid ${src.bd}`,letterSpacing:0.5,fontWeight:700}}>
                        {src.label}
                      </span>
                    </span>
                    <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10,color:'var(--text-muted)'}}>{fmtShortDate(ds)}</span>
                    <span style={{fontFamily:'"IBM Plex Mono",monospace',color:'var(--text-dim)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{t.symbol || '—'}</span>
                    <span style={{fontSize:9,padding:'2px 5px',borderRadius:4,
                      background:isLong?'rgba(74,222,128,0.1)':isShort?'rgba(248,113,113,0.1)':'rgba(255,255,255,0.05)',
                      color:isLong?'var(--green)':isShort?'var(--red)':'var(--text-muted)',
                      border:`1px solid ${isLong?'rgba(74,222,128,0.2)':isShort?'rgba(248,113,113,0.2)':'rgba(255,255,255,0.1)'}`}}>
                      {isLong?'LONG':isShort?'SHORT':'—'}
                    </span>
                    <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10}}>{t.lots || t.qty || '—'}</span>
                    <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10,color:'var(--text-dim)'}}>{D ? '—' : (t.open_price || t.entry_price || '—')}</span>
                    <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10,color:'var(--text-dim)'}}>{D ? '—' : (t.close_price || t.exit_price || '—')}</span>
                    <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:11,fontWeight:600,color:displayPnl>=0?'var(--green)':'var(--red)'}}>
                      {(displayPnl>=0?'+':'-')+'$'+Math.abs(displayPnl).toFixed(2)}
                    </span>
                    {!isMobile && (
                      !D && !t._isManual
                        ? <button className="edit-btn" onClick={() => setEditIdx(idx)}>✎ edit</button>
                        : <span/>
                    )}
                  </div>
                )
              })}
              <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'10px 14px',borderTop:'1px solid rgba(255,255,255,0.06)'}}>
                <span style={{fontSize:10,color:'var(--text-muted)',fontFamily:'"IBM Plex Mono",monospace'}}>{sorted.length} trades</span>
                <div style={{display:'flex',alignItems:'center',gap:10}}>
                  <button className="edit-btn" onClick={() => setPage(p => Math.max(0, p-1))} disabled={safePage===0} style={{opacity:safePage===0?0.35:1}}>← Prev</button>
                  <span style={{fontSize:10,color:'var(--text-muted)',fontFamily:'"IBM Plex Mono",monospace'}}>Page {safePage+1} of {totalPages}</span>
                  <button className="edit-btn" onClick={() => setPage(p => Math.min(totalPages-1, p+1))} disabled={safePage===totalPages-1} style={{opacity:safePage===totalPages-1?0.35:1}}>Next →</button>
                </div>
              </div>
            </div>
          )}

      {/* ── Modals ──────────────────────────────────────────────────── */}
      {showLog && <LogTradeModal onSave={handleLogTrade} onClose={() => setShowLog(false)}/>}
      {showAddAcct && <AddAccountModal onSave={handleAddAccount} onClose={() => setShowAddAcct(false)}/>}
      {editIdx !== null && (
        <TradeEditModal trade={tlTrades[editIdx]} idx={editIdx} onSave={handleSave} onClose={() => setEditIdx(null)}/>
      )}
    </div>
  )
}

// ── Stat helpers ──────────────────────────────────────────────────────────
function mostTraded(list){if(!list.length)return'—';const c={};list.forEach(t=>{if(t.symbol)c[t.symbol]=(c[t.symbol]||0)+1});return Object.entries(c).sort((a,b)=>b[1]-a[1])[0]?.[0]||'—'}
function profitFactor(list){const g=list.reduce((s,t)=>{const p=parseFloat(t.pnl||0);return p>0?s+p:s},0);const l=list.reduce((s,t)=>{const p=parseFloat(t.pnl||0);return p<0?s+Math.abs(p):s},0);return l===0?g>0?'∞':'—':(g/l).toFixed(2)}
function consistency(list){if(!list.length)return 0;const w=list.filter(t=>parseFloat(t.pnl||0)>0).length;return Math.round(w/list.length*100)}
function avgWin(list){const wins=list.filter(t=>parseFloat(t.pnl||0)>0);return wins.length?wins.reduce((s,t)=>s+(parseFloat(t.pnl)||0),0)/wins.length:0}
function avgLoss(list){const losses=list.filter(t=>parseFloat(t.pnl||0)<0);return losses.length?Math.abs(losses.reduce((s,t)=>s+(parseFloat(t.pnl)||0),0)/losses.length):0}
function tradingDaysInMonth(){const now=new Date();const yr=now.getFullYear(),mo=now.getMonth();let cnt=0;for(let d=1;d<=now.getDate();d++){const day=new Date(yr,mo,d).getDay();if(day>=1&&day<=5)cnt++;}return cnt}

function Metric({label,value,color}){
  return(
    <div>
      <div style={{fontSize:8,letterSpacing:3,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:3}}>{label}</div>
      <div style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:16,color}}>{value}</div>
    </div>
  )
}

function StatBlock({label,value,color}){
  return(
    <div className="glass" style={{padding:'12px 16px',minWidth:110}}>
      <div style={{fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:4}}>{label}</div>
      <div style={{fontFamily:'"Playfair Display",serif',fontSize:20,color}}>{value}</div>
    </div>
  )
}

function InlineStat({label,val,color='var(--text-primary)',loading}){
  return(
    <div>
      <div style={{fontSize:9,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:8}}>{label}</div>
      {loading
        ? <div className="animate-pulse-slow" style={{height:28,width:60,background:'rgba(255,255,255,0.04)',borderRadius:4}}/>
        : <div style={{fontFamily:'"Playfair Display",serif',fontSize:24,color}}>{val}</div>}
    </div>
  )
}

function MiniStat({label,val,color='var(--text-primary)',loading}){
  return(
    <div className="glass" style={{padding:'16px 18px'}}>
      <div style={{fontSize:8,letterSpacing:3,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:8}}>{label}</div>
      {loading
        ? <div className="animate-pulse-slow" style={{height:28,width:60,background:'rgba(255,255,255,0.04)',borderRadius:4}}/>
        : <div style={{fontFamily:'"Playfair Display",serif',fontSize:28,color}}>{val}</div>}
    </div>
  )
}

function PnlCalendar({calMap,loading,isMobile}){
  if(loading)return<div className="glass animate-pulse-slow" style={{height:160,marginBottom:4}}/>
  const today=todayStr()
  const now=new Date()
  const yr=now.getFullYear(),mo=now.getMonth()
  const firstDay=new Date(yr,mo,1).getDay()
  const daysInMonth=new Date(yr,mo+1,0).getDate()
  const MONTHS=['January','February','March','April','May','June','July','August','September','October','November','December']
  const DAYS=['Sun','Mon','Tue','Wed','Thu','Fri','Sat','Wk']
  const rows=[]
  let week=[],weekPnl=0,monthTotal=0
  for(let i=0;i<firstDay;i++)week.push({empty:true})
  for(let d=1;d<=daysInMonth;d++){
    const ds=`${yr}-${String(mo+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`
    const pnl=calMap[ds]??null
    if(pnl!==null){weekPnl+=pnl;monthTotal+=pnl}
    week.push({d,ds,pnl})
    const isWeekEnd=new Date(yr,mo,d).getDay()===6||d===daysInMonth
    if(isWeekEnd){
      while(week.length<7)week.push({empty:true})
      week.push({wk:true,pnl:weekPnl})
      rows.push([...week]);week=[];weekPnl=0
    }
  }
  const cellPad=isMobile?'5px 3px':'8px 6px'
  const dayFontSz=isMobile?9:10
  const pnlFontSz=isMobile?7:8
  const minH=isMobile?38:48
  const hdFontSz=isMobile?7:8
  return(
    <div className="glass" style={{padding:isMobile?'14px 12px':'22px 26px',marginBottom:4,overflowX:'auto'}}>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}}>
        <div style={{fontFamily:'"Playfair Display",serif',fontSize:isMobile?15:18}}>{MONTHS[mo]} {yr}</div>
      </div>
      <div style={{minWidth:isMobile?280:'auto'}}>
        <div style={{display:'grid',gridTemplateColumns:'repeat(8,1fr)',gap:isMobile?2:4,marginBottom:4}}>
          {DAYS.map(d=><div key={d} style={{fontSize:hdFontSz,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',textAlign:'center',padding:'4px 0'}}>{isMobile?d.slice(0,1):d}</div>)}
        </div>
        {rows.map((row,ri)=>(
          <div key={ri} style={{display:'grid',gridTemplateColumns:'repeat(8,1fr)',gap:isMobile?2:4,marginBottom:isMobile?2:4}}>
            {row.map((c,ci)=>{
              if(c.empty)return<div key={ci}/>
              if(c.wk){const wkColor=c.pnl>=0?'var(--green)':'var(--red)';return(
                <div key={ci} style={{padding:cellPad,borderRadius:6,background:'rgba(255,255,255,0.02)',border:'1px solid rgba(255,255,255,0.05)',textAlign:'center',minHeight:minH}}>
                  <div style={{fontSize:pnlFontSz,color:'var(--text-muted)'}}>WK</div>
                  <div style={{fontSize:pnlFontSz,color:wkColor,fontFamily:'"IBM Plex Mono",monospace',marginTop:2}}>{(c.pnl>=0?'+':'-')+'$'+Math.abs(c.pnl).toFixed(0)}</div>
                </div>
              )}
              const isToday=c.ds===today,hasPnl=c.pnl!==null,profit=c.pnl>=0
              return(
                <div key={ci} style={{padding:cellPad,borderRadius:6,
                  background:hasPnl?(profit?'rgba(74,222,128,0.06)':'rgba(248,113,113,0.06)'):'rgba(255,255,255,0.02)',
                  border:isToday?'1px solid rgba(201,168,76,0.5)':hasPnl?(profit?'1px solid rgba(74,222,128,0.2)':'1px solid rgba(248,113,113,0.2)'):'1px solid rgba(255,255,255,0.05)',
                  textAlign:'center',minHeight:minH}}>
                  <div style={{fontSize:dayFontSz,color:isToday?'var(--gold)':'var(--text-muted)',fontWeight:isToday?700:400}}>{c.d}</div>
                  {hasPnl&&<div style={{fontSize:pnlFontSz,color:profit?'var(--green)':'var(--red)',fontFamily:'"IBM Plex Mono",monospace',marginTop:2}}>{(profit?'+':'-')+'$'+Math.abs(c.pnl).toFixed(0)}</div>}
                </div>
              )
            })}
          </div>
        ))}
      </div>
      <div style={{marginTop:10,fontSize:10,color:'var(--text-muted)',textAlign:'right'}}>
        Month total: <span style={{color:monthTotal>=0?'var(--green)':'var(--red)',fontFamily:'"IBM Plex Mono",monospace'}}>{(monthTotal>=0?'+':'-')+'$'+Math.abs(monthTotal).toFixed(2)}</span>
      </div>
    </div>
  )
}

// ── Bot Performance Card ──────────────────────────────────────────────────
function BotCard({ name, color, agentKey, agentPnl, agentTrades, today, loading }) {
  const pnlData   = agentPnl?.[agentKey] ?? {}
  const allTrades = (agentTrades?.trades ?? []).filter(t => t.agent === agentKey)

  const wins    = allTrades.filter(t => parseFloat(t.pnl) > 0).length
  const losses  = allTrades.filter(t => parseFloat(t.pnl) < 0).length
  const todayPnl = allTrades
    .filter(t => (t.date || (t.timestamp||'').split('T')[0]) === today)
    .reduce((s, t) => s + (parseFloat(t.pnl) || 0), 0)

  const totalPnl  = pnlData.pnl ?? 0
  const winRate   = pnlData.wr  ?? 0
  const balance   = pnlData.balance ?? null
  const isActive  = pnlData.sessions > 0

  const recent = [...allTrades]
    .filter(t => parseFloat(t.pnl) !== 0 || t.direction !== 'none')
    .sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''))
    .slice(0, 5)

  const fmtPnl = v => (v >= 0 ? '+' : '') + '$' + Math.abs(v).toFixed(2)
  const fmtSym = s => {
    if (!s) return '—'
    if (s.includes(',')) {
      const first = s.split(',')[0].trim()
      return first.replace('/USDT','').replace('/USD','')
    }
    return s.replace('/USDT','').replace('/USD','')
  }

  return (
    <div className="glass" style={{
      padding: '16px 18px',
      borderTop: `2px solid ${color}`,
      position: 'relative',
    }}>
      {/* Header */}
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:12}}>
        <div style={{display:'flex',alignItems:'center',gap:8}}>
          <span style={{fontFamily:'"Playfair Display",serif',fontSize:16,color,letterSpacing:1}}>{name}</span>
          <span style={{
            width:7, height:7, borderRadius:'50%',
            background: isActive ? '#4ade80' : '#f87171',
            boxShadow: isActive ? '0 0 6px rgba(74,222,128,0.6)' : '0 0 6px rgba(248,113,113,0.4)',
            display:'inline-block', flexShrink:0,
          }}/>
        </div>
        {balance !== null && (
          <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:11,color:'var(--text-dim)'}}>
            {'$' + parseFloat(balance).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
          </span>
        )}
      </div>

      {loading ? (
        <div className="animate-pulse-slow" style={{height:60,background:'rgba(255,255,255,0.04)',borderRadius:4}}/>
      ) : (
        <>
          {/* P&L row */}
          <div style={{display:'flex',gap:20,marginBottom:10,flexWrap:'wrap'}}>
            <div>
              <div style={{fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:3}}>Total P&L</div>
              <div style={{fontFamily:'"Playfair Display",serif',fontSize:18,color:totalPnl>=0?'var(--green)':'var(--red)',lineHeight:1}}>
                {fmtPnl(totalPnl)}
              </div>
            </div>
            <div>
              <div style={{fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:3}}>Today</div>
              <div style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:13,color:todayPnl>=0?'var(--green)':'var(--red)',lineHeight:1}}>
                {todayPnl === 0 ? '—' : fmtPnl(todayPnl)}
              </div>
            </div>
            <div>
              <div style={{fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:3}}>Record</div>
              <div style={{display:'flex',alignItems:'center',gap:4}}>
                <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:12,color:'var(--text-dim)'}}>
                  {wins}-{losses}
                </span>
                <span style={{fontSize:8,padding:'1px 5px',borderRadius:3,
                  background: winRate >= 50 ? 'rgba(74,222,128,0.1)' : 'rgba(248,113,113,0.1)',
                  color: winRate >= 50 ? 'var(--green)' : 'var(--red)',
                  border: `1px solid ${winRate >= 50 ? 'rgba(74,222,128,0.2)' : 'rgba(248,113,113,0.2)'}`,
                  fontFamily:'"IBM Plex Mono",monospace'}}>
                  {winRate.toFixed(0)}%
                </span>
              </div>
            </div>
          </div>

          {/* Recent trades */}
          {recent.length > 0 && (
            <div style={{borderTop:'1px solid rgba(255,255,255,0.06)',paddingTop:8}}>
              <div style={{fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:5}}>Last {recent.length} Trades</div>
              {recent.map((t, i) => {
                const pnl    = parseFloat(t.pnl) || 0
                const dir    = (t.direction || '').toLowerCase()
                const isLong = dir === 'long' || dir === 'buy'
                const isShort= dir === 'short' || dir === 'sell'
                return (
                  <div key={i} style={{
                    display:'grid', gridTemplateColumns:'1fr 44px 56px',
                    alignItems:'center', gap:6,
                    padding:'4px 0',
                    borderBottom: i < recent.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                  }}>
                    <div style={{display:'flex',alignItems:'center',gap:5,minWidth:0}}>
                      <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10,color:'var(--text-dim)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                        {fmtSym(t.symbol)}
                      </span>
                    </div>
                    <span style={{fontSize:8,padding:'1px 4px',borderRadius:3,textAlign:'center',
                      background:isLong?'rgba(74,222,128,0.1)':isShort?'rgba(248,113,113,0.1)':'rgba(255,255,255,0.05)',
                      color:isLong?'var(--green)':isShort?'var(--red)':'var(--text-muted)',
                      border:`1px solid ${isLong?'rgba(74,222,128,0.2)':isShort?'rgba(248,113,113,0.2)':'rgba(255,255,255,0.1)'}`,
                      fontFamily:'"IBM Plex Mono",monospace',whiteSpace:'nowrap'}}>
                      {isLong?'LONG':isShort?'SHORT':'—'}
                    </span>
                    <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10,fontWeight:600,
                      color:pnl>=0?'var(--green)':'var(--red)',textAlign:'right'}}>
                      {(pnl>=0?'+':'-')+'$'+Math.abs(pnl).toFixed(2)}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
          {recent.length === 0 && (
            <div style={{fontSize:10,color:'var(--text-muted)',fontStyle:'italic',paddingTop:4}}>No trades recorded</div>
          )}
        </>
      )}
    </div>
  )
}

// ── Log Trade Modal ───────────────────────────────────────────────────────
function LogTradeModal({onSave, onClose}){
  const today = todayStr()
  const [form, setForm] = useState({
    date: today, source: 'tradelocker', symbol: '', direction: 'long',
    qty: '', entry_price: '', exit_price: '', pnl: '', notes: '',
  })
  const [pnlManual, setPnlManual] = useState(false)
  const set = (k, v) => setForm(f => ({...f, [k]: v}))

  // Auto-calc P&L
  useEffect(() => {
    if (pnlManual) return
    const ep = parseFloat(form.entry_price)
    const xp = parseFloat(form.exit_price)
    const q  = parseFloat(form.qty)
    if (ep && xp && q) {
      const raw = (xp - ep) * q
      const calc = form.direction === 'short' ? -raw : raw
      setForm(f => ({...f, pnl: calc.toFixed(2)}))
    }
  }, [form.entry_price, form.exit_price, form.qty, form.direction, pnlManual])

  const selStyle = {width:'100%',background:'#0d1528',color:'var(--text-primary)',border:'1px solid rgba(255,255,255,0.1)',borderRadius:4,padding:'6px 8px',fontSize:13,outline:'none'}

  return(
    <div className="modal-overlay open" onClick={e=>e.target===e.currentTarget&&onClose()}>
      <div className="modal-box">
        <button onClick={onClose} style={{position:'absolute',top:14,right:16,fontSize:16,background:'none',border:'none',color:'var(--text-muted)',cursor:'pointer'}}>✕</button>
        <h2 className="modal-title text-primary">Log Trade</h2>

        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,marginBottom:10}}>
          <div className="mf">
            <label>Date</label>
            <input type="date" value={form.date} onChange={e=>set('date',e.target.value)}/>
          </div>
          <div className="mf">
            <label>Market</label>
            <select value={form.source} onChange={e=>set('source',e.target.value)} style={selStyle}>
              <option value="tradelocker">TradeLocker</option>
              <option value="phemex">Phemex</option>
              <option value="oanda">OANDA</option>
              <option value="manual">Manual</option>
            </select>
          </div>
          <div className="mf">
            <label>Symbol</label>
            <input type="text" placeholder="BTC/USD, XAU/USD…" value={form.symbol} onChange={e=>set('symbol',e.target.value)}/>
          </div>
          <div className="mf">
            <label>Direction</label>
            <select value={form.direction} onChange={e=>set('direction',e.target.value)} style={selStyle}>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </div>
          <div className="mf">
            <label>Lots / Qty</label>
            <input type="number" step="any" placeholder="0.01" value={form.qty} onChange={e=>set('qty',e.target.value)}/>
          </div>
          <div className="mf">
            <label>Entry Price</label>
            <input type="number" step="any" value={form.entry_price} onChange={e=>set('entry_price',e.target.value)}/>
          </div>
          <div className="mf">
            <label>Exit Price</label>
            <input type="number" step="any" value={form.exit_price} onChange={e=>set('exit_price',e.target.value)}/>
          </div>
          <div className="mf">
            <label>P&L ($)</label>
            <input type="number" step="any" value={form.pnl}
              onChange={e=>{ setPnlManual(true); set('pnl',e.target.value) }}
              onFocus={()=>setPnlManual(true)}/>
          </div>
        </div>
        <div className="mf" style={{marginBottom:14}}>
          <label>Notes (optional)</label>
          <input type="text" placeholder="Any context…" value={form.notes} onChange={e=>set('notes',e.target.value)}/>
        </div>
        <div style={{display:'flex',gap:8,justifyContent:'flex-end'}}>
          <button className="mbtn cancel" onClick={onClose}>Cancel</button>
          <button className="mbtn save" onClick={()=>onSave(form)} disabled={!form.symbol}>Save Trade</button>
        </div>
      </div>
    </div>
  )
}

// ── Add Account Modal ─────────────────────────────────────────────────────
function AddAccountModal({onSave, onClose}){
  const today = todayStr()
  const [form, setForm] = useState({
    name: '', broker: 'Hero FX', balance: '', profit_split: '80%',
    start_date: today, target: '', status: 'Active',
  })
  const set = (k, v) => setForm(f => ({...f, [k]: v}))
  const selStyle = {width:'100%',background:'#0d1528',color:'var(--text-primary)',border:'1px solid rgba(255,255,255,0.1)',borderRadius:4,padding:'6px 8px',fontSize:13,outline:'none'}

  return(
    <div className="modal-overlay open" onClick={e=>e.target===e.currentTarget&&onClose()}>
      <div className="modal-box">
        <button onClick={onClose} style={{position:'absolute',top:14,right:16,fontSize:16,background:'none',border:'none',color:'var(--text-muted)',cursor:'pointer'}}>✕</button>
        <h2 className="modal-title text-primary">Add Account</h2>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,marginBottom:10}}>
          <div className="mf" style={{gridColumn:'1/-1'}}>
            <label>Account Name</label>
            <input type="text" placeholder="Goat Funded Phase 1" value={form.name} onChange={e=>set('name',e.target.value)}/>
          </div>
          <div className="mf">
            <label>Broker</label>
            <select value={form.broker} onChange={e=>set('broker',e.target.value)} style={selStyle}>
              <option>Hero FX</option>
              <option>Goat Funded</option>
              <option>FTMO</option>
              <option>Custom</option>
            </select>
          </div>
          <div className="mf">
            <label>Status</label>
            <select value={form.status} onChange={e=>set('status',e.target.value)} style={selStyle}>
              <option>Active</option>
              <option>Completed</option>
              <option>Failed</option>
            </select>
          </div>
          <div className="mf">
            <label>Balance ($)</label>
            <input type="number" step="any" placeholder="100000" value={form.balance} onChange={e=>set('balance',e.target.value)}/>
          </div>
          <div className="mf">
            <label>Profit Split</label>
            <input type="text" placeholder="80%" value={form.profit_split} onChange={e=>set('profit_split',e.target.value)}/>
          </div>
          <div className="mf">
            <label>Start Date</label>
            <input type="date" value={form.start_date} onChange={e=>set('start_date',e.target.value)}/>
          </div>
          <div className="mf">
            <label>Target ($)</label>
            <input type="number" step="any" placeholder="104000" value={form.target} onChange={e=>set('target',e.target.value)}/>
          </div>
        </div>
        <div style={{display:'flex',gap:8,justifyContent:'flex-end'}}>
          <button className="mbtn cancel" onClick={onClose}>Cancel</button>
          <button className="mbtn save" onClick={()=>onSave(form)} disabled={!form.name}>Add Account</button>
        </div>
      </div>
    </div>
  )
}

// ── Trade Edit Modal ──────────────────────────────────────────────────────
function TradeEditModal({trade,idx,onSave,onClose}){
  const [form,setForm]=useState({entry_price:trade?.open_price||trade?.entry_price||'',exit_price:trade?.close_price||trade?.exit_price||'',qty:trade?.lots||trade?.qty||'',pnl:trade?.pnl||'',side:trade?.side||trade?.direction||''})
  const set=(k,v)=>setForm(f=>({...f,[k]:v}))
  return(
    <div className="modal-overlay open" onClick={e=>e.target===e.currentTarget&&onClose()}>
      <div className="modal-box">
        <button onClick={onClose} style={{position:'absolute',top:14,right:16,fontSize:16,background:'none',border:'none',color:'var(--text-muted)',cursor:'pointer'}}>✕</button>
        <h2 className="modal-title text-primary">Edit Trade #{idx+1}</h2>
        <div style={{fontSize:10,color:'var(--text-muted)',marginBottom:14,fontFamily:'"IBM Plex Mono",monospace'}}>{trade?.symbol} · {fmtShortDate(trade?.close_date||trade?.open_date||trade?.date)}</div>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
          {[['entry_price','Entry Price'],['exit_price','Exit Price'],['qty','Lots'],['pnl','P&L ($)']].map(([k,lbl])=>(
            <div key={k} className="mf"><label>{lbl}</label><input type="number" step="any" value={form[k]} onChange={e=>set(k,e.target.value)}/></div>
          ))}
          <div className="mf"><label>Direction</label>
            <select value={form.side} onChange={e=>set('side',e.target.value)} style={{width:'100%',background:'#0d1528',color:'var(--text-primary)',border:'1px solid rgba(255,255,255,0.1)',borderRadius:4,padding:'6px 8px',fontSize:13}}>
              <option value="">— unchanged —</option>
              <option value="long">Long (Buy)</option>
              <option value="short">Short (Sell)</option>
            </select>
          </div>
        </div>
        <div style={{display:'flex',gap:8,justifyContent:'flex-end',marginTop:18}}>
          <button className="mbtn cancel" onClick={onClose}>Cancel</button>
          <button className="mbtn save" onClick={()=>onSave(idx,form)}>Save Changes</button>
        </div>
      </div>
    </div>
  )
}

function SkeletonTable(){
  return(
    <div className="glass" style={{padding:16}}>
      {[1,2,3,4,5].map(i=><div key={i} className="animate-pulse-slow" style={{height:32,background:'rgba(255,255,255,0.03)',borderRadius:4,marginBottom:4}}/>)}
    </div>
  )
}
