/**
 * Basketball — player hero card, season stats, schedule, training goals, career history
 * Data: /bball_stats.json → ppg/rpg/apg/fg_pct/tp_pct/games/team
 *       GET /hq/data → basketball{} → schedule[], goals[], career[], contract{}
 *       POST /hq/basketball → update stored data
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { getStoredData, setBasketball, getBballStats } from '../api/client.js'

const POLL_MS = 60_000

export default function Basketball({ demoMode, isActive = true }) {
  const [stats,   setStats]   = useState(null)
  const [stored,  setStored]  = useState(null)
  const [loading, setLoading] = useState(true)
  const [modal,   setModal]   = useState(null) // 'hero' | 'contract' | 'schedule' | 'goals' | 'career'
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const [bb, st] = await Promise.allSettled([getBballStats(), getStoredData()])
      if (bb.status === 'fulfilled') setStats(bb.value)
      if (st.status === 'fulfilled') setStored(st.value)
    } catch (e) { console.error('[Basketball]', e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!isActive) { clearInterval(timer.current); return }
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [isActive, load])

  async function save(patch) {
    const current = stored?.basketball ?? {}
    await setBasketball({ ...current, ...patch })
    setModal(null); load()
  }

  const bb = stored?.basketball ?? {}
  const jersey   = bb.jersey   ?? stats?.jersey   ?? '1'
  const position = bb.position ?? stats?.position ?? 'Guard'
  const team     = bb.team     ?? stats?.team     ?? '— Enter team name —'
  const record   = bb.record   ?? stats?.record   ?? '— — —'
  const standing = bb.standing ?? stats?.standing ?? 'Enter record'
  const season   = bb.season   ?? '2025-26'
  const contract = bb.contract ?? {}

  const ppg  = stats?.ppg  ?? bb.ppg  ?? '-'
  const apg  = stats?.apg  ?? bb.apg  ?? '-'
  const rpg  = stats?.rpg  ?? bb.rpg  ?? '-'
  const gp   = stats?.games ?? bb.games ?? '-'
  const fgRaw = parseFloat(stats?.fg_pct ?? bb.fg_pct ?? 0)
  const tpRaw = parseFloat(stats?.tp_pct ?? bb.tp_pct ?? 0)
  const fgp  = fgRaw ? ((fgRaw > 1 ? fgRaw : fgRaw * 100).toFixed(1) + '%') : '-'
  const tpp  = tpRaw ? ((tpRaw > 1 ? tpRaw : tpRaw * 100).toFixed(1) + '%') : '-'

  const schedule = bb.schedule ?? []
  const goals    = bb.goals    ?? [{}, {}, {}]
  const career   = bb.career   ?? []

  return (
    <div>
      <h1 className="page-title">Basketball</h1>

      {/* ── Hero Card ────────────────────────────────────────────────── */}
      <div className="glass" style={{ border: '1px solid rgba(201,168,76,0.2)', display: 'grid', gridTemplateColumns: '220px 1fr', minHeight: 350, marginBottom: 14, overflow: 'hidden' }}>
        {/* Image column */}
        <div style={{ position: 'relative', overflow: 'hidden', background: '#080e1e' }}>
          <img src="/jase-basketball.png" alt="Jase" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top center' }} />
          {/* Giant jersey number watermark */}
          <div style={{ position: 'absolute', bottom: -15, left: -8, fontFamily: '"Playfair Display",serif', fontSize: 160, fontWeight: 700, color: 'rgba(201,168,76,0.05)', lineHeight: 1, pointerEvents: 'none', zIndex: 1 }}>
            {jersey}
          </div>
          <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(90deg,transparent 55%,rgba(7,12,26,0.95) 100%),linear-gradient(0deg,rgba(7,12,26,0.3) 0%,transparent 40%)' }} />
        </div>

        {/* Info column */}
        <div style={{ padding: '26px 28px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            {/* Name + edit */}
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 18 }}>
              <div>
                <div style={{ fontSize: 9, letterSpacing: 4, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 5 }}>Current Team · {season} Season</div>
                <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 34, fontWeight: 700, marginBottom: 8 }}>Jase</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span className="pill pill-gold">#{jersey}</span>
                  <span className="pill pill-blue">{position}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{team}</span>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }}>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 8, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Season Record</div>
                  <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 28, fontWeight: 700 }}>{loading ? '—' : record}</div>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2 }}>{standing}</div>
                </div>
                <button className="edit-btn" onClick={() => setModal('hero')}>✏ Edit Info</button>
              </div>
            </div>

            {/* 6 stat blocks */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)' }}>
              {[
                { label: 'PPG', val: ppg, color: 'var(--gold)' },
                { label: 'APG', val: apg },
                { label: 'RPG', val: rpg },
                { label: 'FG%', val: fgp },
                { label: '3P%', val: tpp },
                { label: 'GP',  val: gp  },
              ].map(({ label, val, color }) => (
                <div key={label} style={{ padding: '12px 14px', borderRight: '1px solid rgba(255,255,255,0.04)' }}>
                  <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>{label}</div>
                  {loading
                    ? <div className="animate-pulse-slow" style={{ height: 28, width: 40, background: 'rgba(255,255,255,0.04)', borderRadius: 4 }} />
                    : <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 26, fontWeight: 700, color: color || 'var(--text-primary)' }}>{val}</div>}
                </div>
              ))}
            </div>
          </div>

          {/* Contract bar */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderRadius: 8, background: 'rgba(201,168,76,0.04)', border: '1px solid rgba(201,168,76,0.12)', marginTop: 14 }}>
            <div style={{ display: 'flex', gap: 28 }}>
              <CInfo label="Season"        val={contract.season ?? season} />
              <CInfo label="Compensation"  val={contract.comp ?? '$—'} />
              <CInfo label="Contract Type" val={contract.type ?? '—'} />
              <CInfo label="Status"        val="Active" color="var(--green)" />
            </div>
            <button className="edit-btn" onClick={() => setModal('contract')}>✏ Edit Contract</button>
          </div>
        </div>
      </div>

      {/* ── Schedule ─────────────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Schedule</h3><div className="section-line" /></div>
      <div className="glass" style={{ padding: '20px 24px', marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18 }}>{season} Game Log</div>
          <button className="edit-btn" onClick={() => setModal('schedule')}>✏ Edit Schedule</button>
        </div>
        {!schedule.length
          ? <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Click Edit Schedule to add your games.</div>
          : (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr 80px 70px 70px', gap: 8, padding: '4px 0 8px', fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                {['Date', 'Opponent', 'Result', 'Score', 'PTS'].map(h => <span key={h}>{h}</span>)}
              </div>
              {schedule.map((g, i) => {
                const won = (g.result || '').toUpperCase() === 'W'
                const lost = (g.result || '').toUpperCase() === 'L'
                return (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '80px 1fr 80px 70px 70px', gap: 8, padding: '9px 0', fontSize: 11, borderBottom: '1px solid rgba(255,255,255,0.025)', alignItems: 'center' }}>
                    <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--text-muted)' }}>{g.date || '—'}</span>
                    <span style={{ color: 'var(--text-dim)' }}>{g.opponent || '—'}</span>
                    <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, fontWeight: 600, color: won ? 'var(--green)' : lost ? 'var(--red)' : 'var(--text-muted)' }}>{g.result || '—'}</span>
                    <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10 }}>{g.score || '—'}</span>
                    <span style={{ fontFamily: '"Playfair Display",serif', fontSize: 16, color: 'var(--gold)' }}>{g.pts ?? '—'}</span>
                  </div>
                )
              })}
            </>
          )
        }
      </div>

      {/* ── Training Goals ────────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Training Goals</h3><div className="section-line" /></div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginBottom: 8 }}>
        {[0, 1, 2].map(i => {
          const g = goals[i] ?? {}
          const pct = parseFloat(g.pct || 0)
          return (
            <div key={i} className="glass" style={{ padding: '16px 18px' }}>
              <div style={{ fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>Goal {i + 1}</div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 10 }}>{g.text || '— Add goal —'}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ flex: 1, height: 3, background: 'rgba(255,255,255,0.05)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${pct}%`, background: 'linear-gradient(90deg,var(--gold),var(--gold-light))', boxShadow: '0 0 8px rgba(201,168,76,0.5)' }} />
                </div>
                <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--gold)' }}>{pct}%</span>
              </div>
            </div>
          )
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 14 }}>
        <button className="edit-btn" onClick={() => setModal('goals')}>✏ Edit Goals</button>
      </div>

      {/* ── Career History ────────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line" /><h3>Career History</h3><div className="section-line" /></div>
      <div className="glass" style={{ padding: '20px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ fontFamily: '"Playfair Display",serif', fontSize: 18 }}>Previous Teams</div>
          <button className="edit-btn" onClick={() => setModal('career')}>✏ Edit History</button>
        </div>
        {!career.length
          ? <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Click Edit History to add your previous teams.</div>
          : career.map((c, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '9px 0', borderBottom: '1px solid rgba(255,255,255,0.04)', fontSize: 11 }}>
              <div>
                <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{c.team || '—'}</div>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2 }}>{c.seasons || ''}</div>
              </div>
              <div style={{ textAlign: 'right', fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, color: 'var(--text-muted)' }}>
                {c.stats || ''}
              </div>
            </div>
          ))
        }
      </div>

      {/* ── Modals ───────────────────────────────────────────────────── */}
      {modal === 'hero'     && <HeroEditModal     data={bb} onSave={d => save(d)} onClose={() => setModal(null)} />}
      {modal === 'contract' && <ContractEditModal data={contract} onSave={d => save({ contract: d })} onClose={() => setModal(null)} />}
      {modal === 'schedule' && <ScheduleEditModal data={schedule} onSave={d => save({ schedule: d })} onClose={() => setModal(null)} />}
      {modal === 'goals'    && <GoalsEditModal    data={goals}    onSave={d => save({ goals: d })}    onClose={() => setModal(null)} />}
      {modal === 'career'   && <CareerEditModal   data={career}   onSave={d => save({ career: d })}   onClose={() => setModal(null)} />}
    </div>
  )
}

function CInfo({ label, val, color = 'var(--gold)' }) {
  return (
    <div>
      <div style={{ fontSize: 8, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>
      <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 13, color }}>{val}</div>
    </div>
  )
}

function ModalWrap({ title, onClose, children }) {
  return (
    <div className="modal-overlay open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box">
        <button onClick={onClose} style={{ position: 'absolute', top: 14, right: 16, fontSize: 16, background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>✕</button>
        <h2 className="modal-title">{title}</h2>
        {children}
      </div>
    </div>
  )
}

function ModalBtns({ onClose, onSave }) {
  return (
    <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
      <button className="mbtn cancel" onClick={onClose}>Cancel</button>
      <button className="mbtn save"   onClick={onSave}>Save</button>
    </div>
  )
}

function HeroEditModal({ data, onSave, onClose }) {
  const [f, setF] = useState({ jersey: data.jersey ?? '1', position: data.position ?? 'Guard', team: data.team ?? '', record: data.record ?? '', standing: data.standing ?? '' })
  const s = (k, v) => setF(x => ({ ...x, [k]: v }))
  return (
    <ModalWrap title="Edit Player Info" onClose={onClose}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div className="mf"><label>Jersey #</label><input value={f.jersey}   onChange={e => s('jersey', e.target.value)} /></div>
        <div className="mf"><label>Position</label><input value={f.position} onChange={e => s('position', e.target.value)} /></div>
        <div className="mf"><label>Team</label><input value={f.team}         onChange={e => s('team', e.target.value)} /></div>
        <div className="mf"><label>Season</label><input value={f.season ?? '2025-26'} onChange={e => s('season', e.target.value)} /></div>
        <div className="mf"><label>Record (e.g. 10-5)</label><input value={f.record}   onChange={e => s('record', e.target.value)} /></div>
        <div className="mf"><label>Standing</label><input value={f.standing}  onChange={e => s('standing', e.target.value)} /></div>
      </div>
      <ModalBtns onClose={onClose} onSave={() => onSave(f)} />
    </ModalWrap>
  )
}

function ContractEditModal({ data, onSave, onClose }) {
  const [f, setF] = useState({ season: data.season ?? '2025-26', comp: data.comp ?? '', type: data.type ?? '' })
  const s = (k, v) => setF(x => ({ ...x, [k]: v }))
  return (
    <ModalWrap title="Edit Contract" onClose={onClose}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div className="mf"><label>Season</label><input value={f.season} onChange={e => s('season', e.target.value)} /></div>
        <div className="mf"><label>Compensation</label><input value={f.comp} onChange={e => s('comp', e.target.value)} placeholder="$0" /></div>
        <div className="mf"><label>Contract Type</label><input value={f.type} onChange={e => s('type', e.target.value)} /></div>
      </div>
      <ModalBtns onClose={onClose} onSave={() => onSave(f)} />
    </ModalWrap>
  )
}

function ScheduleEditModal({ data, onSave, onClose }) {
  const [rows, setRows] = useState(data.length ? data : [{ date: '', opponent: '', result: '', score: '', pts: '' }])
  const setRow = (i, k, v) => setRows(r => r.map((x, j) => j === i ? { ...x, [k]: v } : x))
  const addRow = () => setRows(r => [...r, { date: '', opponent: '', result: '', score: '', pts: '' }])
  const delRow = i => setRows(r => r.filter((_, j) => j !== i))
  return (
    <ModalWrap title="Edit Schedule" onClose={onClose}>
      <div style={{ maxHeight: 320, overflowY: 'auto', marginBottom: 10 }}>
        {rows.map((r, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '80px 1fr 55px 70px 55px 30px', gap: 6, marginBottom: 6 }}>
            <input className="mf" style={{ margin: 0, padding: '6px 8px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, color: 'var(--text-primary)', fontSize: 11 }} value={r.date}     onChange={e => setRow(i, 'date', e.target.value)}     placeholder="Date" />
            <input className="mf" style={{ margin: 0, padding: '6px 8px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, color: 'var(--text-primary)', fontSize: 11 }} value={r.opponent} onChange={e => setRow(i, 'opponent', e.target.value)} placeholder="Opponent" />
            <input className="mf" style={{ margin: 0, padding: '6px 8px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, color: 'var(--text-primary)', fontSize: 11 }} value={r.result}   onChange={e => setRow(i, 'result', e.target.value)}   placeholder="W/L" />
            <input className="mf" style={{ margin: 0, padding: '6px 8px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, color: 'var(--text-primary)', fontSize: 11 }} value={r.score}    onChange={e => setRow(i, 'score', e.target.value)}    placeholder="Score" />
            <input className="mf" style={{ margin: 0, padding: '6px 8px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, color: 'var(--text-primary)', fontSize: 11 }} value={r.pts}      onChange={e => setRow(i, 'pts', e.target.value)}      placeholder="PTS" />
            <button onClick={() => delRow(i)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 14 }}>✕</button>
          </div>
        ))}
      </div>
      <button className="edit-btn" onClick={addRow}>+ Add Game</button>
      <ModalBtns onClose={onClose} onSave={() => onSave(rows)} />
    </ModalWrap>
  )
}

function GoalsEditModal({ data, onSave, onClose }) {
  const [rows, setRows] = useState([
    { text: data[0]?.text ?? '', pct: data[0]?.pct ?? 0 },
    { text: data[1]?.text ?? '', pct: data[1]?.pct ?? 0 },
    { text: data[2]?.text ?? '', pct: data[2]?.pct ?? 0 },
  ])
  const setRow = (i, k, v) => setRows(r => r.map((x, j) => j === i ? { ...x, [k]: v } : x))
  return (
    <ModalWrap title="Edit Training Goals" onClose={onClose}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 80px', gap: 10, marginBottom: 8 }}>
          <div className="mf" style={{ margin: 0 }}><label>Goal {i + 1}</label><input value={r.text} onChange={e => setRow(i, 'text', e.target.value)} placeholder="Goal description" /></div>
          <div className="mf" style={{ margin: 0 }}><label>% Done</label><input type="number" min="0" max="100" value={r.pct} onChange={e => setRow(i, 'pct', e.target.value)} /></div>
        </div>
      ))}
      <ModalBtns onClose={onClose} onSave={() => onSave(rows)} />
    </ModalWrap>
  )
}

function CareerEditModal({ data, onSave, onClose }) {
  const [rows, setRows] = useState(data.length ? data : [{ team: '', seasons: '', stats: '' }])
  const setRow = (i, k, v) => setRows(r => r.map((x, j) => j === i ? { ...x, [k]: v } : x))
  const addRow = () => setRows(r => [...r, { team: '', seasons: '', stats: '' }])
  const delRow = i => setRows(r => r.filter((_, j) => j !== i))
  return (
    <ModalWrap title="Edit Career History" onClose={onClose}>
      <div style={{ maxHeight: 320, overflowY: 'auto', marginBottom: 10 }}>
        {rows.map((r, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 30px', gap: 6, marginBottom: 6 }}>
            {['team', 'seasons', 'stats'].map(k => (
              <input key={k} style={{ padding: '6px 8px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, color: 'var(--text-primary)', fontSize: 11 }} value={r[k]} onChange={e => setRow(i, k, e.target.value)} placeholder={k.charAt(0).toUpperCase() + k.slice(1)} />
            ))}
            <button onClick={() => delRow(i)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 14 }}>✕</button>
          </div>
        ))}
      </div>
      <button className="edit-btn" onClick={addRow}>+ Add Team</button>
      <ModalBtns onClose={onClose} onSave={() => onSave(rows)} />
    </ModalWrap>
  )
}
