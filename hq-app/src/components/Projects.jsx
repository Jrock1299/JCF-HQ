/**
 * Projects — JCF digital products, Etsy store, and build pipeline
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { useIsMobile } from '../hooks/useIsMobile.js'

const POLL_MS = 120_000

function relTime(ts) {
  if (!ts) return '—'
  try {
    const d = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
    if (d < 60)    return d + 's ago'
    if (d < 3600)  return Math.floor(d / 60) + 'm ago'
    if (d < 86400) return Math.floor(d / 3600) + 'h ago'
    return Math.floor(d / 86400) + 'd ago'
  } catch { return '—' }
}

// Score color: >=8 green, 6-7 gold, <6 gray
function scoreColor(s) {
  const n = parseFloat(s) || 0
  if (n >= 8)  return '#4ade80'
  if (n >= 6)  return '#c9a84c'
  return 'rgba(255,255,255,0.4)'
}

export default function Projects({ demoMode, isActive = true }) {
  const isMobile = useIsMobile()
  const [forge,   setForge]   = useState(null)
  const [lucy,    setLucy]    = useState(null)
  const [loading, setLoading] = useState(true)
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const [f, l] = await Promise.allSettled([
        fetch('/hq/forge-builds').then(r => r.ok ? r.json() : null),
        fetch('/hq/lucy-research').then(r => r.ok ? r.json() : null),
      ])
      if (f.status === 'fulfilled') setForge(f.value)
      if (l.status === 'fulfilled') setLucy(l.value)
    } catch (e) { console.error('[Projects]', e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!isActive) { clearInterval(timer.current); return }
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [isActive, load])

  const builds = forge?.builds || []
  const specs  = forge?.specs  || []
  const niches = lucy?.niches  || []

  // Latest approved build per product_name
  const approvedByProduct = {}
  for (const b of builds) {
    if ((b.review_status || '').toUpperCase() !== 'APPROVED') continue
    const key = b.product_name
    if (!approvedByProduct[key] || new Date(b.timestamp) > new Date(approvedByProduct[key].timestamp)) {
      approvedByProduct[key] = b
    }
  }
  const approved = Object.values(approvedByProduct)
  const approvedNames = new Set(approved.map(b => b.product_name))
  const pipeline = specs.filter(s => !approvedNames.has(s.name))

  const totalForgeCost = builds.reduce((s, b) => s + (parseFloat(b.total_cost || b.build_cost) || 0), 0)

  return (
    <div>
      <h1 className="page-title">Projects</h1>

      {/* 1 ── Etsy Store: JCF7Studio ─────────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Etsy Store</h3><div className="section-line" /></div>
      <div className="glass" style={{
        border: '1px solid rgba(201,168,76,0.2)',
        borderTop: '2px solid var(--gold)',
        padding: isMobile ? '20px 18px' : '24px 28px',
        marginBottom: 14,
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 14, marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 9, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>Store</div>
            <div style={{ fontFamily: '"Playfair Display",serif', fontSize: isMobile ? 22 : 28, color: 'var(--gold)', lineHeight: 1 }}>JCF7Studio</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>Digital products · templates · creator tooling</div>
          </div>
          <a href="https://www.etsy.com/shop/JCF7Studio" target="_blank" rel="noreferrer"
             style={{ fontSize: 10, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--gold)', textDecoration: 'none', padding: '6px 12px', border: '1px solid rgba(201,168,76,0.3)', borderRadius: 6 }}>
            Open store ↗
          </a>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(4,1fr)', gap: 14, borderTop: '1px solid rgba(255,255,255,0.04)', paddingTop: 14 }}>
          {[
            { label: 'Approved Products', val: String(approved.length),             color: 'var(--green)' },
            { label: 'In Pipeline',       val: String(pipeline.length),             color: 'var(--gold)' },
            { label: 'Niches Researched', val: String(niches.length),               color: '#c9a84c' },
            { label: 'Forge Build Cost',  val: '$' + totalForgeCost.toFixed(2),     color: 'var(--text-primary)' },
          ].map(s => (
            <div key={s.label}>
              <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>{s.label}</div>
              <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 16, color: s.color }}>{s.val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 2 ── Active Products ───────────────────────────────────────── */}
      <div className="section-head">
        <div className="section-line" /><h3>Active Products</h3><div className="section-line" />
        <span className="pill pill-gray ml-2 shrink-0">{approved.length}</span>
      </div>
      {loading ? <Skeleton rows={2} /> : approved.length === 0 ? (
        <EmptyCard msg="No approved Forge builds yet — pipeline still in review." />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 12, marginBottom: 14 }}>
          {approved.map(b => {
            const spec = specs.find(s => s.name === b.product_name)
            return (
              <div key={b.build_id} className="glass" style={{ border: '1px solid rgba(74,222,128,0.18)', padding: '14px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: 6 }}>
                  <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 16, color: 'var(--text-primary)' }}>
                    {spec?.display_name || b.product_name}
                  </div>
                  <span style={{ fontSize: 8, padding: '2px 7px', borderRadius: 20, background: 'rgba(74,222,128,0.15)', color: 'var(--green)', border: '1px solid rgba(74,222,128,0.35)', letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700, flexShrink: 0 }}>
                    Approved
                  </span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 10 }}>
                  {spec?.description || '—'}
                </div>
                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 10 }}>
                  <span style={{ color: 'var(--text-muted)' }}>Theme: <span style={{ color: 'var(--text-dim)' }}>{b.theme || '—'}</span></span>
                  <span style={{ color: 'var(--text-muted)' }}>Score: <span style={{ color: 'var(--green)', fontFamily: '"IBM Plex Mono",monospace' }}>{b.review_score ?? '—'}/10</span></span>
                  <span style={{ color: 'var(--text-muted)' }}>Built: <span style={{ color: 'var(--text-dim)' }}>{relTime(b.timestamp)}</span></span>
                  <span style={{ color: 'var(--text-muted)' }}>Cost: <span style={{ color: 'var(--text-dim)', fontFamily: '"IBM Plex Mono",monospace' }}>${(b.total_cost || b.build_cost || 0).toFixed(3)}</span></span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* 3 ── Product Pipeline ──────────────────────────────────────── */}
      <div className="section-head">
        <div className="section-line" /><h3>Product Pipeline</h3><div className="section-line" />
        <span className="pill pill-gray ml-2 shrink-0">{pipeline.length}</span>
      </div>
      {loading ? <Skeleton rows={2} /> : pipeline.length === 0 ? (
        <EmptyCard msg="Pipeline empty — all specs have approved builds." />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 12, marginBottom: 14 }}>
          {pipeline.map(s => (
            <div key={s.name} className="glass" style={{ border: '1px solid rgba(251,191,36,0.18)', padding: '14px 16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: 6 }}>
                <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 16, color: 'var(--text-primary)' }}>
                  {s.display_name || s.name}
                </div>
                <span style={{ fontSize: 8, padding: '2px 7px', borderRadius: 20, background: 'rgba(251,191,36,0.15)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.35)', letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700, flexShrink: 0 }}>
                  In Queue
                </span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 10 }}>
                {s.description || '—'}
              </div>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 10 }}>
                <span style={{ color: 'var(--text-muted)' }}>Type: <span style={{ color: 'var(--text-dim)' }}>{s.type || '—'}</span></span>
                {Array.isArray(s.themes) && s.themes.length > 0 && (
                  <span style={{ color: 'var(--text-muted)' }}>Themes: <span style={{ color: 'var(--text-dim)' }}>{s.themes.length}</span></span>
                )}
                {Array.isArray(s.features) && (
                  <span style={{ color: 'var(--text-muted)' }}>Features: <span style={{ color: 'var(--text-dim)' }}>{s.features.length}</span></span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 4 ── Lucy's Niches ─────────────────────────────────────────── */}
      <div className="section-head">
        <div className="section-line" /><h3>Lucy's Niches</h3><div className="section-line" />
        <span className="pill pill-gray ml-2 shrink-0">{niches.length}</span>
      </div>
      {loading ? <Skeleton rows={3} /> : niches.length === 0 ? (
        <EmptyCard msg="Lucy hasn't published research yet." />
      ) : (
        <div style={{ marginBottom: 14 }}>
          {lucy?.research_date && (
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
              Research: <span style={{ color: 'var(--text-dim)' }}>{lucy.research_date}</span>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 10 }}>
            {niches.map((n, i) => {
              const score = n.overall_score ?? n.score ?? n.opportunity_score
              const col   = scoreColor(score)
              return (
                <div key={i} className="glass" style={{ border: `1px solid ${col}30`, padding: '14px 16px' }}>
                  <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    {score != null && (
                      <div style={{ flexShrink: 0, textAlign: 'center', minWidth: 52 }}>
                        <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 26, color: col, lineHeight: 1 }}>{parseFloat(score).toFixed(1)}</div>
                        <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginTop: 2 }}>Score</div>
                      </div>
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 15, color: 'var(--text-primary)', marginBottom: 4 }}>
                        {n.name}
                      </div>
                      {n.description && (
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 6 }}>
                          {n.description}
                        </div>
                      )}
                      {n.target_buyer && (
                        <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 4 }}>
                          <span style={{ color: 'var(--text-muted)', letterSpacing: 1, textTransform: 'uppercase', fontSize: 9, marginRight: 6 }}>Buyer:</span>
                          {n.target_buyer}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 5 ── Future Projects ───────────────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Future Projects</h3><div className="section-line" /></div>
      <div className="glass" style={{ padding: '20px 22px', marginBottom: 24 }}>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 14 }}>
          {[
            { name: 'JCF Capital Fund',    desc: 'External capital structure once paper P&L trades reach sustained PASS.',      tag: 'H2 2026' },
            { name: 'Creator Subscription Suite', desc: 'Bundle Forge + Lucy pipeline into a recurring SaaS for creators.',    tag: 'Exploratory' },
            { name: 'Open-source Gateway',  desc: 'Publish the Huncho orchestrator as an open OSS multi-agent framework.',     tag: 'Long-term' },
          ].map(p => (
            <div key={p.name} style={{ borderLeft: '2px solid rgba(201,168,76,0.3)', paddingLeft: 12 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4, flexWrap: 'wrap' }}>
                <span style={{ fontFamily: '"Playfair Display",serif', fontSize: 14, color: 'var(--text-primary)' }}>{p.name}</span>
                <span style={{ fontSize: 8, padding: '1px 6px', borderRadius: 20, background: 'rgba(201,168,76,0.12)', color: 'var(--gold)', border: '1px solid rgba(201,168,76,0.3)', letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700 }}>
                  {p.tag}
                </span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{p.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Skeleton({ rows = 2 }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
      {Array.from({ length: rows * 2 }).map((_, i) => (
        <div key={i} className="glass animate-pulse-slow" style={{ height: 96, background: 'rgba(255,255,255,0.03)' }} />
      ))}
    </div>
  )
}

function EmptyCard({ msg }) {
  return (
    <div className="glass" style={{ padding: '18px 22px', marginBottom: 14 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>{msg}</div>
    </div>
  )
}
