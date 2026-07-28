/** HOME — Command Grid direction.
 *
 * Layout thesis (refs: daily-route node map + AI command center):
 *   No greeting hero. A status strip reports date/clock/operator, then a
 *   single connected KPI RAIL — five metrics in one horizontal instrument
 *   with hairline dividers and per-metric glow sparklines. Below: a dense
 *   12-col grid — alert feed as flat LED-indexed rows (8 col), agent LED
 *   table (4 col), regime band full-width at the bottom.
 *
 * Type: numerals in JetBrains Mono (instrument read-out), labels mono
 * 9px/0.14em. League Spartan only for prose. Sharp 10px radii, 1px borders,
 * accent = cyan glow (--dir-accent under [data-direction=command]).
 */
import MiniSparkline from '../../components/MiniSparkline'
import AgentDot from '../../components/AgentDot'
import { ACTIVE_AGENTS } from '../../data/agentConfig'
import { useHQData, fmtUSD, fmtPct, fmtSigned } from '../../hooks/useHQData'
import { series, computeBladeTrades } from '../../data/derive'
import { CommandStatusBar, FeedAge } from '../shared'

const SPEC = { netWorth: 958000, goal: 10_000_000, tao: 3.345 }

export default function HomeCommand() {
  const nw = useHQData('net-worth').data
  const jerry = useHQData('jerry-portfolio').data
  const tao = useHQData('tao-portfolio').data
  const bladeBal = useHQData('blade-balance').data
  const bladeLog = useHQData('blade-learning-log').data
  const strat = useHQData('strategy-recommendation').data
  const victoria = useHQData('victoria-report').data

  const netWorth = nw?.networth_override ?? SPEC.netWorth
  const pnlToday = nw?.pnl_today ?? victoria?.financial_summary?.total_pnl_today ?? null
  const goalPct = (netWorth / SPEC.goal) * 100
  const bladeTrades = computeBladeTrades(bladeLog?.records || [])
  const bladeBalance = bladeBal?.balance ?? null
  const jerryRet = jerry?.total_pnl_pct ?? null
  const jerryVal = jerry?.balance ?? null
  const taoAmt = tao?.root_staked_tao ?? SPEC.tao
  const taoPrice = tao?.tao_price_usd ?? null

  const alerts = buildAlerts(victoria)
  const regime = strat?.regime ? cap(strat.regime) : null
  const regimeScore = regimeScoreOf(strat)

  return (
    <div className="page-pad cmd-root">
      <CommandStatusBar />

      {/* ── KPI RAIL — one connected instrument, not five cards ── */}
      <div className="cmd-rail">
        <RailCell
          label="NET WORTH" big={fmtUSD(netWorth)}
          sub={`${goalPct.toFixed(1)}% → $10M`}
          spark={series(7, 18, true)} tone="accent" primary
        />
        <RailCell
          label="P&L TODAY"
          big={fmtSigned(pnlToday)}
          tone={pnlToday != null && pnlToday < 0 ? 'red' : 'green'}
          sub="blade · jerry · tao"
          spark={series(21, 18, (pnlToday ?? 1) >= 0)}
        />
        <RailCell
          label="BLADE" big={fmtUSD(bladeBalance)}
          sub={`${bladeTrades.length} trades logged`}
          spark={series(33, 18, true)} tone="accent"
        />
        <RailCell
          label="JERRY" big={fmtPct(jerryRet)}
          sub={jerryVal != null ? fmtUSD(jerryVal) : 'alpaca paper'}
          spark={series(48, 18, (jerryRet ?? 1) >= 0)}
          tone={jerryRet != null && jerryRet < 0 ? 'red' : 'green'}
        />
        <RailCell
          label="TAO" big={`${taoAmt}`}
          sub={taoPrice ? fmtUSD(taoAmt * taoPrice) : 'staked'}
          spark={series(60, 18, false)} tone="purple"
        />
      </div>

      {/* ── 12-col: alert feed (8) + agent LED table (4) ── */}
      <div className="cmd-grid">
        <section className="cmd-panel" style={{ gridColumn: 'span 8' }}>
          <PanelHead title="SIGNAL FEED" right={<FeedAge iso={victoria?.date || victoria?.generated_at} label="victoria" />} />
          <div>
            {alerts.map((a, i) => (
              <div key={i} className="cmd-feed-row">
                <span className={`cmd-led cmd-led-${a.color}`} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 500 }}>{a.title}</div>
                  <div className="soft" style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2, lineHeight: 1.45 }}>{a.sub}</div>
                </div>
                <span className="mono" style={{ fontSize: 9.5, color: 'var(--text-mute)', letterSpacing: '0.08em', flexShrink: 0 }}>{a.time.toUpperCase()}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="cmd-panel" style={{ gridColumn: 'span 4' }}>
          <PanelHead title="AGENT STATUS" />
          <div>
            {ACTIVE_AGENTS.map((a) => (
              <div key={a.id} className="cmd-agent-row">
                <AgentDot state={a.state} />
                <span style={{ fontSize: 13, fontWeight: 500, flex: 1, minWidth: 0 }}>{a.name}</span>
                <span
                  className="mono"
                  style={{
                    fontSize: 8.5, letterSpacing: '0.1em',
                    color: a.state === 'LIVE' ? 'var(--green)' : a.state === 'STANDBY' ? 'var(--amber)' : 'var(--purple)',
                  }}
                >
                  {a.state}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* ── regime band — full-width instrument strip ── */}
      <section className="cmd-regime">
        <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap' }}>
          <span className="mono" style={{ fontSize: 9.5, letterSpacing: '0.16em', color: 'var(--text-mute)' }}>REGIME</span>
          {regime ? (
            <>
              <span className="mono" style={{ fontSize: 22, fontWeight: 600, color: 'var(--dir-accent)' }}>{regime.toUpperCase()}</span>
              <div className="cmd-regime-bar">
                <div className="cmd-regime-fill" style={{ width: `${regimeScore}%` }} />
              </div>
              <span className="mono" style={{ fontSize: 12, color: 'var(--text-dim)' }}>{regimeScore}/100</span>
              <FeedAge iso={strat?.updated} label="jarvis→lens" />
            </>
          ) : (
            <span className="soft" style={{ fontSize: 13, color: 'var(--text-dim)' }}>Awaiting regime read — next brief 06:00 UTC.</span>
          )}
        </div>
      </section>
    </div>
  )
}

// ── pieces ────────────────────────────────────────────────────────────

function RailCell({
  label, big, sub, spark, tone, primary,
}: {
  label: string; big: React.ReactNode; sub?: React.ReactNode
  spark?: number[]; tone?: 'accent' | 'green' | 'red' | 'purple'; primary?: boolean
}) {
  const toneColor =
    tone === 'green' ? 'var(--green)' : tone === 'red' ? 'var(--red)'
    : tone === 'purple' ? 'var(--purple)' : 'var(--dir-accent)'
  return (
    <div className={`cmd-rail-cell${primary ? ' cmd-rail-primary' : ''}`}>
      <div className="mono" style={{ fontSize: 9, letterSpacing: '0.16em', color: 'var(--text-mute)' }}>{label}</div>
      <div className="mono cmd-rail-num" style={{ color: toneColor }}>{big}</div>
      {sub && <div className="mono" style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 3 }}>{sub}</div>}
      {spark && (
        <div style={{ marginTop: 8 }}>
          <MiniSparkline data={spark} color={toneColor} height={22} />
        </div>
      )}
    </div>
  )
}

function PanelHead({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
      <span className="mono" style={{ fontSize: 9.5, letterSpacing: '0.16em', color: 'var(--text-mute)' }}>{title}</span>
      {right}
    </div>
  )
}

function cap(s: string) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s }

function buildAlerts(victoria: any) {
  const out: { title: string; sub: string; time: string; color: string }[] = []
  const alertList: string[] = Array.isArray(victoria?.alerts) ? victoria.alerts : []
  const fixPrompts: any[] = Array.isArray(victoria?.fix_prompts) ? victoria.fix_prompts : []
  fixPrompts.slice(0, 3).forEach((f) => out.push({
    title: f.problem || 'Issue flagged',
    sub: f.root_cause || f.estimated_impact || 'Victoria flagged this for review.',
    time: f.severity === 'high' ? 'high' : f.severity === 'medium' ? 'med' : 'low',
    color: f.severity === 'high' ? 'red' : f.severity === 'medium' ? 'amber' : 'accent',
  }))
  alertList.slice(0, 6 - out.length).forEach((a) => out.push({
    title: a, sub: 'From Victoria’s daily briefing.', time: 'today', color: 'amber',
  }))
  if (out.length === 0) {
    out.push(
      { title: 'All systems nominal', sub: 'No open alerts from the validators.', time: 'now', color: 'green' },
      { title: 'Live-paper executors armed', sub: 'Blade + Edge cron fires every 15 min in London + NY killzones.', time: 'armed', color: 'accent' },
      { title: 'Jerry idling on the library gate', sub: 'Zero deployable strategies for his asset classes — every buy refused by design.', time: 'idle', color: 'amber' },
    )
  }
  return out.slice(0, 6)
}

function regimeScoreOf(strat: any): number {
  if (!strat?.instruments) return 44
  const vals = Object.values(strat.instruments) as any[]
  const conf = vals.map((v) => Number(v.lens_confidence) || 50)
  return Math.round(conf.reduce((a, b) => a + b, 0) / (conf.length || 1))
}
