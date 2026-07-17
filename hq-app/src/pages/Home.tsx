import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import AgentAvatar from '../components/AgentAvatar'
import AgentDot from '../components/AgentDot'
import { useLiveClock, greeting } from '../hooks/useLiveClock'
import { quoteOfDay } from '../data/quotes'
import { AGENTS } from '../data/agentConfig'
import { useHQData, fmtUSD, fmtPct, fmtSigned } from '../hooks/useHQData'
import { series, computeBladeTrades } from '../data/derive'

const SPEC = { netWorth: 958000, goal: 10_000_000, tao: 3.345 }

function Label({ children }: { children: React.ReactNode }) {
  return <div className="mono-label" style={{ marginBottom: 14 }}>{children}</div>
}

export default function Home() {
  const now = useLiveClock()
  const quote = quoteOfDay(now)

  const nw = useHQData('net-worth').data
  const tl = useHQData('tradelocker-trades').data
  const jerry = useHQData('jerry-portfolio').data
  const tao = useHQData('tao-portfolio').data
  const bladeBal = useHQData('blade-balance').data
  const bladeLog = useHQData('blade-learning-log').data
  const bias = useHQData('market-bias').data
  const strat = useHQData('strategy-recommendation').data
  const victoria = useHQData('victoria-report').data

  const netWorth = nw?.networth_override ?? SPEC.netWorth
  const pnlToday = nw?.pnl_today ?? victoria?.financial_summary?.total_pnl_today ?? null
  const goalPct = (netWorth / SPEC.goal) * 100

  const bladeTrades = computeBladeTrades(bladeLog?.records || [])
  const bladeBalance = bladeBal?.balance ?? null
  const jerryVal = jerry?.balance ?? null
  const jerryRet = jerry?.total_pnl_pct ?? null
  const taoAmt = tao?.root_staked_tao ?? SPEC.tao
  const taoPrice = tao?.tao_price_usd ?? null

  const alerts = buildAlerts(victoria, strat)

  const news: any[] = Array.isArray(bias?.forex_news) ? bias.forex_news : []
  const econ = news.filter((n) => ['high', 'medium'].includes(String(n.impact).toLowerCase())).slice(0, 6)

  const regimeName = strat?.regime ? cap(strat.regime) : null
  const regimeScore = regimeScoreOf(strat)

  return (
    <div className="page-pad">
      {/* Greeting */}
      <GlassCard style={{ padding: 26, marginBottom: 20 }}>
        <div className="iceland" style={{ fontSize: 40, lineHeight: 1.05 }}>
          {greeting(now)}, <span className="gold-text">Jase.</span>
        </div>
        <div className="soft" style={{ marginTop: 12, fontStyle: 'italic', color: 'var(--text-dim)', fontSize: 16, maxWidth: 760, lineHeight: 1.5 }}>
          "{quote.text}"
        </div>
        <div className="mono" style={{ marginTop: 8, fontSize: 11, color: 'var(--gold)', letterSpacing: '0.04em' }}>
          — {quote.author}
        </div>
      </GlassCard>

      {/* Stat cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 1fr 1fr', gap: 14, marginBottom: 20 }}>
        <StatCard
          label="net worth"
          gradient
          value={fmtUSD(netWorth)}
          delay={0}
          spark={series(7, 16, true)}
          sub={
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 2 }}>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${Math.min(100, goalPct)}%`, background: 'linear-gradient(90deg,#d4a843,#f0c060)' }} />
              </div>
              <span className="mono" style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                {goalPct.toFixed(1)}% → $10M · 2037
              </span>
            </div>
          }
        />
        <StatCard
          label="p&l today"
          value={<span className={pnlToday != null && pnlToday < 0 ? 'text-red' : 'text-green'}>{fmtSigned(pnlToday)}</span>}
          sub={pnlBreakdown(victoria)}
          spark={series(21, 16, (pnlToday ?? 1) >= 0)}
          sparkColor="var(--green)"
          delay={0.04}
        />
        <StatCard
          label="blade 🔪"
          value={fmtUSD(bladeBalance)}
          valueColor="var(--text-hi)"
          sub={`${bladeBal?.last_session ? cap(bladeBal.last_session) : 'ORB'} · ${bladeTrades.length} trades logged`}
          spark={series(33, 16, true)}
          sparkColor="var(--gold)"
          delay={0.08}
        />
        <StatCard
          label="jerry 📊"
          value={<span className="text-blue">{fmtPct(jerryRet)}</span>}
          sub={jerryVal != null ? fmtUSD(jerryVal) : 'Alpaca paper'}
          spark={series(48, 16, (jerryRet ?? 1) >= 0)}
          sparkColor="var(--blue)"
          delay={0.12}
        />
        <StatCard
          label="tao ☯️"
          value={<span className="text-purple">{taoAmt} TAO</span>}
          sub={taoPrice ? `6 subnets · ${fmtUSD(taoAmt * taoPrice)}` : '6 subnets · Entry 1/5'}
          spark={series(60, 16, false)}
          sparkColor="var(--purple)"
          delay={0.16}
        />
      </div>

      {/* Row A: Needs Attention (wide) + Agents (full height) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 18, marginBottom: 18 }}>
        <GlassCard hover={false}>
          <Label>needs attention</Label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
            {alerts.map((a, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'flex-start', paddingBottom: i < alerts.length - 1 ? 13 : 0, borderBottom: i < alerts.length - 1 ? '0.5px solid rgba(128,128,140,0.10)' : 'none' }}>
                <div style={{ width: 3, alignSelf: 'stretch', minHeight: 38, borderRadius: 2, background: `var(--${a.color})`, boxShadow: `0 0 8px var(--${a.color})`, flexShrink: 0 }} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{a.title}</div>
                  <div className="soft" style={{ fontSize: 12.5, color: 'var(--text-dim)', marginTop: 3, lineHeight: 1.45 }}>{a.sub}</div>
                  <div className="mono-meta" style={{ marginTop: 4 }}>{a.time}</div>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard hover={false}>
          <Label>agents</Label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
            {AGENTS.map((a) => (
              <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <AgentDot state={a.state} />
                <AgentAvatar agent={a} size={26} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <span style={{ fontSize: 13.5, fontWeight: 500 }}>{a.name}</span>
                  <span className="soft" style={{ fontSize: 11.5, color: 'var(--text-mute)' }}> · {a.role}</span>
                </div>
                <span className="mono" style={{ fontSize: 9, color: a.state === 'LIVE' ? 'var(--green)' : a.state === 'STANDBY' ? 'var(--amber)' : 'var(--purple)', letterSpacing: '0.06em' }}>
                  {a.state}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>

      {/* Row B: Econ Calendar + Regime */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 18 }}>
        <GlassCard hover={false}>
          <Label>econ calendar</Label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
            {econ.length === 0 && <div className="soft" style={{ fontSize: 13, color: 'var(--text-dim)' }}>No high-impact events queued. Quiet tape.</div>}
            {econ.map((e, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                <span className={`badge badge-${String(e.impact).toLowerCase() === 'high' ? 'red' : 'amber'}`}>
                  {String(e.impact).toLowerCase() === 'high' ? 'HIGH' : 'MED'}
                </span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 13, lineHeight: 1.4 }}>{e.headline}</div>
                  <div className="mono-meta" style={{ marginTop: 2 }}>{e.source} · {e.time}</div>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard tint="blue" hover={false}>
          <Label>regime</Label>
          {regimeName ? (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span className="stat-num text-blue" style={{ fontSize: 26 }}>{regimeName}</span>
                <span className="mono" style={{ fontSize: 12, color: 'var(--text-dim)' }}>{regimeScore}/100</span>
              </div>
              <div className="bar-track" style={{ marginTop: 12 }}>
                <div className="bar-fill" style={{ width: `${regimeScore}%`, background: 'var(--blue)', boxShadow: '0 0 10px 0 rgba(56,189,248,0.5)' }} />
              </div>
              <div className="soft" style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 12, lineHeight: 1.5 }}>
                {regimePlain(regimeName, regimeScore)}
              </div>
            </>
          ) : (
            <div className="soft" style={{ fontSize: 13, color: 'var(--text-dim)' }}>Awaiting Jarvis regime read — next brief 06:00 UTC.</div>
          )}
        </GlassCard>
      </div>
    </div>
  )
}

// ── helpers ──────────────────────────────────────────────────────────
function cap(s: string) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

function pnlBreakdown(victoria: any) {
  const b = victoria?.financial_summary?.breakdown
  if (!b) return 'Blade · Jerry · Tao'
  const parts = Object.entries(b)
    .filter(([, v]) => typeof v === 'number' && v !== 0)
    .slice(0, 3)
    .map(([k, v]) => `${cap(k)} ${(v as number) >= 0 ? '+' : '−'}$${Math.abs(v as number).toFixed(0)}`)
  return parts.length ? parts.join(' · ') : 'Blade · Jerry · Tao'
}

function buildAlerts(victoria: any, strat: any) {
  const out: { title: string; sub: string; time: string; color: string }[] = []
  const alertList: string[] = Array.isArray(victoria?.alerts) ? victoria.alerts : []
  const fixPrompts: any[] = Array.isArray(victoria?.fix_prompts) ? victoria.fix_prompts : []

  fixPrompts.slice(0, 3).forEach((f) => {
    out.push({
      title: f.problem || 'Issue flagged',
      sub: f.root_cause || f.estimated_impact || 'Victoria flagged this for review.',
      time: sev(f.severity),
      color: f.severity === 'high' ? 'red' : f.severity === 'medium' ? 'amber' : 'blue',
    })
  })
  alertList.slice(0, 6 - out.length).forEach((a) => {
    out.push({ title: a, sub: 'From Victoria’s daily briefing.', time: 'today', color: 'amber' })
  })

  if (out.length === 0) {
    out.push(
      { title: 'All systems nominal', sub: 'No open alerts from Victoria or Norman. Family’s eating.', time: 'now', color: 'green' },
      { title: 'Blade D3 validation in progress', sub: 'Filling the learning log toward Norman’s 100-cluster checkpoint before live sizing.', time: 'ongoing', color: 'blue' },
      { title: 'Portfolio syncs on schedule', sub: 'Robinhood, Trust Wallet, Kraken, Plaid refresh on the 1st & 15th.', time: 'scheduled', color: 'blue' },
      { title: 'Storage API online', sub: 'hq-storage (:8900) live — Agent Hub read/write and POST-backed features are up.', time: 'now', color: 'green' },
      { title: 'Edge on standby', sub: '1H SMA strategy built and idle on account 002. Awaiting the green light.', time: 'idle', color: 'amber' },
    )
  }
  return out.slice(0, 6)
}
function sev(s: string) {
  return s === 'high' ? 'high priority' : s === 'medium' ? 'medium' : 'low'
}

function regimeScoreOf(strat: any): number {
  if (!strat?.instruments) return 44
  const vals = Object.values(strat.instruments) as any[]
  const conf = vals.map((v) => Number(v.lens_confidence) || 50)
  const avg = conf.reduce((a, b) => a + b, 0) / (conf.length || 1)
  return Math.round(avg)
}
function regimePlain(name: string, score: number): string {
  const n = name.toLowerCase()
  if (n.includes('compress')) return `Compressed — ${score}/100. Range-bound and coiled. Wait for the break; don’t predict it.`
  if (n.includes('volatil')) return `Volatile — ${score}/100. Big swings both ways. Smaller size, wider stops, quicker hands.`
  if (n.includes('trend')) return `Trending — ${score}/100. Momentum has a direction. Lean with it, don’t fade it.`
  if (n.includes('chop')) return `Choppy — ${score}/100. Not a trending day. Don’t force anything.`
  return `${name} — ${score}/100. Read the tape before you commit size.`
}
