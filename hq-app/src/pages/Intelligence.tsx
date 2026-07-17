import GlassCard from '../components/GlassCard'
import { useHQData, fmtNum } from '../hooks/useHQData'

export default function Intelligence() {
  const bias = useHQData('market-bias').data
  const strat = useHQData('strategy-recommendation').data
  const morning = useHQData('morning-report').data

  const briefing: string = morning?.text || bias?.morning_report || bias?.summary || ''
  const news: any[] = Array.isArray(bias?.forex_news) ? bias.forex_news : []
  const instruments = strat?.instruments ? Object.entries(strat.instruments) : []
  const regimeName = strat?.regime ? cap(strat.regime) : null

  return (
    <div className="page-pad">
      {/* Lens briefing terminal */}
      <div className="mono-label" style={{ marginBottom: 12 }}>lens briefing</div>
      <div
        style={{
          background: '#050609',
          border: '0.5px solid rgba(212,168,67,0.18)',
          borderRadius: 14,
          padding: '20px 22px',
          marginBottom: 24,
          fontFamily: 'JetBrains Mono, monospace',
          fontSize: 13,
          lineHeight: 1.7,
          color: 'rgba(240,237,230,0.82)',
          maxHeight: 320,
          overflowY: 'auto',
        }}
      >
        <div style={{ color: 'var(--gold)', marginBottom: 10, fontSize: 11, letterSpacing: '0.06em' }}>
          jcf@hq:~/lens$ cat morning_report.md
        </div>
        {briefing ? (
          <span>{briefing}<span className="cursor-blink" /></span>
        ) : (
          <span style={{ color: 'var(--text-dim)' }}>// awaiting Lens briefing — next run 04:55 UTC<span className="cursor-blink" /></span>
        )}
      </div>

      {/* Instrument bias grid */}
      <div className="mono-label" style={{ marginBottom: 12 }}>instrument bias</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(220px,1fr))', gap: 14, marginBottom: 24 }}>
        {instruments.length === 0 && (
          <GlassCard hover={false}><span style={{ color: 'var(--text-dim)', fontSize: 13 }}>Awaiting Jarvis regime read.</span></GlassCard>
        )}
        {instruments.map(([sym, d]: any, i) => {
          const bias = String(d.bias || 'neutral').toLowerCase()
          const conf = Number(d.lens_confidence) || 50
          const badge = bias === 'bullish' ? 'green' : bias === 'bearish' ? 'red' : 'amber'
          const barColor = bias === 'bullish' ? 'var(--green)' : bias === 'bearish' ? 'var(--red)' : 'var(--amber)'
          return (
            <GlassCard key={sym} delay={i * 0.04}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="mono" style={{ fontWeight: 600, fontSize: 13 }}>{sym.replace('_', '/')}</span>
                <span className={`badge badge-${badge}`}>{bias.toUpperCase()}</span>
              </div>
              <div style={{ marginTop: 14 }}>
                <div className="mono-meta" style={{ marginBottom: 5 }}>confidence {conf.toFixed(0)}%</div>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${conf}%`, background: barColor }} /></div>
              </div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 14, display: 'flex', justifyContent: 'space-between' }}>
                <span>px {fmtNum(d.current_price)}</span>
                <span>ADR {fmtNum(d.adr, 0)}</span>
              </div>
              <div className="mono-meta" style={{ marginTop: 6 }}>regime · {cap(String(d.regime || '—'))}</div>
            </GlassCard>
          )
        })}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 18 }}>
        {/* News feed */}
        <div>
          <div className="mono-label" style={{ marginBottom: 12 }}>news feed</div>
          <GlassCard hover={false}>
            {news.length === 0 ? (
              <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>No news items in the latest Lens pull.</span>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
                {news.slice(0, 8).map((n, i) => (
                  <div key={i} style={{ display: 'flex', gap: 11, alignItems: 'flex-start', paddingBottom: 13, borderBottom: i < 7 ? '0.5px solid rgba(255,255,255,0.04)' : 'none' }}>
                    <span className={`badge badge-${String(n.impact).toLowerCase() === 'high' ? 'red' : String(n.impact).toLowerCase() === 'medium' ? 'amber' : 'mute'}`}>
                      {String(n.impact || 'low').toUpperCase()}
                    </span>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 13, lineHeight: 1.4 }}>{n.headline}</div>
                      <div className="mono-meta" style={{ marginTop: 3 }}>{n.source} · {n.time}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        </div>

        {/* Jarvis panel */}
        <div>
          <div className="mono-label" style={{ marginBottom: 12 }}>jarvis · regime</div>
          <GlassCard tint="blue" hover={false}>
            {regimeName ? (
              <>
                <div className="stat-num text-blue" style={{ fontSize: 24 }}>{regimeName}</div>
                <div className="bar-track" style={{ marginTop: 12 }}>
                  <div className="bar-fill" style={{ width: `${scoreOf(strat)}%`, background: 'var(--blue)' }} />
                </div>
                <div className="soft" style={{ fontSize: 13.5, color: 'var(--text-dim)', marginTop: 14, lineHeight: 1.55 }}>
                  {plainRegime(regimeName, scoreOf(strat))}
                </div>
                <div className="mono-meta" style={{ marginTop: 16, paddingTop: 12, borderTop: '0.5px solid var(--glass-border)' }}>
                  per-session: London leans with the number, NY confirms or fades it. — Jarvis
                </div>
              </>
            ) : (
              <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>Awaiting Jarvis regime read — next brief 06:00 UTC.</span>
            )}
          </GlassCard>
        </div>
      </div>
    </div>
  )
}

function cap(s: string) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s }
function scoreOf(strat: any): number {
  if (!strat?.instruments) return 44
  const vals = Object.values(strat.instruments) as any[]
  const conf = vals.map((v) => Number(v.lens_confidence) || 50)
  return Math.round(conf.reduce((a, b) => a + b, 0) / (conf.length || 1))
}
function plainRegime(name: string, score: number): string {
  const n = name.toLowerCase()
  if (n.includes('compress')) return `Compressed — ${score}/100. The market's coiled and range-bound. Wait for the break to show itself; don't guess the direction.`
  if (n.includes('volatil')) return `Volatile — ${score}/100. Whippy both ways. Cut size, widen stops, and be quick to take what it gives.`
  if (n.includes('trend')) return `Trending — ${score}/100. There's a real direction here. Lean with momentum instead of fading it.`
  if (n.includes('chop')) return `Choppy — ${score}/100. Not a trending day. Don't force anything — flat is fine.`
  return `${name} — ${score}/100. Read the tape before committing size.`
}
