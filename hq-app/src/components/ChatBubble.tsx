import { motion } from 'framer-motion'
import type { Agent } from '../data/agentConfig'
import AgentAvatar from './AgentAvatar'

export const REACTIONS = ['👍', '❤️', '😂', '🔥', '👀', '✅'] as const

interface Props {
  from: 'agent' | 'jase'
  text: string
  time?: string
  agent?: Agent
  showMeta?: boolean
  showName?: boolean
  reactions?: string[]
  showPicker?: boolean
  onOpenPicker?: () => void
  onPick?: (emoji: string) => void
}

// Agent messages align left (portrait + gold name + glass bubble).
// Jase messages align right (glass-gold bubble). Double-click any bubble to
// open the reaction picker; chosen emoji shows as a pill on the bubble corner.
export default function ChatBubble({
  from, text, time, agent, showMeta = true, showName = true,
  reactions = [], showPicker = false, onOpenPicker, onPick,
}: Props) {
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
      <div style={{ maxWidth: '68%', minWidth: 0, position: 'relative' }}>
        {isAgent && agent && showName && (
          <div className="mono" style={{ fontSize: 10, color: 'var(--gold)', marginBottom: 4, marginLeft: 4, letterSpacing: '0.03em' }}>
            {agent.name}
          </div>
        )}

        {/* Reaction picker (double-click) */}
        {showPicker && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            className="glass"
            style={{
              position: 'absolute', top: -40, [isAgent ? 'left' : 'right']: 0,
              display: 'flex', gap: 2, padding: '4px 6px', borderRadius: 20, zIndex: 5,
            }}
          >
            {REACTIONS.map((e) => (
              <button
                key={e}
                onClick={() => onPick?.(e)}
                style={{ fontSize: 16, width: 28, height: 28, borderRadius: 50, lineHeight: 1 }}
                onMouseEnter={(ev) => (ev.currentTarget.style.background = 'rgba(255,255,255,0.08)')}
                onMouseLeave={(ev) => (ev.currentTarget.style.background = 'transparent')}
              >
                {e}
              </button>
            ))}
          </motion.div>
        )}

        <div
          onDoubleClick={onOpenPicker}
          className={isAgent ? 'glass' : 'glass-gold'}
          style={{
            padding: '10px 14px',
            borderRadius: isAgent ? '4px 14px 14px 14px' : '14px 4px 14px 14px',
            fontSize: 14,
            lineHeight: 1.5,
            color: 'var(--text-hi)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            cursor: 'default',
            userSelect: 'text',
          }}
        >
          {text}
        </div>

        {/* Reaction pills */}
        {reactions.length > 0 && (
          <div style={{ display: 'flex', gap: 4, marginTop: 5, justifyContent: isAgent ? 'flex-start' : 'flex-end', marginInline: 4, flexWrap: 'wrap' }}>
            {reactions.map((r, i) => (
              <span
                key={i}
                className="glass"
                style={{ fontSize: 12, padding: '1px 7px', borderRadius: 20, lineHeight: 1.4, display: 'inline-flex', alignItems: 'center' }}
              >
                {r}
              </span>
            ))}
          </div>
        )}

        {time && showMeta && (
          <div className="mono-meta" style={{ marginTop: 4, textAlign: isAgent ? 'left' : 'right', marginInline: 4 }}>
            {time}
          </div>
        )}
      </div>
    </motion.div>
  )
}
