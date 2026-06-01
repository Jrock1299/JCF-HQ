/**
 * Agents — 14 agent cards grouped by category + chat-style Agent Hub
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { getHubMessages, getHubStats, postHubCollab } from '../api/client.js'
import { useIsMobile } from '../hooks/useIsMobile.js'

const POLL_MS = 30_000

const STATUS_CFG = {
  ACTIVE:    { label: 'ACTIVE',    bg: 'rgba(74,222,128,0.12)',  bd: 'rgba(74,222,128,0.35)',  col: '#4ade80' },
  PAPER:     { label: 'PAPER',     bg: 'rgba(250,204,21,0.12)',  bd: 'rgba(250,204,21,0.35)',  col: '#facc15' },
  IDLE:      { label: 'IDLE',      bg: 'rgba(255,255,255,0.06)', bd: 'rgba(255,255,255,0.15)', col: 'rgba(255,255,255,0.4)' },
  SUSPENDED: { label: 'SUSPENDED', bg: 'rgba(248,113,113,0.12)', bd: 'rgba(248,113,113,0.35)', col: '#f87171' },
}

// ── 14 agents grouped by category ───────────────────────────────────────────
const CATEGORIES = [
  {
    key: 'trading',
    label: 'Trading',
    agents: [
      {
        id: 'blade', name: 'Blade', title: 'Forex Agent', color: '#f87171',
        border: 'rgba(248,113,113,0.2)', img: '/agents/blade.png',
        model: 'Codex', brain: null, status: 'PAPER',
        desc: 'Executes forex trades on OANDA paper account. Risk-based position sizing split across 3 positions.',
        statsType: 'trading',
      },
      {
        id: 'crisp', name: 'Crisp', title: 'Crypto Agent', color: '#4ade80',
        border: 'rgba(74,222,128,0.2)', img: '/agents/crisp.png',
        model: 'Codex', brain: null, status: 'PAPER',
        desc: 'Monitors crypto markets on Binance testnet. Scans news and feeds alpha to the hub.',
        statsType: 'trading',
      },
      {
        id: 'jerry', name: 'Jerry', title: 'Stocks & Options', color: '#fb923c',
        border: 'rgba(251,146,60,0.25)', img: '/agents/jerry.png',
        model: 'Codex + Claude', brain: 'claude-sonnet-4-6', status: 'PAPER',
        desc: 'Trades US equities and options on Alpaca paper. Claude brain discovers and reviews strategies with a $25K safety floor.',
        statsType: 'jerry',
      },
      {
        id: 'phantom', name: 'Phantom', title: 'Crypto Futures', color: '#818cf8',
        border: 'rgba(129,140,248,0.25)', img: '/agents/phantom.png',
        model: 'Codex + Claude', brain: 'claude-sonnet-4-6', status: 'PAPER',
        desc: 'Self-evolving crypto futures trader on Phemex. Claude brain discovers, backtests, and evolves strategies.',
        statsType: 'phantom',
      },
    ],
  },
  {
    key: 'intelligence',
    label: 'Intelligence',
    agents: [
      {
        id: 'lens', name: 'Lens', title: 'Macro Analyst', color: '#22d3ee',
        border: 'rgba(34,211,238,0.2)', img: '/agents/lens.png',
        model: 'Codex', brain: null, status: 'ACTIVE',
        desc: 'Reads price action, HTF bias, and forex structure. Publishes macro context to the hub.',
        statsType: 'intelligence',
      },
      {
        id: 'strategist', name: 'Strategist', title: 'Regime Analyst', color: '#c9a84c',
        border: 'rgba(201,168,76,0.2)', img: '/agents/strategist.png',
        model: 'Codex', brain: null, status: 'IDLE',
        desc: 'Identifies market regime and session context. Provides directional bias and trade framework.',
        statsType: 'intelligence',
      },
      {
        id: 'norman', name: 'Norman', title: 'Strategy Validator', color: '#34d399',
        border: 'rgba(52,211,153,0.25)', img: '/agents/norman.png',
        model: 'Claude', brain: 'claude-sonnet-4-6', status: 'ACTIVE',
        desc: 'Monte Carlo validation engine. Stress-tests every trading agent and issues PASS/FAIL verdicts with structural critiques.',
        statsType: 'intelligence',
      },
    ],
  },
  {
    key: 'business',
    label: 'Business',
    agents: [
      {
        id: 'forge', name: 'Forge', title: 'Product Builder', color: '#fbbf24',
        border: 'rgba(251,191,36,0.25)', img: '/agents/forge.png',
        model: 'Claude', brain: 'claude-sonnet-4-6', status: 'ACTIVE',
        desc: 'Builds sellable digital products from Lucy\u2019s niche research. Generates HTML/sheets templates, self-reviews, and iterates.',
        statsType: 'forge',
      },
      {
        id: 'lucy', name: 'Lucy', title: 'Niche Research', color: '#c9a84c',
        border: 'rgba(201,168,76,0.25)', img: '/agents/lucy.png',
        model: 'Claude', brain: 'claude-sonnet-4-6', status: 'ACTIVE',
        desc: 'Scouts high-opportunity Etsy niches. Scores each idea on demand, competition, and buyer profile.',
        statsType: 'lucy',
      },
      {
        id: 'victoria', name: 'Victoria', title: 'News Analyst', color: '#f9a8d4',
        border: 'rgba(249,168,212,0.25)', img: '/agents/victoria.png',
        model: 'Claude', brain: 'claude-sonnet-4-6', status: 'ACTIVE',
        desc: 'Reads financial news, earnings, and sector catalysts. Publishes daily market briefings from Sentinel data.',
        statsType: 'intelligence',
      },
    ],
  },
  {
    key: 'infrastructure',
    label: 'Infrastructure',
    agents: [
      {
        id: 'huncho', name: 'Huncho', title: 'Chief of Staff', color: '#c9a84c',
        border: 'rgba(201,168,76,0.3)', img: '/agents/huncho.png',
        model: 'Codex / Gemini 3.1 Pro', brain: null, status: 'ACTIVE', isHero: true,
        desc: 'Orchestrates all agents, runs the morning brief, and manages the daily playbook.',
        statsType: 'huncho',
      },
      {
        id: 'tao', name: 'Tao', title: 'Staking Agent', color: '#c9a84c',
        border: 'rgba(201,168,76,0.2)', img: '/agents/tao.png',
        model: 'Codex', brain: null, status: 'ACTIVE',
        desc: 'Manages Bittensor TAO staking positions across root and subnet validators.',
        statsType: 'tao',
      },
    ],
  },
]

// Flat list for lookups
const AGENTS = CATEGORIES.flatMap(c => c.agents)

const HUB_FILTERS = [
  { key: 'all', label: 'All' }, { key: 'error', label: 'Errors' },
  { key: 'status', label: 'Status' }, { key: 'idea', label: 'Ideas' },
  { key: 'report', label: 'Reports' }, { key: 'collab', label: 'Collab' },
]

// Normalize versioned agent names: crisp_v5 → crisp, blade_v4 → blade
function normalizeAgentId(raw) {
  return (raw || '').toLowerCase().replace(/_v\d+$/i, '').replace(/-v\d+$/i, '')
}

function agentById(n) {
  return AGENTS.find(a => a.id === normalizeAgentId(n))
}

function agentDisplayName(raw) {
  const agent = agentById(raw)
  if (agent) return agent.name
  const id = normalizeAgentId(raw)
  if (id === 'jase') return 'Jase'
  if (!raw) return 'Agent'
  return raw.charAt(0).toUpperCase() + raw.slice(1)
}

function agentColor(n) {
  const a = agentById(n)
  if (a) return a.color
  if (normalizeAgentId(n) === 'jase') return '#c9a84c'
  return 'rgba(255,255,255,0.3)'
}

function agentImg(n) {
  const a = agentById(n)
  return a ? a.img : null
}

function typeBadge(t) {
  t = (t || '').toLowerCase()
  if (t === 'collab')   return { bg: 'rgba(167,139,250,0.15)', bd: 'rgba(167,139,250,0.4)',  col: 'var(--purple)' }
  if (t === 'question') return { bg: 'rgba(201,168,76,0.15)',  bd: 'rgba(201,168,76,0.4)',   col: 'var(--gold)' }
  if (t === 'error')    return { bg: 'rgba(248,113,113,0.15)', bd: 'rgba(248,113,113,0.35)', col: 'var(--red)' }
  if (t === 'idea')     return { bg: 'rgba(201,168,76,0.15)',  bd: 'rgba(201,168,76,0.35)',  col: 'var(--gold)' }
  if (t === 'status')   return { bg: 'rgba(34,211,238,0.15)',  bd: 'rgba(34,211,238,0.35)',  col: 'var(--cyan)' }
  if (t === 'report')   return { bg: 'rgba(96,165,250,0.15)',  bd: 'rgba(96,165,250,0.35)',  col: 'var(--blue)' }
  if (t === 'trade')    return { bg: 'rgba(74,222,128,0.15)',  bd: 'rgba(74,222,128,0.35)',  col: 'var(--green)' }
  return { bg: 'rgba(255,255,255,0.06)', bd: 'rgba(255,255,255,0.12)', col: 'var(--text-muted)' }
}

function relTime(ts) {
  if (!ts) return ''
  try {
    const d = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
    if (d < 60)    return d + 's ago'
    if (d < 3600)  return Math.floor(d / 60) + 'm ago'
    if (d < 86400) return Math.floor(d / 3600) + 'h ago'
    const dt = new Date(ts)
    const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return `${mo[dt.getUTCMonth()]} ${String(dt.getUTCDate()).padStart(2,'0')} ${String(dt.getUTCHours()).padStart(2,'0')}:${String(dt.getUTCMinutes()).padStart(2,'0')} UTC`
  } catch { return '' }
}

// ── Main component ──────────────────────────────────────────────────────────

export default function Agents({ demoMode, isActive = true }) {
  const isMobile = useIsMobile()
  const [messages,      setMessages]      = useState([])
  const [stats,         setStats]         = useState(null)
  const [loading,       setLoading]       = useState(true)
  const [filter,        setFilter]        = useState('all')
  const [collabQ,       setCollabQ]       = useState('')
  const [collabSending, setCollabSending] = useState(false)
  const [collabStatus,  setCollabStatus]  = useState('')
  const [extra,         setExtra]         = useState({})
  const chatEndRef = useRef(null)
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const [msgs, s, jerry, phantom, forge, lucy] = await Promise.allSettled([
        getHubMessages(50),
        getHubStats(),
        fetch('/hq/jerry-portfolio').then(r => r.ok ? r.json() : null),
        fetch('/hq/phantom-portfolio').then(r => r.ok ? r.json() : null),
        fetch('/hq/forge-builds').then(r => r.ok ? r.json() : null),
        fetch('/hq/lucy-research').then(r => r.ok ? r.json() : null),
      ])
      if (msgs.status === 'fulfilled') setMessages(Array.isArray(msgs.value) ? msgs.value : [])
      if (s.status    === 'fulfilled') setStats(s.value)
      setExtra({
        jerry:   jerry.status   === 'fulfilled' ? jerry.value   : null,
        phantom: phantom.status === 'fulfilled' ? phantom.value : null,
        forge:   forge.status   === 'fulfilled' ? forge.value   : null,
        lucy:    lucy.status    === 'fulfilled' ? lucy.value    : null,
      })
    } catch (e) { console.error('[Agents]', e) } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!isActive) { clearInterval(timer.current); return }
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [isActive, load])

  const handleCollab = useCallback(async () => {
    const q = collabQ.trim()
    if (!q || collabSending) return
    setCollabSending(true); setCollabStatus('')
    try {
      await postHubCollab(q)
      setCollabQ('')
      setCollabStatus('Question posted — response will appear in the hub (30–60s).')
      await load()
    } catch (e) { setCollabStatus('Error: ' + e.message) }
    finally { setCollabSending(false) }
  }, [collabQ, collabSending, load])

  const filtered = filter === 'all' ? messages
    : filter === 'collab' ? messages.filter(m => ['collab','question'].includes((m.type||'').toLowerCase()))
    : messages.filter(m => (m.type||'').toLowerCase() === filter)

  const huncho = AGENTS.find(a => a.id === 'huncho')

  return (
    <div>
      <h1 className="page-title">Agent Command Center</h1>

      {/* Huncho — full-width hero at top */}
      <AgentCard agent={huncho} messages={messages} isMobile={isMobile} extra={extra} isHero />

      {/* Category sections */}
      {CATEGORIES.map(cat => {
        const items = cat.agents.filter(a => a.id !== 'huncho')
        if (!items.length) return null
        return (
          <div key={cat.key} style={{ marginTop: 18 }}>
            <div className="section-head">
              <div className="section-line" />
              <h3>{cat.label}</h3>
              <div className="section-line" />
              <span className="pill pill-gray ml-2 shrink-0">{items.length}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 12, marginBottom: 4 }}>
              {items.map(a => (
                <AgentCard key={a.id} agent={a} messages={messages} isMobile={isMobile} extra={extra} />
              ))}
            </div>
          </div>
        )
      })}

      {/* Agent Hub — chat interface */}
      <div className="section-head" style={{ marginTop: 22 }}>
        <div className="section-line" /><h3>Agent Hub</h3><div className="section-line" />
        {stats && <span className="pill pill-gray ml-2 shrink-0">{stats.total_messages ?? messages.length} msgs</span>}
      </div>

      <div className="glass" style={{ overflow: 'hidden' }}>
        {/* Filter pills */}
        <div style={{ display: 'flex', gap: 6, padding: '12px 16px 10px', borderBottom: '1px solid rgba(255,255,255,0.05)', flexWrap: 'wrap' }}>
          {HUB_FILTERS.map(f => (
            <button key={f.key} onClick={() => setFilter(f.key)}
              style={{ padding: '4px 12px', borderRadius: 6, cursor: 'pointer', fontSize: 11, fontWeight: 500,
                background: filter === f.key ? 'rgba(201,168,76,0.1)' : 'rgba(255,255,255,0.02)',
                color: filter === f.key ? 'var(--gold)' : 'var(--text-muted)',
                border: filter === f.key ? '1px solid rgba(201,168,76,0.25)' : '1px solid rgba(255,255,255,0.07)',
                transition: 'all .15s' }}>
              {f.label}
            </button>
          ))}
        </div>

        {/* Chat messages */}
        <div style={{ maxHeight: 480, overflowY: 'auto', padding: '12px 16px' }}>
          {loading ? (
            <div>{[1,2,3].map(i => (
              <div key={i} style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
                <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'rgba(255,255,255,0.06)', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div className="animate-pulse-slow" style={{ height: 9, width: '25%', background: 'rgba(255,255,255,0.04)', borderRadius: 4, marginBottom: 6 }} />
                  <div className="animate-pulse-slow" style={{ height: 44, background: 'rgba(255,255,255,0.04)', borderRadius: 8 }} />
                </div>
              </div>
            ))}</div>
          ) : !filtered.length ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', padding: '20px 0' }}>No messages.</div>
          ) : (
            <ChatMessages messages={filtered} />
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Chat input bar */}
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '10px 14px', background: 'rgba(0,0,0,0.1)' }}>
          {collabStatus && (
            <div style={{ marginBottom: 6, fontSize: 10, color: collabStatus.startsWith('Error') ? 'var(--red)' : 'var(--text-muted)', fontStyle: 'italic' }}>
              {collabStatus}
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <input type="text" placeholder="Ask your agents..."
              value={collabQ}
              onChange={e => setCollabQ(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCollab()}
              style={{ flex: 1, padding: '9px 14px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: 'var(--text-primary)', fontSize: 13, outline: 'none', fontFamily: 'inherit', transition: 'border .15s' }}
              onFocus={e => e.target.style.borderColor = 'rgba(167,139,250,0.4)'}
              onBlur={e => e.target.style.borderColor = 'rgba(255,255,255,0.1)'}
            />
            <button onClick={handleCollab} disabled={collabSending || !collabQ.trim()}
              style={{ padding: '9px 18px', borderRadius: 8, cursor: 'pointer', fontSize: 12, fontWeight: 600, background: 'rgba(167,139,250,0.12)', color: 'var(--purple)', border: '1px solid rgba(167,139,250,0.3)', opacity: (!collabQ.trim() || collabSending) ? 0.45 : 1, transition: 'all .15s', whiteSpace: 'nowrap' }}>
              {collabSending ? 'Asking…' : 'Send'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── ChatMessages ─────────────────────────────────────────────────────────────

function ChatMessages({ messages }) {
  const groups = []
  messages.forEach((msg, i) => {
    const prev = i > 0 ? messages[i - 1] : null
    const sameAgent = prev && normalizeAgentId(prev.agent) === normalizeAgentId(msg.agent)
    if (sameAgent) {
      groups[groups.length - 1].msgs.push(msg)
    } else {
      groups.push({ agent: msg.agent, msgs: [msg] })
    }
  })

  return (
    <div>
      {groups.map((group, gi) => {
        const color       = agentColor(group.agent)
        const img         = agentImg(group.agent)
        const displayName = agentDisplayName(group.agent)
        const letter      = displayName.charAt(0).toUpperCase()
        return (
          <div key={gi} style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'flex-start' }}>
            <div style={{ width: 32, height: 32, borderRadius: '50%', overflow: 'hidden', background: img ? '#080e1e' : color, border: `1px solid ${color}40`, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#0b1226', fontSize: 12, fontWeight: 700 }}>
              {img
                ? <img src={img} alt={displayName} style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top' }} onError={e => { e.target.style.display = 'none'; e.target.parentElement.innerText = letter }} />
                : letter
              }
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color, marginBottom: 4, display: 'block' }}>{displayName}</span>
              {group.msgs.map((msg, mi) => {
                const badge = typeBadge(msg.type)
                return (
                  <div key={mi} style={{ marginBottom: mi < group.msgs.length - 1 ? 6 : 0 }}>
                    <div style={{ display: 'inline-flex', gap: 6, alignItems: 'center', marginBottom: 3, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, border: `1px solid ${badge.bd}`, background: badge.bg, color: badge.col, textTransform: 'uppercase', letterSpacing: 1 }}>{msg.type || 'log'}</span>
                    </div>
                    <div style={{ background: 'rgba(255,255,255,0.04)', border: `1px solid ${color}20`, borderRadius: '0 10px 10px 10px', padding: '8px 12px', fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5, wordBreak: 'break-word', display: 'block' }}>
                      {msg.message}
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2, marginLeft: 4 }}>{relTime(msg.timestamp)}</div>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── StatusBadge + BrainBadge ─────────────────────────────────────────────────

function StatusBadge({ status }) {
  const s = STATUS_CFG[status] || STATUS_CFG.IDLE
  return (
    <span style={{ fontSize: 8, padding: '2px 7px', borderRadius: 20, background: s.bg, color: s.col, border: `1px solid ${s.bd}`, letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700 }}>
      {s.label}
    </span>
  )
}

function BrainBadge({ brain }) {
  if (!brain) return null
  return (
    <span style={{
      fontSize: 8, padding: '2px 7px', borderRadius: 20,
      background: 'rgba(167,139,250,0.14)', color: '#c4b5fd',
      border: '1px solid rgba(167,139,250,0.4)',
      letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700,
      display: 'inline-flex', alignItems: 'center', gap: 3,
    }}>
      <span style={{ fontSize: 9, lineHeight: 1 }}>✦</span>
      Claude Brain
    </span>
  )
}

// ── AgentCard ────────────────────────────────────────────────────────────────

function fmtDol(v) {
  return '$' + parseFloat(v || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtSign(n) {
  const v = parseFloat(n || 0)
  return (v >= 0 ? '+' : '-') + '$' + Math.abs(v).toFixed(2)
}

function AgentCard({ agent, messages, isMobile, extra = {}, isHero = false }) {
  const [showFull, setShowFull] = useState(false)
  const lastMsg       = messages.find(m => normalizeAgentId(m.agent) === agent.id)
  const isActiveAgent = lastMsg && (Date.now() - new Date(lastMsg.timestamp).getTime()) < 10 * 60_000
  const imgW          = isHero ? 140 : 110
  const CARD_MIN_H    = isHero ? 160 : 200

  const activeDot = isActiveAgent ? (
    <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#4ade80', boxShadow: '0 0 6px rgba(74,222,128,0.8)', display: 'inline-block', marginLeft: 6, verticalAlign: 'middle' }} />
  ) : null

  const lastActive = lastMsg ? relTime(lastMsg.timestamp) : '—'

  let statsContent = null
  if (agent.statsType === 'huncho') {
    statsContent = (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginTop: 10 }}>
        {[{ label: 'Uptime', val: '99.8%' }, { label: 'Tasks Today', val: '—' }, { label: 'Last Active', val: lastActive }, { label: 'Model', val: 'Codex' }].map(s => (
          <StatCell key={s.label} label={s.label} val={s.val} color="var(--gold)" />
        ))}
      </div>
    )
  } else if (agent.statsType === 'trading') {
    statsContent = (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: 10 }}>
        {[{ label: "Today's P&L", val: '—' }, { label: 'Total P&L', val: '—' }, { label: 'Last Active', val: lastActive }].map(s => (
          <StatCell key={s.label} label={s.label} val={s.val} color={agent.color} />
        ))}
      </div>
    )
  } else if (agent.statsType === 'jerry') {
    const j = extra.jerry || {}
    statsContent = (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: 10 }}>
        <StatCell label="Balance"     val={j.balance != null ? fmtDol(j.balance) : '—'} color={agent.color} />
        <StatCell label="Total P&L"   val={j.total_pnl != null ? fmtSign(j.total_pnl) : '—'} color={j.total_pnl >= 0 ? 'var(--green)' : 'var(--red)'} />
        <StatCell label="Positions"   val={j.open_positions ? String(j.open_positions.length) : '—'} color={agent.color} />
      </div>
    )
  } else if (agent.statsType === 'phantom') {
    const p = extra.phantom || {}
    statsContent = (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: 10 }}>
        <StatCell label="Balance"   val={p.balance != null ? fmtDol(p.balance) : '—'} color={agent.color} />
        <StatCell label="Total P&L" val={p.total_pnl != null ? fmtSign(p.total_pnl) : '—'} color={p.total_pnl >= 0 ? 'var(--green)' : 'var(--red)'} />
        <StatCell label="Positions" val={p.open_positions ? String(p.open_positions.length) : '—'} color={agent.color} />
      </div>
    )
  } else if (agent.statsType === 'intelligence') {
    statsContent = (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: 10 }}>
        {[{ label: 'Last Active', val: lastActive }, { label: 'Reports', val: '—' }, { label: 'Status', val: agent.status }].map(s => (
          <StatCell key={s.label} label={s.label} val={s.val} color={agent.color} />
        ))}
      </div>
    )
  } else if (agent.statsType === 'forge') {
    const f = extra.forge || {}
    const builds = f.builds || []
    const specs  = f.specs  || []
    const approved = builds.filter(b => (b.review_status || '').toUpperCase() === 'APPROVED').length
    statsContent = (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: 10 }}>
        <StatCell label="Builds"    val={String(builds.length)}   color={agent.color} />
        <StatCell label="Approved"  val={String(approved)}         color="var(--green)" />
        <StatCell label="Pipeline"  val={String(specs.length)}     color={agent.color} />
      </div>
    )
  } else if (agent.statsType === 'lucy') {
    const l = extra.lucy || {}
    const niches = l.niches || []
    statsContent = (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: 10 }}>
        <StatCell label="Niches"     val={String(niches.length)}             color={agent.color} />
        <StatCell label="Last Research" val={l.research_date || '—'}         color={agent.color} />
        <StatCell label="Last Active"   val={lastActive}                      color={agent.color} />
      </div>
    )
  } else if (agent.statsType === 'tao') {
    statsContent = (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: 10 }}>
        {[{ label: 'Staked TAO', val: '—' }, { label: 'Total Value', val: '—' }, { label: 'Return %', val: '—' }].map(s => (
          <StatCell key={s.label} label={s.label} val={s.val} color="var(--gold)" />
        ))}
      </div>
    )
  }

  if (isMobile) {
    return (
      <div className="glass" style={{ border: `1px solid ${agent.border}`, padding: '14px 16px', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
          <div style={{ width: 44, height: 44, borderRadius: '50%', overflow: 'hidden', background: '#080e1e', border: `1px solid ${agent.border}`, flexShrink: 0 }}>
            <img src={agent.img} alt={agent.name} style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top' }} onError={e => e.target.style.display = 'none'} />
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', gap: 6, marginBottom: 4, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 8, padding: '2px 7px', borderRadius: 20, background: `${agent.color}18`, color: agent.color, border: `1px solid ${agent.color}40`, letterSpacing: 1.5, textTransform: 'uppercase' }}>{agent.title}</span>
              <StatusBadge status={agent.status} />
              <BrainBadge brain={agent.brain} />
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: agent.color }}>{agent.name}{activeDot}</div>
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{agent.desc}</div>
        {statsContent}
        {lastMsg && (
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ fontSize: 10, color: 'var(--text-dim)', fontStyle: 'italic', wordBreak: 'break-word', display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: showFull ? 'unset' : 3, overflow: showFull ? 'visible' : 'hidden' }}>"{lastMsg.message}"</div>
            {lastMsg.message?.length > 120 && <button onClick={() => setShowFull(v => !v)} style={{ marginTop: 3, fontSize: 9, color: 'var(--gold)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>{showFull ? 'Show less ▴' : 'Show more ▾'}</button>}
          </div>
        )}
      </div>
    )
  }

  const imgObjPos = agent.id === 'strategist' ? 'center top' : 'top'

  return (
    <div className="glass" style={{ border: `1px solid ${agent.border}`, display: 'grid', gridTemplateColumns: `${imgW}px 1fr`, overflow: 'hidden', marginBottom: 12, minHeight: CARD_MIN_H }}>
      <div style={{ position: 'relative', background: '#080e1e', overflow: 'hidden', minHeight: CARD_MIN_H }}>
        <img src={agent.img} alt={agent.name}
          style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: imgObjPos, display: 'block' }}
          onError={e => e.target.style.display = 'none'}
        />
        <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(90deg,transparent 60%,rgba(7,12,26,0.98) 100%)' }} />
      </div>
      <div style={{ padding: isHero ? '18px 22px' : '14px 18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 8, padding: '2px 8px', borderRadius: 20, background: `${agent.color}18`, color: agent.color, border: `1px solid ${agent.color}40`, letterSpacing: 2, textTransform: 'uppercase' }}>{agent.title}</span>
          <StatusBadge status={agent.status} />
          <BrainBadge brain={agent.brain} />
        </div>
        <div style={{ fontFamily: '"Playfair Display",serif', fontSize: isHero ? 22 : 18, color: 'var(--text-primary)', marginBottom: 2 }}>
          {agent.name}{activeDot}
        </div>
        {agent.model && (
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 8, fontFamily: '"IBM Plex Mono",monospace', letterSpacing: 0.5 }}>{agent.model}</div>
        )}
        <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{agent.desc}</div>
        {statsContent}
        {lastMsg && (
          <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{
              fontSize: 10, color: 'var(--text-dim)', fontStyle: 'italic', wordBreak: 'break-word',
              display: '-webkit-box', WebkitBoxOrient: 'vertical',
              WebkitLineClamp: showFull ? 'unset' : 3,
              overflow: showFull ? 'visible' : 'hidden',
            }}>
              "{lastMsg.message}"
            </div>
            {lastMsg.message?.length > 120 && (
              <button onClick={() => setShowFull(v => !v)} style={{ marginTop: 4, fontSize: 9, color: 'var(--gold)', background: 'none', border: 'none', cursor: 'pointer', padding: 0, letterSpacing: 0.5 }}>
                {showFull ? 'Show less ▴' : 'Show more ▾'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function StatCell({ label, val, color }) {
  return (
    <div>
      <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>
      <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color }}>{val}</div>
    </div>
  )
}
