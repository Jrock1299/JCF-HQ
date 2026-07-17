import { useNavigate } from 'react-router-dom'
import GlassCard from '../components/GlassCard'
import AgentAvatar from '../components/AgentAvatar'
import { AGENTS, type Agent } from '../data/agentConfig'

const stateBadge: Record<string, string> = { LIVE: 'badge-green', STANDBY: 'badge-amber', BUILDING: 'badge-purple' }

export default function Agents() {
  const nav = useNavigate()
  return (
    <div className="page-pad">
      <div className="mono-label" style={{ marginBottom: 4 }}>the roster</div>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 20 }}>Agents</h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16 }}>
        {AGENTS.map((a, i) => (
          <AgentCard key={a.id} agent={a} delay={i * 0.04} onMessage={() => nav(`/hub?agent=${a.id}`)} />
        ))}
      </div>
    </div>
  )
}

function AgentCard({ agent, delay, onMessage }: { agent: Agent; delay: number; onMessage: () => void }) {
  return (
    <GlassCard delay={delay} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', padding: 24 }}>
      <div style={{ position: 'relative' }}>
        <AgentAvatar agent={agent} size={80} />
      </div>
      <div style={{ fontSize: 17, fontWeight: 600, marginTop: 14 }}>{agent.name} {agent.emoji}</div>
      <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 3 }}>{agent.role}</div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <span className={`badge ${stateBadge[agent.state]}`}>{agent.state}</span>
        <span className="badge badge-mute">{agent.model}</span>
      </div>

      <div className="mono-meta" style={{ marginTop: 14, minHeight: 14 }}>
        {agent.connectedTo.length ? `Connected to: ${agent.connectedTo.join(' → ')}` : 'No active wires yet'}
      </div>

      <div style={{ fontSize: 12.5, fontStyle: 'italic', color: 'var(--text-dim)', marginTop: 10, lineHeight: 1.45, minHeight: 34 }}>
        {agent.voice}
      </div>

      <button
        onClick={onMessage}
        className="glass-hover"
        style={{
          marginTop: 16, width: '100%', padding: '9px', borderRadius: 10, fontSize: 13, fontWeight: 500,
          color: 'var(--gold-hi)', background: 'rgba(212,168,67,0.10)', border: '0.5px solid var(--gold-border)',
        }}
      >
        Message →
      </button>
    </GlassCard>
  )
}
