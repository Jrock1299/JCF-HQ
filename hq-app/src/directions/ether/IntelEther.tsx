/** INTELLIGENCE — Ether Ledger direction.
 *
 * Same DEAD-DATA FIX as the Command variant (no morning_report fossil; all
 * feeds stale-guarded), rendered in the neo-pop language: bias as tinted
 * pill cards per pair, verdicts as chip-grid, sentinel as rounded list.
 */
import { useHQData } from '../../hooks/useHQData'
import { EtherGreeting, FeedAge, StaleGuard } from '../shared'

export default function IntelEther() {
  const bias = useHQData('market-bias').data
  const strat = useHQData('strategy-recommendation').data
  const sentinel = useHQData('sentinel-data').data
  const lensVal = useHQData('lens-validation').data
  const vicVal = useHQData('victoria-validation').data

  const pairs: any[] = Array.isArray(bias?.pairs) ? bias.pairs : []
  const verdicts = fleetVerdicts(lensVal, vicVal)
  const signals: any[] = (sentinel?.watchlist_signals || sentinel?.top_discoveries || []).slice(0, 6)

  return (
    <div className="page-pad ether-root">
      <EtherGreeting />

      {/* macro bias — tinted pair cards */}
      <section className="ether-card" style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <span style={{ fontSize: 17, fontWeight: 600 }}>Macro read — Lens</span>
          <FeedAge iso={bias?.last_updated} />
        </div>
        <StaleGuard iso={bias?.last_updated} feedName="market_bias.json (Lens daily)">
          <div className="ether-pair-grid">
            {pairs.map((p, i) => (
              <div key={i} className={`ether-tint ether-tint-${p.bias === 'bullish' ? 'green' : p.bias === 'bearish' ? 'red' : 'gold'}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>{p.symbol}</span>
                  <span className="soft" style={{ fontSize: 11, opacity: 0.7, textTransform: 'capitalize' }}>{p.bias}</span>
                </div>
                <div className="ether-goal-track" style={{ marginTop: 10 }}>
                  <div className="ether-goal-fill" style={{ width: `${p.confidence ?? 50}%` }} />
                </div>
                <div className="soft" style={{ fontSize: 10.5, opacity: 0.6, marginTop: 4 }}>{p.confidence ?? '--'}% conviction</div>
              </div>
            ))}
          </div>
          {bias?.summary && (
            <p className="soft" style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.6, marginTop: 16, maxWidth: '68ch' }}>
              {bias.summary}
            </p>
          )}
        </StaleGuard>
      </section>

      {/* fleet verdicts as chips */}
      <section className="ether-card" style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 14 }}>Validator verdicts</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {verdicts.map((v) => (
            <div key={v.agent} className={`ether-verdict ether-verdict-${tone(v.verdict)}`}>
              <span style={{ fontSize: 13.5, fontWeight: 700, textTransform: 'capitalize' }}>{v.agent}</span>
              <span style={{ fontSize: 11.5, fontWeight: 600, opacity: 0.85 }}>{v.verdict}</span>
              {v.n != null && <span className="soft" style={{ fontSize: 10, opacity: 0.6 }}>{v.n} trades</span>}
            </div>
          ))}
        </div>
      </section>

      {/* sentinel */}
      <section className="ether-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <span style={{ fontSize: 17, fontWeight: 600 }}>Sentinel signals</span>
          <FeedAge iso={sentinel?.last_updated} />
        </div>
        <StaleGuard iso={sentinel?.last_updated} feedName="sentinel_data.json (3×/day)">
          {signals.length === 0 ? (
            <div className="soft" style={{ fontSize: 13, color: 'var(--text-dim)' }}>
              Quiet window — Sentinel sweeps at 08:00, 14:00 and 20:00 UTC.
            </div>
          ) : (
            signals.map((s: any, i: number) => (
              <div key={i} className="ether-alert-row">
                <span className="ether-chip ether-chip-blue">{s.symbol || s.ticker || '•'}</span>
                <div className="soft" style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.5, minWidth: 0 }}>
                  {s.headline || s.signal || s.reason || JSON.stringify(s).slice(0, 110)}
                </div>
              </div>
            ))
          )}
        </StaleGuard>
        {strat?.regime && (
          <div className="ether-regime-note" style={{ marginTop: 14 }}>
            Regime: <strong style={{ textTransform: 'capitalize' }}>{strat.regime}</strong>
            <FeedAge iso={strat?.updated} />
          </div>
        )}
      </section>
    </div>
  )
}

function fleetVerdicts(lensVal: any, vicVal: any) {
  const out: { agent: string; verdict: string; n: number | null }[] = []
  for (const [agent, r] of Object.entries<any>(lensVal?.agent_reports || {})) {
    out.push({ agent, verdict: r?.verdict ?? 'UNKNOWN', n: r?.total_trades ?? null })
  }
  for (const [agent, r] of Object.entries<any>(vicVal?.agent_reports || {})) {
    out.push({ agent: agent === 'crisp' ? 'chad' : agent, verdict: r?.verdict ?? 'UNKNOWN', n: r?.total_trades ?? null })
  }
  return out
}

function tone(v: string) {
  if (v === 'PASS') return 'green'
  if (v === 'FAIL') return 'red'
  if (v === 'MARGINAL') return 'amber'
  return 'mute'
}
