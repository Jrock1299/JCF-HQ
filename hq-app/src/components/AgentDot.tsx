import type { AgentState } from '../data/agentConfig'

const cls: Record<AgentState, string> = {
  LIVE: 'dot dot-live',
  STANDBY: 'dot dot-standby',
  BUILDING: 'dot dot-building',
  // Retired agents are filtered out of the active roster (ACTIVE_AGENTS), so
  // this only renders on an archive view that deliberately shows them.
  RETIRED: 'dot dot-retired',
}

export default function AgentDot({ state }: { state: AgentState }) {
  return <span className={cls[state]} />
}
