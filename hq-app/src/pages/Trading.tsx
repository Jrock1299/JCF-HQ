import type { ReactNode } from 'react'
import { AreaChart, Area, PieChart, Pie, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import GlassCard from '../components/GlassCard'
import AgentAvatar from '../components/AgentAvatar'
import EditableValue from '../components/EditableValue'
import { AGENT_MAP } from '../data/agentConfig'
import { useHQData, fmtUSD, fmtPct, fmtNum } from '../hooks/useHQData'
import { trajectory } from '../data/derive'

function SectionHead({ id, status }: { id: string; status: string }) {
  const a = AGENT_MAP[id]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18 }}>
      <AgentAvatar agent={a} size={46} />
      <div>
        <div className="head" style={{ fontSize: 24 }}>{a.name} {a.emoji}</div>
        <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>{a.role} · {status}</div>
      </div>
    </div>
  )
}

// Stat card whose value is editable in place (Round 2, Section 3).
function EditStat({
  label, file, path, value, type = 'number', display, color,
}: {
  label: string; file: string; path: string; value: number | string | null
  type?: 'number' | 'text'; display?: (v: any) => ReactNode; color?: string
}) {
  return (
    <GlassCard style={{ padding: 16 }}>
      <div className="mono-label" style={{ marginBottom: 8 }}>{label}</div>
      <EditableValue
        file={file}
        path={path}
        value={value}
        type={type}
        display={display}
        className="stat-num"
        style={{ fontSize: 22, color: color || 'var(--text-hi)' }}
      />
    </GlassCard>
  )
}

export default function Trading() {
  return (
    <div className="page-pad">
      <BladeSection />
      <div style={{ height: 36 }} />
      <JerrySection />
    </div>
  )
}

function BladeSection() {
  const bal = useHQData('blade-balance').data
  const manual = useHQData('blade-manual').data

  const balance = bal?.balance ?? 0
  const pnlToday = manual?.pnl_today ?? 0
  const winRate = manual?.win_rate ?? 0
  const wins = manual?.wins ?? 0
  const losses = manual?.losses ?? 0
  const session = manual?.session ?? '—'

  return (
    <div>
      <SectionHead id="blade" status="ASIA · LONDON · NY_PM · clean slate" />

      {/* 4 stat cards — kept, now editable */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, marginBottom: 22 }}>
        <EditStat label="balance" file="blade_balance.json" path="balance" value={balance} display={(v) => fmtUSD(Number(v) || 0)} />
        <EditStat
          label="p&l today" file="blade_manual.json" path="pnl_today" value={pnlToday}
          display={(v) => <span className={Number(v) < 0 ? 'text-red' : 'text-green'}>{signed(Number(v) || 0)}</span>}
        />
        <EditStat label="win rate" file="blade_manual.json" path="win_rate" value={winRate} display={(v) => `${(Number(v) || 0).toFixed(1)}%`} color="var(--gold)" />
        <EditStat label="session" file="blade_manual.json" path="session" value={session} type="text" color="var(--blue)" />
      </div>

      {/* Redesigned premium block — donut centerpiece + layered depth cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.15fr 1fr', gap: 20, alignItems: 'stretch' }}>
        {/* Win / Loss ring */}
        <GlassCard hover={false} style={{ padding: '30px 32px', display: 'flex', flexDirection: 'column' }}>
          <div className="mono-label" style={{ marginBottom: 6 }}>win / loss ratio</div>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 30, flexWrap: 'wrap' }}>
            <WinLossRing winRate={Number(winRate) || 0} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <RingLegend color="var(--green)" label="Wins" file="blade_manual.json" path="wins" value={wins} />
              <RingLegend color="var(--red)" label="Losses" file="blade_manual.json" path="losses" value={losses} />
              <div className="mono-meta" style={{ maxWidth: 150, lineHeight: 1.5, marginTop: 4 }}>
                Fresh account. The ring fills as clusters close and Norman validates the edge.
              </div>
            </div>
          </div>
        </GlassCard>

        {/* Layered depth cards */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <LayeredCard tint="gold">
            <div className="mono-label" style={{ marginBottom: 8 }}>risk rails · d3</div>
            <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
              <Rail k="per trade" v="≤ 1%" />
              <Rail k="per cluster" v="≤ 2%" />
              <Rail k="daily halt" v="−4%" />
            </div>
            <div className="mono-meta" style={{ marginTop: 12, lineHeight: 1.5 }}>
              Structural stop, R-multiple targets, pos3 trails. Rails are hard, not advisory.
            </div>
          </LayeredCard>

          <LayeredCard tint="blue">
            <div className="mono-label" style={{ marginBottom: 8 }}>validation</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
              <span className="stat-num text-blue" style={{ fontSize: 26 }}>0<span style={{ fontSize: 15, color: 'var(--text-dim)' }}> / 100</span></span>
              <span className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>clusters to Norman check</span>
            </div>
            <div className="bar-track" style={{ marginTop: 12 }}>
              <div className="bar-fill" style={{ width: '0%', background: 'var(--blue)', boxShadow: '0 0 10px rgba(56,189,248,0.5)' }} />
            </div>
          </LayeredCard>
        </div>
      </div>
    </div>
  )
}

function WinLossRing({ winRate }: { winRate: number }) {
  const wr = Math.max(0, Math.min(100, winRate))
  const hasData = wr > 0
  const data = hasData
    ? [{ name: 'win', value: wr }, { name: 'loss', value: 100 - wr }]
    : [{ name: 'empty', value: 100 }]
  const colors = hasData ? ['var(--green)', 'var(--red)'] : ['rgba(128,128,140,0.18)']
  return (
    <div style={{ position: 'relative', width: 190, height: 190 }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" innerRadius={68} outerRadius={92} startAngle={90} endAngle={-270} stroke="none" paddingAngle={hasData ? 2 : 0}>
            {data.map((_, i) => <Cell key={i} fill={colors[i]} />)}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
        <div className="stat-num" style={{ fontSize: 40, color: hasData ? 'var(--text-hi)' : 'var(--text-dim)' }}>{wr.toFixed(0)}%</div>
        <div className="mono" style={{ fontSize: 10, color: 'var(--text-dim)', letterSpacing: '0.08em' }}>{hasData ? 'WIN RATE' : 'NO TRADES YET'}</div>
      </div>
    </div>
  )
}

function RingLegend({ color, label, file, path, value }: { color: string; label: string; file: string; path: string; value: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ width: 10, height: 10, borderRadius: 3, background: color, boxShadow: `0 0 8px ${color}`, flexShrink: 0 }} />
      <div>
        <EditableValue file={file} path={path} value={value} type="number" className="stat-num" style={{ fontSize: 20 }} />
        <div className="mono-meta">{label}</div>
      </div>
    </div>
  )
}

function Rail({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="stat-num text-gold" style={{ fontSize: 20 }}>{v}</div>
      <div className="mono-meta" style={{ marginTop: 2 }}>{k}</div>
    </div>
  )
}

// Card with real stacked depth — two offset shadow layers behind the surface.
function LayeredCard({ children, tint }: { children: ReactNode; tint: 'gold' | 'blue' }) {
  const edge = tint === 'gold' ? 'rgba(212,168,67,0.16)' : 'rgba(56,189,248,0.14)'
  return (
    <div style={{ position: 'relative', flex: 1 }}>
      <div style={{ position: 'absolute', inset: 0, transform: 'translate(10px, 10px)', borderRadius: 14, background: 'var(--surface)', border: `1px solid ${edge}`, opacity: 0.35 }} />
      <div style={{ position: 'absolute', inset: 0, transform: 'translate(5px, 5px)', borderRadius: 14, background: 'var(--surface)', border: `1px solid ${edge}`, opacity: 0.6 }} />
      <div
        className="glass"
        style={{
          position: 'relative',
          height: '100%',
          padding: 20,
          border: `1px solid ${edge}`,
          boxShadow: `var(--card-shadow), 0 0 22px -6px ${edge}`,
        }}
      >
        {children}
      </div>
    </div>
  )
}

function JerrySection() {
  const jerry = useHQData('jerry-portfolio').data
  const val = jerry?.balance ?? null
  const ret = jerry?.total_pnl_pct ?? null
  const winRate = jerry?.win_rate != null ? jerry.win_rate * (jerry.win_rate <= 1 ? 100 : 1) : null
  const openPos: any[] = Array.isArray(jerry?.open_positions) ? jerry.open_positions : []

  const chartData = trajectory(100_000, val && val > 0 ? val : 109_672, 12)

  return (
    <div>
      <SectionHead id="jerry" status="Alpaca paper · LIVE" />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, marginBottom: 16 }}>
        <Stat label="account value" value={fmtUSD(val)} />
        <Stat label="return" value={<span className="text-blue">{fmtPct(ret)}</span>} />
        <Stat label="win rate" value={winRate != null ? `${winRate.toFixed(0)}%` : '--'} color="var(--gold)" />
        <Stat label="open positions" value={openPos.length || '--'} color="var(--purple)" />
      </div>

      <GlassCard hover={false} style={{ marginBottom: 16 }}>
        <div className="mono-label" style={{ marginBottom: 14 }}>portfolio value · 12mo</div>
        <div style={{ height: 200 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 4, right: 6, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="jerryFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#d4a843" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#d4a843" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="m" tick={{ fill: 'rgba(240,237,230,0.4)', fontSize: 10, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: 'rgba(240,237,230,0.4)', fontSize: 10, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip content={<ChartTip />} />
              <Area type="monotone" dataKey="v" stroke="#d4a843" strokeWidth={2} fill="url(#jerryFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </GlassCard>

      <GlassCard hover={false} style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px 8px' }} className="mono-label">open positions</div>
        {openPos.length === 0 ? (
          <div style={{ padding: 24, color: 'var(--text-dim)', fontSize: 13 }}>No open positions right now. Jerry’s waiting for the tape.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr><th>Symbol</th><th>Side</th><th style={{ textAlign: 'right' }}>Qty</th><th style={{ textAlign: 'right' }}>Value</th><th style={{ textAlign: 'right' }}>Unreal. P&L</th></tr>
              </thead>
              <tbody>
                {openPos.slice(0, 12).map((p, i) => (
                  <tr key={i}>
                    <td className="mono" style={{ fontWeight: 600 }}>{p.symbol}</td>
                    <td><span className={`badge ${String(p.side).includes('long') ? 'badge-green' : 'badge-red'}`}>{String(p.side || '').toUpperCase()}</span></td>
                    <td className="mono" style={{ textAlign: 'right' }}>{fmtNum(p.qty, 0)}</td>
                    <td className="mono" style={{ textAlign: 'right' }}>{fmtUSD(p.market_value)}</td>
                    <td className="mono" style={{ textAlign: 'right', color: (p.unrealized_pl ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>
                      {(p.unrealized_pl ?? 0) >= 0 ? '+' : '−'}{fmtUSD(Math.abs(p.unrealized_pl ?? 0))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <GlassCard style={{ padding: 16 }}>
      <div className="mono-label" style={{ marginBottom: 8 }}>{label}</div>
      <div className="stat-num" style={{ fontSize: 22, color: color || 'var(--text-hi)' }}>{value}</div>
    </GlassCard>
  )
}

function ChartTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="glass" style={{ padding: '6px 10px', fontSize: 12 }}>
      <span className="mono" style={{ color: 'var(--text-dim)' }}>{label} · </span>
      <span className="mono" style={{ color: 'var(--gold)' }}>{fmtUSD(payload[0].value)}</span>
    </div>
  )
}

function signed(n: number): string {
  return `${n >= 0 ? '+' : '−'}${fmtUSD(Math.abs(n))}`
}
