import { useState } from 'react'
import type { Agent } from '../data/agentConfig'

interface Props {
  agent: Agent
  size?: number
}

// Renders the portrait; on 404/load error falls back to the agent's emoji
// inside a matching glass circle. Never shows a broken image.
export default function AgentAvatar({ agent, size = 32 }: Props) {
  const [failed, setFailed] = useState(false)

  if (failed) {
    return (
      <div
        className="agent-avatar-fallback"
        style={{ width: size, height: size, fontSize: size * 0.5 }}
        title={agent.name}
      >
        <span>{agent.emoji}</span>
      </div>
    )
  }

  return (
    <img
      className="agent-avatar"
      src={agent.portrait}
      alt={agent.name}
      width={size}
      height={size}
      style={{ width: size, height: size }}
      onError={() => setFailed(true)}
    />
  )
}
