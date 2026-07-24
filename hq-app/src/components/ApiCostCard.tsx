import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { AreaChart, Area, ResponsiveContainer, Tooltip, XAxis, ReferenceDot } from 'recharts'
import GlassCard from './GlassCard'
import AgentAvatar from './AgentAvatar'
import EditableValue from './EditableValue'
import { useHQData, fmtUSD, timeAgo } from '../hooks/useHQData'
import { AGENT_MAP } from '../data/agentConfig'

// ── Types matching dashboard/api_costs.json (scripts/sync_api_costs.py) ──
interface CostAgent {
  id: string
  billing: 'metered' | 'codex' | 'none'
  month_usd: number
  prev_month_usd: number
  total_usd: number
  last_activity: string | null
  has_log: boolean
  note: string | null
}
interface CostFeed {
  updated: string
  month: string
  ceiling_usd: number
  month_total_usd: number
  prev_month_total_usd: number
  daily: { date: string; usd: number }[]
  agents: CostAgent[]
}

// Gold family for real-spend donut segments — stepped hard enough that
// adjacent arcs actually separate at a glance (bright → deep bronze).
const GOLD_SEQ = ['#f0c060', '#a87b2e', '#7d5c22', '#5f461c']

const fmtCost = (n: number): string =>
  n === 0 ? '$0' : n >= 100 ? fmtUSD(n, 0) : fmtUSD(n, 2)

// ── Donut geometry ───────────────────────────────────────────────────────
const D_SIZE = 216
const D_CX = D_SIZE / 2
const D_R = 84 // outer ring radius
const D_W = 21 // outer ring stroke width
const D_RI = D_R - 30 // muted companion ring radius

function arcPath(r: number, startDeg: number, endDeg: number): string {
  const a0 = ((startDeg - 90) * Math.PI) / 180
  const a1 = ((endDeg - 90) * Math.PI) / 180
  const large = endDeg - startDeg > 180 ? 1 : 0
  return `M ${D_CX + r * Math.cos(a0)} ${D_CX + r * Math.sin(a0)} A ${r} ${r} 0 ${large} 1 ${
    D_CX + r * Math.cos(a1)
  } ${D_CX + r * Math.sin(a1)}`
}

interface Segment {
  id: string
  name: string
  usd: number
  share: number
  color: string
  start: number
  end: number
}

export default function ApiCostCard() {
  const { data, loading, error } = useHQData<CostFeed>('api-costs')

  const ceiling = data?.ceiling_usd ?? 50
  const total = data?.month_total_usd ?? 0
  const pctOfCeiling = ceiling > 0 ? (total / ceiling) * 100 : 0
  const warn = pctOfCeiling >= 100 ? 'over' : pctOfCeiling >= 70 ? 'near' : null

  // Donut segments: agents with real dollars this month, largest first.
  const segments: Segment[] = useMemo(() => {
    const spenders = (data?.agents ?? [])
      .filter((a) => a.month_usd > 0.005)
      .sort((a, b) => b.month_usd - a.month_usd)
    const sum = spenders.reduce((s, a) => s + a.month_usd, 0)
    if (sum <= 0) return []
    const gap = spenders.length > 1 ? 5 : 0 // degrees between arcs
    const avail = 360 - gap * spenders.length
    let cursor = 0
    return spenders.map((a, i) => {
      const sweep = (a.month_usd / sum) * avail
      const seg: Segment = {
        id: a.id,
        name: AGENT_MAP[a.id]?.name ?? a.id,
        usd: a.month_usd,
        share: (a.month_usd / sum) * 100,
        color: GOLD_SEQ[Math.min(i, GOLD_SEQ.length - 1)],
        start: cursor,
        end: cursor + sweep,
      }
      cursor += sweep + gap
      return seg
    })
  }, [data])

  const coveredCount = (data?.agents ?? []).filter((a) => a.billing === 'codex').length

  // Fleet list: metered → codex → no-AI, spend descending inside each group.
  const fleet = useMemo(() => {
    const rank = { metered: 0, codex: 1, none: 2 }
    return [...(data?.agents ?? [])]
      .filter((a) => AGENT_MAP[a.id])
      .sort((a, b) => rank[a.billing] - rank[b.billing] || b.month_usd - a.month_usd || a.id.localeCompare(b.id))
  }, [data])

  // Spend delta vs previous month (spend going DOWN is the good direction).
  const prevTotal = data?.prev_month_total_usd ?? 0
  const delta = prevTotal > 0 ? ((total - prevTotal) / prevTotal) * 100 : null

  const spark = useMemo(
    () =>
      (data?.daily ?? []).map((d) => ({
        d: d.date.slice(5).replace('-', '/'),
        usd: d.usd,
      })),
    [data],
  )

  const stale = data ? Date.now() - new Date(data.updated).getTime() > 26 * 3600_000 : false

  const barColor =
    warn === 'over'
      ? 'linear-gradient(90deg,#ef4444,#f2645f)'
      : warn === 'near'
        ? 'linear-gradient(90deg,#f59e0b,#f0a232)'
        : 'linear-gradient(90deg,#d4a843,#f0c060)'

  return (
    <GlassCard
      hover={false}
      style={{
        padding: 24,
        ...(warn === 'over'
          ? { border: '1px solid rgba(239,68,68,0.45)', boxShadow: 'var(--card-shadow), 0 0 24px rgba(239,68,68,0.14)' }
          : warn === 'near'
            ? { border: '1px solid rgba(245,158,11,0.40)' }
            : {}),
      }}
    >
      {/* header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
        <span className="mono-label">api usage · cost</span>
        <span className="mono-meta" style={stale ? { color: 'var(--amber)' } : undefined}>
          {data ? `synced ${timeAgo(data.updated)}${stale ? ' · stale' : ''}` : loading ? 'syncing…' : 'feed offline'}
        </span>
      </div>

      {!data && !loading ? (
        <div style={{ padding: '28px 4px', color: 'var(--text-dim)', fontSize: 13 }}>
          Cost feed offline — <span className="mono">api_costs.json</span> is missing or unreadable.
          <div className="mono-meta" style={{ marginTop: 6 }}>run scripts/sync_api_costs.py on the VPS to populate it</div>
        </div>
      ) : (
        <div className="cost-grid">
          {/* ── numbers ── */}
          <div>
            <div className="mono-meta" style={{ marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
              {monthName(data?.month)} spend
            </div>
            <div className="hero-num gold-text" style={{ fontSize: 40 }}>{fmtCost(total)}</div>
            <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 6 }}>
              {delta == null ? (
                `prev month ${fmtCost(prevTotal)}`
              ) : (
                <>
                  <span className={delta <= 0 ? 'text-green' : 'text-amber'}>
                    {delta <= 0 ? '▼' : '▲'} {Math.abs(delta).toFixed(0)}%
                  </span>{' '}
                  vs prev month ({fmtCost(prevTotal)})
                </>
              )}
            </div>

            {/* ceiling */}
            <div style={{ marginTop: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
                <span className="mono-meta" style={{ textTransform: 'uppercase', letterSpacing: '0.1em' }}>monthly ceiling</span>
                <EditableValue
                  file="api_costs.json"
                  path="ceiling_usd"
                  value={ceiling}
                  type="number"
                  display={(v) => fmtUSD(Number(v) || 0)}
                  className="data-num"
                  style={{ fontSize: 14, color: 'var(--text-hi)' }}
                  inputWidth={70}
                />
              </div>
              <div className="bar-track" style={{ height: 7 }}>
                <div
                  className="bar-fill"
                  style={{ width: `${Math.min(100, pctOfCeiling)}%`, background: barColor }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
                <span className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                  {pctOfCeiling.toFixed(1)}% used
                </span>
                {warn && (
                  <span className={`badge ${warn === 'over' ? 'badge-red' : 'badge-amber'}`}>
                    {warn === 'over' ? '⚠ over ceiling' : '⚠ approaching ceiling'}
                  </span>
                )}
              </div>
            </div>

            {/* 30-day trend */}
            <div style={{ marginTop: 20 }}>
              <div className="mono-meta" style={{ marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                30-day trend
              </div>
              <div style={{ height: 86 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={spark} margin={{ top: 8, right: 10, left: 2, bottom: 0 }}>
                    <defs>
                      <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#d4a843" stopOpacity={0.4} />
                        <stop offset="100%" stopColor="#d4a843" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis
                      dataKey="d"
                      interval={6}
                      tick={{ fill: 'var(--text-mute)', fontSize: 9, fontFamily: 'JetBrains Mono' }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip content={<CostTip />} cursor={{ stroke: 'rgba(212,168,67,0.3)' }} />
                    <Area
                      type="monotone"
                      dataKey="usd"
                      stroke="#d4a843"
                      strokeWidth={1.8}
                      fill="url(#costFill)"
                      dot={false}
                      // no mount animation: the donut carries the motion; this
                      // guarantees the trend renders on first paint everywhere
                      isAnimationActive={false}
                      style={{ filter: 'drop-shadow(0 0 6px rgba(212,168,67,0.45))' }}
                    />
                    {/* endpoint marker — keeps "today" visible even when the
                        latest spend lands on the chart's right edge */}
                    {spark.length > 0 && (
                      <ReferenceDot
                        x={spark[spark.length - 1].d}
                        y={spark[spark.length - 1].usd}
                        r={3.2}
                        fill="#f0c060"
                        stroke="rgba(240,192,96,0.3)"
                        strokeWidth={4}
                      />
                    )}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* ── donut ── */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}>
            <div style={{ position: 'relative', width: D_SIZE, height: D_SIZE }}>
              <svg width={D_SIZE} height={D_SIZE} viewBox={`0 0 ${D_SIZE} ${D_SIZE}`}>
                {/* faint track behind the spend ring */}
                <circle cx={D_CX} cy={D_CX} r={D_R} fill="none" strokeWidth={D_W} className="donut-track" />
                {/* muted companion ring — the always-on Codex fleet ($0 marginal) */}
                <circle cx={D_CX} cy={D_CX} r={D_RI} fill="none" strokeWidth={5} className="donut-muted" strokeDasharray="1 7" strokeLinecap="round" />
                {/* real spend segments — glow is color-matched per segment so
                    deeper bronze arcs stay visually distinct from bright gold */}
                <g>
                  {segments.map((s, i) => {
                    const glow = { filter: `drop-shadow(0 0 8px ${s.color}66) drop-shadow(0 0 18px ${s.color}2e)` }
                    return s.end - s.start >= 359 ? (
                      <motion.circle
                        key={s.id}
                        cx={D_CX}
                        cy={D_CX}
                        r={D_R}
                        fill="none"
                        stroke={s.color}
                        strokeWidth={D_W}
                        strokeLinecap="round"
                        style={glow}
                        initial={{ pathLength: 0 }}
                        animate={{ pathLength: 1 }}
                        transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }}
                        transform={`rotate(-90 ${D_CX} ${D_CX})`}
                      />
                    ) : (
                      <motion.path
                        key={s.id}
                        d={arcPath(D_R, s.start, s.end)}
                        fill="none"
                        stroke={s.color}
                        strokeWidth={D_W}
                        strokeLinecap="round"
                        style={glow}
                        initial={{ pathLength: 0, opacity: 0 }}
                        animate={{ pathLength: 1, opacity: 1 }}
                        transition={{ duration: 0.9, delay: 0.15 + i * 0.12, ease: [0.22, 1, 0.36, 1] }}
                      />
                    )
                  })}
                </g>
              </svg>
              {/* center readout */}
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  pointerEvents: 'none',
                }}
              >
                <div className="stat-num" style={{ fontSize: 26 }}>{fmtCost(total)}</div>
                <div className="mono" style={{ fontSize: 8.5, letterSpacing: '0.18em', color: 'var(--text-mute)', textTransform: 'uppercase', marginTop: 3 }}>
                  this month
                </div>
              </div>
            </div>

            {/* legend */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7, width: '100%', maxWidth: 230 }}>
              {segments.length === 0 && (
                <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', textAlign: 'center' }}>
                  no metered spend this month
                </div>
              )}
              {segments.map((s) => (
                <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 3, background: s.color, boxShadow: `0 0 6px ${s.color}66`, flexShrink: 0 }} />
                  <span style={{ fontWeight: 500 }}>{s.name}</span>
                  <span className="data-num" style={{ marginLeft: 'auto', color: 'var(--text-dim)' }}>
                    {fmtCost(s.usd)} · {s.share.toFixed(0)}%
                  </span>
                </div>
              ))}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 }}>
                <span className="legend-muted-tick" style={{ width: 8, height: 8, borderRadius: 3, flexShrink: 0 }} />
                <span style={{ color: 'var(--text-dim)' }}>Codex fleet · included</span>
                <span className="data-num" style={{ marginLeft: 'auto', color: 'var(--text-mute)' }}>×{coveredCount}</span>
              </div>
            </div>
          </div>

          {/* ── fleet breakdown ── */}
          <div>
            <div className="mono-meta" style={{ marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
              fleet breakdown
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {fleet.map((a, i) => {
                const agent = AGENT_MAP[a.id]
                const seg = segments.find((s) => s.id === a.id)
                return (
                  <div
                    key={a.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      padding: '7px 2px',
                      borderBottom: i < fleet.length - 1 ? '0.5px solid rgba(128,128,140,0.10)' : 'none',
                    }}
                  >
                    <AgentAvatar agent={agent} size={26} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}>
                        {agent.name}
                        {seg && <span style={{ width: 6, height: 6, borderRadius: 2, background: seg.color, flexShrink: 0 }} />}
                      </div>
                      {a.note && (
                        <div className="mono" style={{ fontSize: 9, color: 'var(--text-mute)', marginTop: 1 }}>{a.note}</div>
                      )}
                    </div>
                    <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span
                        className="data-num"
                        style={{
                          fontSize: 12.5,
                          color: a.billing === 'none' ? 'var(--text-mute)' : a.month_usd > 0 ? (a.billing === 'metered' ? 'var(--gold)' : 'var(--text-dim)') : 'var(--text-mute)',
                        }}
                      >
                        {a.billing === 'none' ? '—' : fmtCost(a.month_usd)}
                      </span>
                      {a.billing === 'metered' ? (
                        <span className="badge badge-gold">metered</span>
                      ) : a.billing === 'codex' ? (
                        <span className="badge badge-purple" title="Included in the Codex subscription — $0 marginal cost">codex · included</span>
                      ) : (
                        <span className="badge badge-mute">no ai cost</span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </GlassCard>
  )
}

function monthName(m?: string): string {
  if (!m) return 'monthly'
  const d = new Date(`${m}-01T00:00:00Z`)
  return Number.isNaN(d.getTime()) ? 'monthly' : d.toLocaleDateString('en-US', { month: 'long', timeZone: 'UTC' })
}

function CostTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="glass" style={{ padding: '6px 10px', fontSize: 11 }}>
      <div className="mono" style={{ color: 'var(--text-dim)', marginBottom: 2 }}>{label}</div>
      <div className="mono text-gold">{fmtUSD(payload[0].value, 2)}</div>
    </div>
  )
}
