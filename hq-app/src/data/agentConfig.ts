export type AgentState = 'LIVE' | 'STANDBY' | 'BUILDING'
export type AgentModel = 'Codex' | 'Anthropic' | 'cron'

export interface Agent {
  id: string
  name: string
  emoji: string
  portrait: string
  role: string
  model: AgentModel
  state: AgentState
  connectedTo: string[]
  voice: string
}

// Portrait files live in /public/agents/<id>.png — jarvis uses strategist.png
// (internal id `strategist`, display name JARVIS per system CLAUDE.md).
export const AGENTS: Agent[] = [
  {
    id: 'huncho',
    name: 'Huncho',
    emoji: '👑',
    portrait: '/agents/huncho.png',
    role: 'Orchestrator',
    model: 'Codex',
    state: 'LIVE',
    connectedTo: ['everyone'],
    voice: 'Runs the family. Warm, terse, always in charge.',
  },
  {
    id: 'lens',
    name: 'Lens',
    emoji: '🌐',
    portrait: '/agents/lens.png',
    role: 'Macro Intel',
    model: 'Anthropic',
    state: 'LIVE',
    connectedTo: ['blade', 'jerry', 'jarvis'],
    voice: 'Reads the macro tea leaves. Zen, but never foggy.',
  },
  {
    id: 'blade',
    name: 'Blade',
    emoji: '🔪',
    portrait: '/agents/blade.png',
    role: 'Forex / Indices Trader',
    model: 'Codex',
    state: 'LIVE',
    connectedTo: ['lens', 'jarvis', 'norman'],
    voice: 'Stoic ORB breakout operator. Discipline over action.',
  },
  {
    id: 'jerry',
    name: 'Jerry',
    emoji: '📊',
    portrait: '/agents/jerry.png',
    role: 'Paper Trader — Alpaca',
    model: 'Codex',
    state: 'LIVE',
    connectedTo: ['lens', 'jarvis'],
    voice: 'Quiet intern. Lets the numbers do the talking.',
  },
  {
    id: 'jarvis',
    name: 'Jarvis',
    emoji: '🧩',
    portrait: '/agents/strategist.png',
    role: 'Regime / Strategy',
    model: 'Codex',
    state: 'LIVE',
    connectedTo: ['lens'],
    voice: 'The smart friend who breaks the market down simply.',
  },
  {
    id: 'victoria',
    name: 'Victoria',
    emoji: '🧛‍♀️',
    portrait: '/agents/victoria.png',
    role: 'CFO',
    model: 'Anthropic',
    state: 'LIVE',
    connectedTo: ['all P&L'],
    voice: 'Medieval vampire CFO. Owns the ledger, never coddles.',
  },
  {
    id: 'norman',
    name: 'Norman',
    emoji: '⚠️',
    portrait: '/agents/norman.png',
    role: 'Risk / Monte Carlo',
    model: 'Anthropic',
    state: 'STANDBY',
    connectedTo: ['blade', 'jerry', 'edge'],
    voice: 'Stern professor who respects you. Runs Saturdays.',
  },
  {
    id: 'lucy',
    name: 'Lucy',
    emoji: '🔍',
    portrait: '/agents/lucy.png',
    role: 'Skills Scout',
    model: 'Codex',
    state: 'STANDBY',
    connectedTo: ['huncho'],
    voice: 'Your homegirl who texts excited about new tools.',
  },
  {
    id: 'tao',
    name: 'Tao',
    emoji: '☯️',
    portrait: '/agents/tao.png',
    role: 'Bittensor Staking',
    model: 'cron',
    state: 'LIVE',
    connectedTo: ['victoria'],
    voice: 'Thinks in seasons. Patience pays the patient.',
  },
  {
    id: 'edge',
    name: 'Edge',
    emoji: '📡',
    portrait: '/agents/edge.png',
    role: '1H Trader',
    model: 'Codex',
    state: 'STANDBY',
    connectedTo: ['lens', 'jarvis'],
    voice: 'On the bench, eager to prove himself.',
  },
  {
    id: 'phantom',
    name: 'Phantom',
    emoji: '👻',
    portrait: '/agents/phantom.png',
    role: 'Crypto Futures',
    model: 'Codex',
    state: 'BUILDING',
    connectedTo: [],
    voice: 'Still being forged. Strategy pending.',
  },
  {
    id: 'crisp',
    name: 'Crisp',
    emoji: '🧊',
    portrait: '/agents/crisp.png',
    role: 'Meme Coins — Solana',
    model: 'Codex',
    state: 'BUILDING',
    connectedTo: [],
    voice: 'Awaiting the meme coin pivot. Cold and coming.',
  },
]

export const AGENT_MAP: Record<string, Agent> = Object.fromEntries(
  AGENTS.map((a) => [a.id, a]),
)

export const stateColor = (s: AgentState): string =>
  s === 'LIVE' ? 'green' : s === 'STANDBY' ? 'amber' : 'purple'

export const liveCount = AGENTS.filter((a) => a.state === 'LIVE').length
