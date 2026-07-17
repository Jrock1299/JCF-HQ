import { motion } from 'framer-motion'
import type { Agent } from '../data/agentConfig'
import AgentAvatar from './AgentAvatar'

interface Props {
  from: 'agent' | 'jase'
  text: string
  time?: string
  agent?: Agent
  showMeta?: boolean
}

// Agent messages align left (portrait + gold name + glass bubble).
// Jase messages align right (glass-gold bubble). Timestamp below, mono.
export default function ChatBubble({ from, text, time, agent, showMeta = true }: Props) {
  const isAgent = from === 'agent'

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      style={{
        display: 'flex',
        gap: 10,
        flexDirection: isAgent ? 'row' : 'row-reverse',
        alignItems: 'flex-end',
        marginBottom: 14,
      }}
    >
      {isAgent && agent && <AgentAvatar agent={agent} size={30} />}
      <div style={{ maxWidth: '68%', minWidth: 0 }}>
        {isAgent && agent && showMeta && (
          <div className="mono" style={{ fontSize: 10, color: 'var(--gold)', marginBottom: 4, marginLeft: 4, letterSpacing: '0.03em' }}>
            {agent.name}
          </div>
        )}
        <div
          className={isAgent ? 'glass' : 'glass-gold'}
          style={{
            padding: '10px 14px',
            borderRadius: isAgent ? '4px 14px 14px 14px' : '14px 4px 14px 14px',
            fontSize: 14,
            lineHeight: 1.5,
            color: 'var(--text-hi)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
          }}
        >
          {text}
        </div>
        {time && showMeta && (
          <div
            className="mono-meta"
            style={{ marginTop: 4, textAlign: isAgent ? 'left' : 'right', marginInline: 4 }}
          >
            {time}
          </div>
        )}
      </div>
    </motion.div>
  )
}
