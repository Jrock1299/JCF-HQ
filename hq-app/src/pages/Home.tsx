import { Link } from 'react-router-dom'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import AgentAvatar from '../components/AgentAvatar'
import AgentDot from '../components/AgentDot'
import ChatBubble from '../components/ChatBubble'
import { useLiveClock, greeting } from '../hooks/useLiveClock'
import { quoteOfDay } from '../data/quotes'
import { AGENTS, AGENT_MAP } from '../data/agentConfig'
import { THREADS } from '../data/seedMessages'
import { useHQData, fmtUSD, fmtPct, fmtSigned } from '../hooks/useHQData'
import { series, computeBladeTrades } from '../data/derive'

const SPEC = { netWorth: 958000, goal: 10_000_000, tao: 3.345 }

function Label({ children }: { children: React.ReactNode }) {
  return <div className="mono-label" style={{ marginBottom: 12 }}>{children}</div>
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

  // ── alerts (needs attention) ─────────────────────────────
  const alerts = buildAlerts(victoria, strat)

  // ── econ calendar / news (today's high+med) ──────────────
  const news: any[] = Array.isArray(bias?.forex_news) ? bias.forex_news : []
  const econ = news.filter((n) => ['high', 'medium'].includes(String(n.impact).toLowerCase())).slice(0, 5)

  // ── regime ───────────────────────────────────────────────
  const regimeName = strat?.regime ? cap(strat.regime) : null
  const regimeScore = regimeScoreOf(strat)

  const hubPreview = THREADS.filter((t) => t.messages.length).slice(0, 3)

  return (
    <div className="page-pad">
      {/* Greeting */}
      <GlassCard style={{ padding: 26, marginBottom: 20 }}>
        <div className="hero-num" style={{ fontSize: 28 }}>
          {greeting(now)}, <span className="gold-text">Jase.</span>
        </div>
        <div style={{ marginTop: 12, fontStyle: 'italic', color: 'var(--text-dim)', fontSize: 15, maxWidth: 720, lineHeight: 1.5 }}>
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

      {/* Three-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr 1fr', gap: 18, marginBottom: 20 }}>
        {/* Needs attention */}
        <GlassCard hover={false}>
          <Label>needs attention</Label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {alerts.map((a, i) => (
              <div key={i} style={{ display: 'flex', gap: 11, alignItems: 'flex-start' }}>
                <div style={{ width: 2, alignSelf: 'stretch', minHeight: 34, borderRadius: 2, background: `var(--${a.color})`, flexShrink: 0 }} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 500 }}>{a.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2, lineHeight: 1.45 }}>{a.sub}</div>
                  <div className="mono-meta" style={{ marginTop: 3 }}>{a.time}</div>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Agents */}
        <GlassCard hover={false}>
          <Label>agents</Label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
            {AGENTS.map((a) => (
              <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <AgentDot state={a.state} />
                <AgentAvatar agent={a} size={24} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{a.name}</span>
                  <span style={{ fontSize: 11.5, color: 'var(--text-mute)' }}> · {a.role}</span>
                </div>
                <span className={`mono`} style={{ fontSize: 9, color: a.state === 'LIVE' ? 'var(--green)' : a.state === 'STANDBY' ? 'var(--amber)' : 'var(--purple)', letterSpacing: '0.06em' }}>
                  {a.state}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Right stack: econ + regime */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <GlassCard hover={false}>
            <Label>econ calendar</Label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              {econ.length === 0 && <div style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>No high-impact events queued. Quiet tape.</div>}
              {econ.map((e, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 9 }}>
                  <span className={`badge badge-${String(e.impact).toLowerCase() === 'high' ? 'red' : 'amber'}`}>
                    {String(e.impact).toLowerCase() === 'high' ? 'HIGH' : 'MED'}
                  </span>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 12.5, lineHeight: 1.35 }}>{e.headline}</div>
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
                  <span className="stat-num text-blue" style={{ fontSize: 20 }}>{regimeName}</span>
                  <span className="mono" style={{ fontSize: 12, color: 'var(--text-dim)' }}>{regimeScore}/100</span>
                </div>
                <div className="bar-track" style={{ marginTop: 10 }}>
                  <div className="bar-fill" style={{ width: `${regimeScore}%`, background: 'var(--blue)' }} />
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--text-dim)', marginTop: 10, lineHeight: 1.45 }}>
                  {regimePlain(regimeName, regimeScore)}
                </div>
              </>
            ) : (
              <div style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>Awaiting Jarvis regime read — next brief 06:00 UTC.</div>
            )}
          </GlassCard>
        </div>
      </div>

      {/* Hub preview */}
      <GlassCard tint="purple" hover={false}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div className="mono-label">agent hub · latest</div>
          <Link to="/hub" className="badge badge-purple" style={{ cursor: 'pointer' }}>Open Agent Hub →</Link>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 16 }}>
          {hubPreview.map((t) => {
            const agent = AGENT_MAP[t.agentId]
            const msg = t.messages[0]
            return <ChatBubble key={t.agentId} from="agent" agent={agent} text={truncate(msg.text, 150)} time={msg.time} />
          })}
        </div>
      </GlassCard>
    </div>
  )
}

// ── helpers ──────────────────────────────────────────────────────────
function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n).trimEnd() + '…' : s
}
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

  fixPrompts.slice(0, 2).forEach((f) => {
    out.push({
      title: f.problem || 'Issue flagged',
      sub: f.root_cause || f.estimated_impact || 'Victoria flagged this for review.',
      time: sev(f.severity),
      color: f.severity === 'high' ? 'red' : f.severity === 'medium' ? 'amber' : 'blue',
    })
  })
  alertList.slice(0, 4 - out.length).forEach((a) => {
    out.push({ title: a, sub: 'From Victoria’s daily briefing.', time: 'today', color: 'amber' })
  })

  if (out.length === 0) {
    out.push(
      { title: 'All systems nominal', sub: 'No open alerts from Victoria or Norman. Family’s eating.', time: 'now', color: 'green' as any },
      { title: 'Blade D3 validation in progress', sub: 'Filling the learning log toward Norman’s 100-cluster checkpoint before live sizing.', time: 'ongoing', color: 'blue' },
      { title: 'Portfolio syncs on schedule', sub: 'Robinhood, Trust Wallet, Kraken, Plaid refresh on the 1st & 15th.', time: 'scheduled', color: 'blue' },
    )
  }
  return out.slice(0, 4)
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
