import type { AgentState } from '../data/agentConfig'

const cls: Record<AgentState, string> = {
  LIVE: 'dot dot-live',
  STANDBY: 'dot dot-standby',
  BUILDING: 'dot dot-building',
}

export default function AgentDot({ state }: { state: AgentState }) {
  return <span className={cls[state]} />
}
