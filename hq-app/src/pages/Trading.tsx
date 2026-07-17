import { useState } from 'react'
import { AreaChart, Area, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import GlassCard from '../components/GlassCard'
import AgentAvatar from '../components/AgentAvatar'
import { AGENT_MAP } from '../data/agentConfig'
import { useHQData, fmtUSD, fmtPct, fmtNum } from '../hooks/useHQData'
import { computeBladeTrades, bladeWinRate, trajectory } from '../data/derive'

function Stat({ label, value, color }: { label: string; value: React.ReactNode; color?: string }) {
  return (
    <GlassCard style={{ padding: 16 }}>
      <div className="mono-label" style={{ marginBottom: 8 }}>{label}</div>
      <div className="stat-num" style={{ fontSize: 22, color: color || 'var(--text-hi)' }}>{value}</div>
    </GlassCard>
  )
}

function SectionHead({ id, status }: { id: string; status: string }) {
  const a = AGENT_MAP[id]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16 }}>
      <AgentAvatar agent={a} size={46} />
      <div>
        <div style={{ fontSize: 20, fontWeight: 600 }}>{a.name} {a.emoji}</div>
        <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>{a.role} · {status}</div>
      </div>
    </div>
  )
}

export default function Trading() {
  return (
    <div className="page-pad">
      <BladeSection />
      <div style={{ height: 32 }} />
      <JerrySection />
    </div>
  )
}

function BladeSection() {
  const bal = useHQData('blade-balance').data
  const log = useHQData('blade-learning-log').data
  const victoria = useHQData('victoria-report').data
  const [page, setPage] = useState(0)

  const trades = computeBladeTrades(log?.records || [])
  const balance = bal?.balance ?? null
  const winRate = bladeWinRate(trades)
  const todayPnl = victoria?.financial_summary?.breakdown?.blade ?? null
  const session = bal?.last_session ? cap(bal.last_session) : '—'

  // circuit breaker: daily DD vs -4%
  const ddPct = todayPnl != null && balance ? (todayPnl / balance) * 100 : 0
  const ddRatio = Math.min(100, (Math.abs(Math.min(0, ddPct)) / 4) * 100)

  const perPage = 10
  const pageCount = Math.max(1, Math.ceil(trades.length / perPage))
  const shown = trades.slice(page * perPage, page * perPage + perPage)

  return (
    <div>
      <SectionHead id="blade" status={`ASIA · LONDON · NY_PM`} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, marginBottom: 16 }}>
        <Stat label="balance" value={fmtUSD(balance)} />
        <Stat label="today p&l" value={<span className={(todayPnl ?? 0) < 0 ? 'text-red' : 'text-green'}>{todayPnl != null ? (todayPnl >= 0 ? '+' : '−') + fmtUSD(Math.abs(todayPnl)) : '--'}</span>} />
        <Stat label="win rate" value={winRate != null ? `${winRate.toFixed(1)}%` : '--'} color="var(--gold)" />
        <Stat label="session" value={session} color="var(--blue)" />
      </div>

      {/* D3 sizing + circuit breaker */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16, marginBottom: 16 }}>
        <GlassCard hover={false}>
          <div className="mono-label" style={{ marginBottom: 12 }}>d3 position sizing · 2% cluster risk</div>
          <div style={{ display: 'flex', height: 34, borderRadius: 8, overflow: 'hidden', border: '0.5px solid var(--glass-border)' }}>
            <SizeSeg pct={20} label="Pos1 · quick 1R" color="rgba(56,189,248,0.35)" />
            <SizeSeg pct={30} label="Pos2 · 2R runner" color="rgba(212,168,67,0.4)" />
            <SizeSeg pct={50} label="Pos3 · trail" color="rgba(34,197,94,0.35)" />
          </div>
          <div className="mono-meta" style={{ marginTop: 10, lineHeight: 1.5 }}>
            Stop is structural (opposite ORB ± 3pt). TPs as R-multiples of real stop. Best-case cluster R:R 3.3:1.
          </div>
        </GlassCard>

        <GlassCard hover={false}>
          <div className="mono-label" style={{ marginBottom: 12 }}>circuit breaker · daily dd</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span className="stat-num" style={{ fontSize: 20, color: ddRatio > 75 ? 'var(--red)' : 'var(--text-hi)' }}>{fmtPct(ddPct)}</span>
            <span className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>limit −4.0%</span>
          </div>
          <div className="bar-track" style={{ marginTop: 12 }}>
            <div className="bar-fill" style={{ width: `${ddRatio}%`, background: ddRatio > 75 ? 'var(--red)' : ddRatio > 40 ? 'var(--amber)' : 'var(--green)' }} />
          </div>
          <div className="mono-meta" style={{ marginTop: 10 }}>
            {ddRatio > 90 ? 'Near halt — sessions suspend at −4%.' : 'Within rails. Trading enabled.'}
          </div>
        </GlassCard>
      </div>

      {/* Trade table */}
      <GlassCard hover={false} style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px 8px' }} className="mono-label">recent clusters · computed R</div>
        {trades.length === 0 ? (
          <div style={{ padding: 24, color: 'var(--text-dim)', fontSize: 13 }}>No trades logged yet. The learning log fills as sessions run.</div>
        ) : (
          <>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th><th>Session</th><th>Instrument</th><th>Dir</th><th style={{ textAlign: 'right' }}>R</th><th style={{ textAlign: 'right' }}>Entry → Close</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((t, i) => (
                    <tr key={i} style={{ background: t.pnlSign === 'win' ? 'rgba(34,197,94,0.04)' : 'rgba(239,68,68,0.04)' }}>
                      <td className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>{fmtDate(t.timestamp_close)}</td>
                      <td>{t.session}</td>
                      <td className="mono" style={{ fontSize: 12 }}>{t.instrument}</td>
                      <td><span className={`badge ${t.direction === 'LONG' ? 'badge-green' : 'badge-red'}`}>{t.direction}</span></td>
                      <td className="mono" style={{ textAlign: 'right', color: t.r >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>{t.r >= 0 ? '+' : ''}{t.r.toFixed(2)}R</td>
                      <td className="mono" style={{ textAlign: 'right', fontSize: 11, color: 'var(--text-dim)' }}>{fmtNum(t.entry_price)} → {fmtNum(t.close_price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 20px' }}>
              <span className="mono-meta">{trades.length} clusters · page {page + 1}/{pageCount}</span>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="badge badge-mute" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} style={{ opacity: page === 0 ? 0.4 : 1 }}>← Prev</button>
                <button className="badge badge-mute" onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))} disabled={page >= pageCount - 1} style={{ opacity: page >= pageCount - 1 ? 0.4 : 1 }}>Next →</button>
              </div>
            </div>
          </>
        )}
      </GlassCard>
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

function SizeSeg({ pct, label, color }: { pct: number; label: string; color: string }) {
  return (
    <div style={{ width: `${pct}%`, background: color, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRight: '0.5px solid rgba(7,8,15,0.5)' }}>
      <span className="mono" style={{ fontSize: 9.5, color: 'var(--text-hi)', whiteSpace: 'nowrap', overflow: 'hidden', padding: '0 4px' }}>{label}</span>
    </div>
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

function cap(s: string) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s }
function fmtDate(iso: string) {
  if (!iso) return '--'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '--'
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
