/** INTELLIGENCE — Command Grid direction.
 *
 * DEAD-DATA FIX (2026-07-28): this page NO LONGER reads morning_report.json —
 * that feed fossilised at 2026-04-15 (pre-Oracle-retirement, "Crisp & Blade",
 * NHL picks) and its generating cron is #HOLD. Current sources, all
 * stale-guarded (>7d → FEED OFFLINE panel instead of stale content):
 *   market_bias.json           — Lens macro (daily 04:55 UTC)
 *   strategy_recommendation.json — regime read
 *   sentinel_data.json         — insider/market intel (3×/day)
 *   lens_validation.json       — two-tier verdicts: Blade + Edge
 *   victoria_validation.json   — two-tier verdicts: Jerry + Chad
 *
 * Layout: bias board as a flat instrument table (one row per pair, LED +
 * confidence bar), verdict rail across the fleet, sentinel signals feed.
 */
import { useHQData } from '../../hooks/useHQData'
import { CommandStatusBar, FeedAge, StaleGuard } from '../shared'

export default function IntelCommand() {
  const bias = useHQData('market-bias').data
  const strat = useHQData('strategy-recommendation').data
  const sentinel = useHQData('sentinel-data').data
  const lensVal = useHQData('lens-validation').data
  const vicVal = useHQData('victoria-validation').data

  const pairs: any[] = Array.isArray(bias?.pairs) ? bias.pairs : []
  const verdicts = fleetVerdicts(lensVal, vicVal)
  const signals: any[] = (sentinel?.watchlist_signals || sentinel?.top_discoveries || []).slice(0, 8)

  return (
    <div className="page-pad cmd-root">
      <CommandStatusBar />

      {/* ── macro bias board ── */}
      <section className="cmd-panel" style={{ marginBottom: 14 }}>
        <Head title="MACRO BIAS — LENS" right={<FeedAge iso={bias?.last_updated} label="market_bias" />} />
        <StaleGuard iso={bias?.last_updated} feedName="market_bias.json (Lens 04:55 UTC)">
          <table className="cmd-spec" style={{ width: '100%' }}>
            <tbody>
              {pairs.map((p, i) => (
                <tr key={i}>
                  <td style={{ width: 14 }}>
                    <span className={`cmd-led cmd-led-${p.bias === 'bullish' ? 'green' : p.bias === 'bearish' ? 'red' : 'amber'}`} />
                  </td>
                  <td className="mono" style={{ fontSize: 13, fontWeight: 600, width: 110 }}>{p.symbol}</td>
                  <td className="mono" style={{ fontSize: 11, width: 84, letterSpacing: '0.08em', color: p.bias === 'bullish' ? 'var(--green)' : p.bias === 'bearish' ? 'var(--red)' : 'var(--amber)' }}>
                    {String(p.bias).toUpperCase()}
                  </td>
                  <td style={{ width: 150 }}>
                    <div className="cmd-regime-bar" style={{ width: 130 }}>
                      <div className="cmd-regime-fill" style={{ width: `${p.confidence ?? 50}%` }} />
                    </div>
                  </td>
                  <td className="mono" style={{ fontSize: 11, width: 46, color: 'var(--text-dim)' }}>{p.confidence ?? '--'}%</td>
                  <td className="soft" style={{ fontSize: 11.5, color: 'var(--text-mute)', maxWidth: 0 }}>
                    <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.note}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {bias?.summary && (
            <div className="soft" style={{ fontSize: 12.5, color: 'var(--text-dim)', lineHeight: 1.55, marginTop: 12, borderTop: '1px solid var(--surface-border)', paddingTop: 12 }}>
              {bias.summary}
            </div>
          )}
        </StaleGuard>
      </section>

      {/* ── fleet verdict rail ── */}
      <section className="cmd-rail" style={{ marginBottom: 14 }}>
        {verdicts.map((v) => (
          <div key={v.agent} className="cmd-rail-cell">
            <div className="mono" style={{ fontSize: 9, letterSpacing: '0.16em', color: 'var(--text-mute)' }}>{v.agent.toUpperCase()}</div>
            <div className="mono cmd-rail-num" style={{ fontSize: 19, color: verdictColor(v.verdict) }}>{v.verdict}</div>
            <div className="mono" style={{ fontSize: 9.5, color: 'var(--text-dim)', marginTop: 3 }}>
              {v.n != null ? `${v.n} trades graded` : v.validator}
            </div>
          </div>
        ))}
      </section>

      {/* ── sentinel feed ── */}
      <section className="cmd-panel">
        <Head title="SENTINEL — INSIDER / MARKET INTEL" right={<FeedAge iso={sentinel?.last_updated} label="sentinel" />} />
        <StaleGuard iso={sentinel?.last_updated} feedName="sentinel_data.json (3×/day)">
          {signals.length === 0 ? (
            <div className="mono" style={{ fontSize: 11, color: 'var(--text-mute)' }}>
              NO ACTIVE SIGNALS — sentinel runs 08:00 / 14:00 / 20:00 UTC.
            </div>
          ) : (
            signals.map((s: any, i: number) => (
              <div key={i} className="cmd-feed-row">
                <span className="cmd-led cmd-led-accent" />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <span className="mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{s.symbol || s.ticker || '—'}</span>
                  <span className="soft" style={{ fontSize: 12, color: 'var(--text-dim)', marginLeft: 8 }}>
                    {s.headline || s.signal || s.reason || JSON.stringify(s).slice(0, 90)}
                  </span>
                </div>
              </div>
            ))
          )}
        </StaleGuard>
      </section>

      {/* regime footnote */}
      {strat?.regime && (
        <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-mute)', marginTop: 12, letterSpacing: '0.06em' }}>
          {'// '}REGIME: {String(strat.regime).toUpperCase()} <FeedAge iso={strat?.updated} />
        </div>
      )}
    </div>
  )
}

function Head({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
      <span className="mono" style={{ fontSize: 9.5, letterSpacing: '0.16em', color: 'var(--text-mute)' }}>{title}</span>
      {right}
    </div>
  )
}

function fleetVerdicts(lensVal: any, vicVal: any) {
  const out: { agent: string; verdict: string; n: number | null; validator: string }[] = []
  const lens = lensVal?.agent_reports || {}
  const vic = vicVal?.agent_reports || {}
  for (const [agent, r] of Object.entries<any>(lens)) {
    out.push({ agent, verdict: r?.verdict ?? 'UNKNOWN', n: r?.total_trades ?? null, validator: 'lens' })
  }
  for (const [agent, r] of Object.entries<any>(vic)) {
    // fleet rename: crisp → chad (2026-07-25). Report under the live name.
    out.push({ agent: agent === 'crisp' ? 'chad' : agent, verdict: r?.verdict ?? 'UNKNOWN', n: r?.total_trades ?? null, validator: 'victoria' })
  }
  return out
}

function verdictColor(v: string) {
  if (v === 'PASS') return 'var(--green)'
  if (v === 'FAIL') return 'var(--red)'
  if (v === 'MARGINAL') return 'var(--amber)'
  return 'var(--text-dim)'
}
