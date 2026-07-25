import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import GlassCard from '../components/GlassCard'
import AgentAvatar from '../components/AgentAvatar'
import { ACTIVE_AGENTS, AGENT_PROFILES, type Agent } from '../data/agentConfig'

const stateBadge: Record<string, string> = { LIVE: 'badge-green', STANDBY: 'badge-amber', BUILDING: 'badge-purple' }
const stateColorVar: Record<string, string> = { LIVE: 'var(--green)', STANDBY: 'var(--amber)', BUILDING: 'var(--purple)' }

export default function Agents() {
  const [selected, setSelected] = useState<Agent | null>(null)

  return (
    <div className="page-pad">
      <div className="mono-label" style={{ marginBottom: 4 }}>the roster</div>
      <h1 className="head" style={{ fontSize: 32, fontWeight: 600, marginBottom: 20, letterSpacing: '0.01em' }}>Agents</h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16 }}>
        {ACTIVE_AGENTS.map((a, i) => (
          <AgentCard key={a.id} agent={a} delay={i * 0.04} onOpen={() => setSelected(a)} />
        ))}
      </div>

      <AnimatePresence>
        {selected && <AgentModal agent={selected} onClose={() => setSelected(null)} />}
      </AnimatePresence>
    </div>
  )
}

function AgentCard({ agent, delay, onOpen }: { agent: Agent; delay: number; onOpen: () => void }) {
  return (
    <GlassCard
      delay={delay}
      onClick={onOpen}
      style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', padding: 24, cursor: 'pointer' }}
    >
      <AgentAvatar agent={agent} size={80} />
      <div className="head" style={{ fontSize: 22, marginTop: 14 }}>{agent.name} {agent.emoji}</div>
      <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 3 }}>{agent.role}</div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <span className={`badge ${stateBadge[agent.state]}`}>{agent.state}</span>
        <span className="badge badge-mute">{agent.model}</span>
      </div>

      <div className="soft" style={{ fontSize: 13, fontStyle: 'italic', color: 'var(--text-dim)', marginTop: 12, lineHeight: 1.45, minHeight: 34 }}>
        “{AGENT_PROFILES[agent.id]?.motto || agent.voice}”
      </div>

      <div className="mono-meta" style={{ marginTop: 14 }}>Tap for profile →</div>
    </GlassCard>
  )
}

function AgentModal({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const nav = useNavigate()
  const profile = AGENT_PROFILES[agent.id]

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(4,5,9,0.72)', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
      }}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.94, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 10 }}
        transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
        onClick={(e) => e.stopPropagation()}
        className="glass"
        style={{ width: 440, maxWidth: '100%', maxHeight: '90vh', overflowY: 'auto', padding: 0, border: '1px solid var(--gold-border)', background: 'var(--surface-solid)' }}
      >
        {/* Close */}
        <button
          onClick={onClose}
          aria-label="Close"
          style={{ position: 'absolute', top: 14, right: 14, width: 30, height: 30, borderRadius: 9, fontSize: 16, color: 'var(--text-dim)', background: 'var(--input-bg)', border: '0.5px solid var(--glass-border)', zIndex: 2 }}
        >
          ✕
        </button>

        {/* Header */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', padding: '34px 28px 20px', background: 'linear-gradient(180deg, rgba(212,168,67,0.10), transparent)' }}>
          <div style={{ borderRadius: '50%', padding: 4, background: 'radial-gradient(circle, rgba(212,168,67,0.22), transparent 70%)', boxShadow: '0 0 30px -4px rgba(212,168,67,0.5)' }}>
            <div style={{ borderRadius: '50%', border: '2px solid var(--gold-border)' }}>
              <AgentAvatar agent={agent} size={110} />
            </div>
          </div>
          <div className="head" style={{ fontSize: 28, marginTop: 16 }}>{agent.name} {agent.emoji}</div>
          <div className="soft" style={{ fontSize: 14, fontStyle: 'italic', color: 'var(--gold)', marginTop: 8, lineHeight: 1.4 }}>
            “{profile?.motto || agent.voice}”
          </div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 10 }}>{agent.role}</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <span className={`badge ${stateBadge[agent.state]}`}>{agent.state}</span>
            <span className="badge badge-mute">{agent.model}</span>
          </div>
        </div>

        {/* Body */}
        <div style={{ padding: '4px 28px 26px' }}>
          <div style={{ borderTop: '0.5px solid var(--glass-border)', paddingTop: 16 }}>
            <div className="mono-label" style={{ marginBottom: 8 }}>connected to</div>
            {agent.connectedTo.length ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                {agent.connectedTo.map((c, i) => (
                  <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <span className="badge badge-gold" style={{ textTransform: 'none' }}>{c}</span>
                    {i < agent.connectedTo.length - 1 && <span style={{ color: 'var(--text-mute)' }}>→</span>}
                  </span>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>No active wires yet.</div>
            )}
          </div>

          <div style={{ marginTop: 18 }}>
            <div className="mono-label" style={{ marginBottom: 8 }}>personality</div>
            <div className="soft" style={{ fontSize: 14, color: 'var(--text-dim)', lineHeight: 1.65 }}>
              {profile?.bio || agent.voice}
            </div>
          </div>

          <button
            onClick={() => { nav(`/hub?agent=${agent.id}`); onClose() }}
            className="glass-hover"
            style={{
              marginTop: 22, width: '100%', padding: '11px', borderRadius: 11, fontSize: 14, fontWeight: 600,
              color: '#07080f', background: 'linear-gradient(90deg,#d4a843,#f0c060)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              boxShadow: `0 0 18px -4px ${stateColorVar[agent.state] || 'rgba(212,168,67,0.5)'}`,
            }}
          >
            Message {agent.name} →
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}
