/**
 * Timeline — "Building the Empire" hero + chronological milestone timeline
 * Pre-populated with known events; live hub/trade/bet events appended below.
 * Data: GET /hq/hub?limit=200, GET /hq/data (bets), tradelocker_trades.json
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { getHubMessages, getStoredData, getTradesFile, fmt } from '../api/client.js'

const POLL_MS = 60_000

// Progress along 2024→2037 timeline (14 years)
const TIMELINE_START = new Date('2024-01-01').getTime()
const TIMELINE_END   = new Date('2037-12-31').getTime()
const YEAR_LABELS    = ['2024', '2025', '2026', '2028', '2031', '2037']

function timelineProgress() {
  const now = Date.now()
  return Math.min(100, Math.max(0, ((now - TIMELINE_START) / (TIMELINE_END - TIMELINE_START)) * 100))
}

// Static seed events matching original HTML
const SEED_EVENTS = [
  {
    date: 'Mar 2026',
    category: 'Trading',
    categoryColor: 'var(--cyan)',
    categoryBg: 'rgba(34,211,238,0.1)',
    title: 'JCF HQ Mission Control — Full Gold Sovereign Restyle Complete',
    body: 'All 7 tabs live: Dashboard, Portfolio, Trading, Agents, Sports Betting, Intel, Basketball, Timeline.',
    status: 'In Progress',
    statusColor: 'var(--gold)',
    statusBg: 'rgba(201,168,76,0.1)',
    statusBd: 'rgba(201,168,76,0.2)',
    dot: 'gold',
    cardBorder: 'rgba(201,168,76,0.2)',
    cardBg: 'rgba(201,168,76,0.04)',
  },
  {
    date: 'Mar 2026',
    category: 'Finance',
    categoryColor: 'var(--gold)',
    categoryBg: 'rgba(201,168,76,0.1)',
    title: 'Hero FX — Active',
    body: '$100K account · $354 P&L · 4 trades · 100% win rate · Target: $104K',
    status: 'In Progress',
    statusColor: 'var(--gold)',
    statusBg: 'rgba(201,168,76,0.1)',
    statusBd: 'rgba(201,168,76,0.2)',
    dot: 'gold',
    cardBorder: 'rgba(201,168,76,0.2)',
    cardBg: 'rgba(201,168,76,0.04)',
  },
  {
    date: 'Dec 2025',
    category: 'Trading',
    categoryColor: 'var(--cyan)',
    categoryBg: 'rgba(34,211,238,0.1)',
    title: 'Blade deployed — Forex trading live',
    body: 'GBP/JPY, AUD/CAD, XAU/USD on Twelve Data feed.',
    status: 'Completed',
    statusColor: 'var(--green)',
    statusBg: 'rgba(74,222,128,0.1)',
    statusBd: 'rgba(74,222,128,0.2)',
    dot: 'green',
    cardBorder: 'rgba(74,222,128,0.1)',
    cardBg: 'rgba(74,222,128,0.03)',
  },
  {
    date: '2026 — Goal',
    category: 'Finance Goal',
    categoryColor: 'var(--purple)',
    categoryBg: 'rgba(167,139,250,0.1)',
    title: 'Cross $1,000,000 net worth',
    body: 'Currently at $940.5K — 94% of the way there.',
    status: 'Upcoming',
    statusColor: 'var(--text-muted)',
    statusBg: 'rgba(255,255,255,0.04)',
    statusBd: 'rgba(255,255,255,0.08)',
    dot: 'empty',
    cardBorder: 'rgba(201,168,76,0.25)',
    cardBg: 'rgba(201,168,76,0.05)',
    titleColor: 'var(--gold)',
    titleSize: 15,
  },
  {
    date: '2037 — Ultimate Goal',
    category: 'Ultimate Goal',
    categoryColor: 'var(--purple)',
    categoryBg: 'rgba(167,139,250,0.1)',
    title: '$10,000,000 — Empire Complete',
    body: 'The destination. Everything on this timeline leads here.',
    status: null,
    dot: 'purple',
    cardBorder: 'rgba(201,168,76,0.3)',
    cardBg: 'rgba(201,168,76,0.06)',
    titleFont: '"Playfair Display",serif',
    titleColor: 'var(--gold)',
    titleSize: 20,
  },
]

export default function Timeline({ demoMode, isActive = true }) {
  const [hubEvents, setHubEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [showLive, setShowLive] = useState(false)
  const timer = useRef(null)
  const milestoneCount = SEED_EVENTS.length

  const load = useCallback(async () => {
    try {
      const [msgs] = await Promise.allSettled([getHubMessages(50)])
      if (msgs.status === 'fulfilled') setHubEvents(Array.isArray(msgs.value) ? msgs.value : [])
    } catch (e) { console.error('[Timeline]', e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!isActive) { clearInterval(timer.current); return }
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [isActive, load])

  const progress = timelineProgress()

  return (
    <div>
      <h1 className="page-title">Timeline</h1>

      {/* ── Hero card ────────────────────────────────────────────────── */}
      <div className="glass" style={{ border: '1px solid rgba(201,168,76,0.2)', padding: '26px 30px', marginBottom: 14, position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: -60, right: -60, width: 280, height: 280, background: 'radial-gradient(circle,rgba(201,168,76,0.07) 0%,transparent 70%)', pointerEvents: 'none' }} />

        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 9, letterSpacing: 4, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 5 }}>JCF Master Timeline · 2024 → 2037</div>
            <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 32, fontWeight: 700, color: 'var(--gold)' }}>Building the Empire</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Every milestone, every win, every level-up — logged here.</div>
          </div>
          <div style={{ display: 'flex', gap: 28, textAlign: 'right' }}>
            <div>
              <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 3 }}>Year</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 14, color: 'var(--gold)' }}>{new Date().getFullYear()}</div>
            </div>
            <div>
              <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 3 }}>Milestones</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 14 }}>{milestoneCount}</div>
            </div>
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ height: 5, background: 'rgba(255,255,255,0.04)', borderRadius: 3, overflow: 'hidden', marginBottom: 8 }}>
          <div style={{ height: '100%', width: `${progress}%`, background: 'linear-gradient(90deg,var(--gold),var(--gold-light))', boxShadow: '0 0 8px rgba(201,168,76,0.5)', borderRadius: 3 }} />
        </div>

        {/* Year labels */}
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          {YEAR_LABELS.map(y => {
            const isNow = y === String(new Date().getFullYear())
            return (
              <span key={y} style={{ fontSize: 9, color: isNow ? 'var(--gold)' : 'var(--text-muted)', fontFamily: '"IBM Plex Mono",monospace' }}>
                {isNow ? `${y} ▲` : y}
              </span>
            )
          })}
        </div>
      </div>

      {/* ── Timeline body ─────────────────────────────────────────────── */}
      <div className="glass" style={{ padding: '14px 28px 28px' }}>
        <div style={{ paddingLeft: 20, borderLeft: '1px solid rgba(255,255,255,0.05)', marginLeft: 10 }}>

          {SEED_EVENTS.map((e, i) => (
            <div key={i} style={{ padding: '14px 0', position: 'relative' }}>
              {/* Dot */}
              <span className={`tl-dot ${dotClass(e.dot)}`} />
              {/* Date */}
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>{e.date}</div>
              {/* Card */}
              <div style={{ padding: '14px 16px', borderRadius: 8, border: `1px solid ${e.cardBorder}`, background: e.cardBg }}>
                <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', padding: '2px 6px', borderRadius: 3, background: e.categoryBg, color: e.categoryColor, display: 'inline-block', marginBottom: 5 }}>{e.category}</div>
                <div style={{ fontFamily: e.titleFont || 'inherit', fontSize: e.titleSize || 13, fontWeight: e.titleFont ? 400 : 500, marginBottom: 3, color: e.titleColor || 'var(--text-primary)' }}>{e.title}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{e.body}</div>
                {e.status && (
                  <span style={{ fontSize: 8, padding: '2px 7px', borderRadius: 3, background: e.statusBg, color: e.statusColor, border: `1px solid ${e.statusBd}`, display: 'inline-block', marginTop: 5 }}>{e.status}</span>
                )}
              </div>
            </div>
          ))}

          {/* ── Live hub events (collapsed by default) ─────────────── */}
          <div style={{ padding: '14px 0', position: 'relative' }}>
            <span className="tl-dot tl-dot-empty" />
            <button
              onClick={() => setShowLive(v => !v)}
              style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 6, padding: '6px 14px', cursor: 'pointer' }}
            >
              {showLive ? '▲ Hide' : '▼ Show'} Live Agent Events ({loading ? '…' : hubEvents.length})
            </button>

            {showLive && !loading && hubEvents.map((msg, i) => {
              const color = agentColor(msg.agent)
              return (
                <div key={i} style={{ padding: '10px 0', position: 'relative' }}>
                  <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>{relTime(msg.timestamp)}</div>
                  <div style={{ padding: '10px 14px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <div style={{ width: 20, height: 20, borderRadius: '50%', background: color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: '#0b1226', flexShrink: 0 }}>
                        {(msg.agent || '?').charAt(0).toUpperCase()}
                      </div>
                      <span style={{ fontSize: 11, fontWeight: 600, color }}>{msg.agent || 'Agent'}</span>
                      <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)', border: '1px solid rgba(255,255,255,0.08)' }}>{msg.type || 'log'}</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.45 }}>{msg.message}</div>
                  </div>
                </div>
              )
            })}
          </div>

        </div>
      </div>
    </div>
  )
}

function dotClass(d) {
  if (d === 'gold')   return 'tl-dot-gold'
  if (d === 'green')  return 'tl-dot-green'
  if (d === 'purple') return 'tl-dot-purple'
  return 'tl-dot-empty'
}

function agentColor(n) {
  n = (n || '').toLowerCase()
  if (n.includes('crisp'))  return '#4ade80'
  if (n.includes('blade'))  return '#f87171'
  if (n.includes('lens'))   return '#22d3ee'
  if (n.includes('huncho')) return '#c9a84c'
  return 'rgba(255,255,255,0.3)'
}

function relTime(ts) {
  if (!ts) return ''
  try {
    const d = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
    if (d < 60)    return `${d}s ago`
    if (d < 3600)  return `${Math.floor(d / 60)}m ago`
    if (d < 86400) return `${Math.floor(d / 3600)}h ago`
    const dt = new Date(ts)
    const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return `${mo[dt.getUTCMonth()]} ${String(dt.getUTCDate()).padStart(2,'0')} ${String(dt.getUTCHours()).padStart(2,'0')}:${String(dt.getUTCMinutes()).padStart(2,'0')} UTC`
  } catch { return '' }
}
