/** HOME — Ether Ledger direction.
 *
 * Layout thesis (refs: ethereal neo-pop fintech + Fierce warm luxe):
 *   Big friendly greeting in League Spartan. ONE dominant saturated
 *   gradient feature card (gold→amber — the JCF identity hue) carrying net
 *   worth huge + goal progress; a right-hand stack of tinted stat cards
 *   (each washed in its metric's hue). Below: rounded alert card + agents
 *   as an avatar chip-grid. Pill top-nav replaces the sidebar (rendered by
 *   Layout when direction=ether).
 *
 * Type: League Spartan forward, big friendly numerals, minimal mono
 * (labels only). Rounded-2xl geometry (20px lock). Soft tinted shadows,
 * ZERO backdrop-blur.
 */
import AgentAvatar from '../../components/AgentAvatar'
import AgentDot from '../../components/AgentDot'
import { ACTIVE_AGENTS } from '../../data/agentConfig'
import { useHQData, fmtUSD, fmtPct, fmtSigned } from '../../hooks/useHQData'
import { EtherGreeting, FeedAge } from '../shared'

const SPEC = { netWorth: 958000, goal: 10_000_000, tao: 3.345 }

export default function HomeEther() {
  const nw = useHQData('net-worth').data
  const jerry = useHQData('jerry-portfolio').data
  const tao = useHQData('tao-portfolio').data
  const bladeBal = useHQData('blade-balance').data
  const victoria = useHQData('victoria-report').data
  const strat = useHQData('strategy-recommendation').data

  const netWorth = nw?.networth_override ?? SPEC.netWorth
  const pnlToday = nw?.pnl_today ?? victoria?.financial_summary?.total_pnl_today ?? null
  const goalPct = (netWorth / SPEC.goal) * 100
  const bladeBalance = bladeBal?.balance ?? null
  const jerryRet = jerry?.total_pnl_pct ?? null
  const taoAmt = tao?.root_staked_tao ?? SPEC.tao
  const taoPrice = tao?.tao_price_usd ?? null
  const regime = strat?.regime ?? null

  const alerts = topAlerts(victoria)

  return (
    <div className="page-pad ether-root">
      <EtherGreeting />

      {/* ── Feature card + tinted stack ── */}
      <div className="ether-hero-grid">
        {/* Dominant gradient feature card */}
        <div className="ether-feature">
          <div style={{ fontSize: 15, fontWeight: 500, opacity: 0.85 }}>Total net worth</div>
          <div className="ether-hero-num">{fmtUSD(netWorth)}</div>
          <div style={{ fontSize: 13.5, opacity: 0.8, marginTop: 4 }}>
            {goalPct.toFixed(1)}% of the $10M goal · 2037
          </div>
          <div className="ether-goal-track" role="progressbar" aria-valuenow={Math.round(goalPct)} aria-valuemin={0} aria-valuemax={100}>
            <div className="ether-goal-fill" style={{ width: `${Math.min(100, goalPct)}%` }} />
          </div>
        </div>

        {/* Tinted stat stack */}
        <div className="ether-stat-stack">
          <TintCard
            tint={pnlToday != null && pnlToday < 0 ? 'red' : 'green'}
            label="P&L today" value={fmtSigned(pnlToday)}
            sub="Blade · Jerry · Tao"
          />
          <TintCard tint="gold" label="Blade" value={fmtUSD(bladeBalance)} sub="OANDA paper" />
          <TintCard tint="blue" label="Jerry" value={fmtPct(jerryRet)} sub="Alpaca paper" />
          <TintCard tint="purple" label="TAO" value={`${taoAmt} TAO`} sub={taoPrice ? fmtUSD(taoAmt * taoPrice) : 'staked'} />
        </div>
      </div>

      {/* ── Alerts + agents ── */}
      <div className="ether-body-grid">
        <div className="ether-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <span style={{ fontSize: 17, fontWeight: 600 }}>Needs attention</span>
            <FeedAge iso={victoria?.date || victoria?.generated_at} />
          </div>
          {alerts.map((a, i) => (
            <div key={i} className="ether-alert-row">
              <span className={`ether-chip ether-chip-${a.color}`}>{a.tag}</span>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 500 }}>{a.title}</div>
                <div className="soft" style={{ fontSize: 12.5, color: 'var(--text-dim)', marginTop: 2, lineHeight: 1.45 }}>{a.sub}</div>
              </div>
            </div>
          ))}
        </div>

        <div className="ether-card">
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 14 }}>The team</div>
          <div className="ether-agent-grid">
            {ACTIVE_AGENTS.map((a) => (
              <div key={a.id} className="ether-agent-chip">
                <AgentAvatar agent={a} size={34} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.15 }}>{a.name}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 2 }}>
                    <AgentDot state={a.state} />
                    <span className="soft" style={{ fontSize: 10.5, color: 'var(--text-mute)' }}>{a.role}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
          {regime && (
            <div className="ether-regime-note">
              Regime read: <strong style={{ textTransform: 'capitalize' }}>{regime}</strong>
              <FeedAge iso={strat?.updated} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── pieces ────────────────────────────────────────────────────────────

function TintCard({
  tint, label, value, sub,
}: {
  tint: 'green' | 'red' | 'gold' | 'blue' | 'purple'
  label: string; value: React.ReactNode; sub?: string
}) {
  return (
    <div className={`ether-tint ether-tint-${tint}`}>
      <div style={{ fontSize: 12.5, fontWeight: 500, opacity: 0.75 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.015em', marginTop: 3 }}>{value}</div>
      {sub && <div className="soft" style={{ fontSize: 11, opacity: 0.65, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function topAlerts(victoria: any) {
  const out: { title: string; sub: string; tag: string; color: string }[] = []
  const fixPrompts: any[] = Array.isArray(victoria?.fix_prompts) ? victoria.fix_prompts : []
  const alertList: string[] = Array.isArray(victoria?.alerts) ? victoria.alerts : []
  fixPrompts.slice(0, 3).forEach((f) => out.push({
    title: f.problem || 'Issue flagged',
    sub: f.root_cause || f.estimated_impact || 'Victoria flagged this for review.',
    tag: f.severity === 'high' ? 'High' : f.severity === 'medium' ? 'Med' : 'Low',
    color: f.severity === 'high' ? 'red' : f.severity === 'medium' ? 'amber' : 'blue',
  }))
  alertList.slice(0, 5 - out.length).forEach((a) => out.push({
    title: a, sub: 'From Victoria’s daily briefing.', tag: 'Note', color: 'amber',
  }))
  if (out.length === 0) {
    out.push(
      { title: 'All quiet', sub: 'No open alerts from the validators today.', tag: 'OK', color: 'green' },
      { title: 'Executors armed', sub: 'Blade + Edge fire every 15 min in the killzones, paper mode.', tag: 'Live', color: 'blue' },
      { title: 'Jerry waiting on a strategy', sub: 'Library gate refuses every buy until something validates.', tag: 'Idle', color: 'amber' },
    )
  }
  return out.slice(0, 5)
}
