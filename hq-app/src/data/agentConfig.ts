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
    model: 'Codex',
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
    model: 'Codex',
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
    name: 'Chad',
    emoji: '🏎️',
    portrait: '/agents/crisp.png',
    role: 'Meme Coins — Solana',
    model: 'Codex',
    state: 'BUILDING',
    connectedTo: [],
    voice: 'I show up early and let the room chase me. Same with the wallet.',
  },
]

// Expanded profile copy for the Agents-page modal (Round 2, Section 9).
export interface AgentProfile {
  motto: string
  bio: string
}
export const AGENT_PROFILES: Record<string, AgentProfile> = {
  huncho: {
    motto: 'Family first. Numbers second. Excuses never.',
    bio: 'The Don of the operation — every agent answers to him, and every message routes through his hands. He runs the family with warm authority and zero tolerance for freelancing, keeping the whole roster tight, honest, and pointed in one direction. Terse, knowing, always three moves ahead.',
  },
  lens: {
    motto: 'The market always tells you — you just have to listen.',
    bio: 'The macro analyst who reads the tape like scripture. Every morning he web-searches the world, weighs the news by impact, and hands every downstream agent a clean bias and confidence read. Calm and unhurried — he would rather wait for the market to speak than force a guess.',
  },
  blade: {
    motto: 'Discipline is the only edge that never fades.',
    bio: 'The primary trading operator — a pure 15-minute ORB breakout specialist across SPX, DAX, and CHF/JPY. Stoic and rule-bound, he takes only the setups his structure allows and treats a flat day as a position. Discipline over action, every single session.',
  },
  jerry: {
    motto: "Let the numbers speak. I'll just execute.",
    bio: 'The quiet stocks-and-options paper trader on Alpaca. He runs pre-market discovery, works the day’s watchlist in five-minute ticks, and reviews every close. No ego, no narrative — he lets the numbers pick the trades and simply executes.',
  },
  jarvis: {
    motto: 'Complexity is just simplicity nobody explained yet.',
    bio: 'The right-hand strategist who turns market complexity into a plain-English brief before every session. He reads regime, breadth, and rotation, then tells you what actually matters today. Composed and precise — three steps ahead, but always happy to explain it simply.',
  },
  victoria: {
    motto: 'I have outlived worse quarters than this.',
    bio: 'The CFO and chief of staff who owns the ledger with gothic-queen authority. She reads every account, produces the daily financial briefing, and flags what needs fixing without a shred of coddling. She has seen worse quarters than this and outlived them all.',
  },
  norman: {
    motto: "Risk doesn't care about your feelings.",
    bio: 'The risk validator who runs Monte Carlo on every agent’s closed trades and issues a cold PASS / FAIL verdict. Brutally honest by design, he blesses nothing until the math earns it. Respectful of the operator, entirely unmoved by the streak.',
  },
  lucy: {
    motto: "There's always a better tool. I'll find it.",
    bio: 'The scout who hunts the internet each week for new skills, tools, and MCPs worth adopting. Endlessly curious and a little too excited, she brings back receipts on anything that might sharpen the edge. If a better tool exists, she finds it first.',
  },
  tao: {
    motto: 'Patient capital outlives impatient markets.',
    bio: 'The patient allocator staking TAO across Bittensor subnets. She thinks in seasons, not sessions — DCA’ing quietly and harvesting only when the cycle turns. Stillness is a position, and she holds it well.',
  },
  edge: {
    motto: "Ready when you are. Still ready when you're not.",
    bio: 'The 1-hour SMA-crossover trader waiting on the bench, fully built and eager. His logic is dialed in on account 002; he just needs the green light. Ready when you are — and still ready when you’re not.',
  },
  phantom: {
    motto: 'Still becoming.',
    bio: 'The crypto-futures orchestrator still taking shape in the dark. Nothing ships until the thesis is real and the data backs it. Building quietly, patient enough to wait for the right moment to surface.',
  },
  crisp: {
    motto: 'Show up early. Let the room chase you.',
    bio: 'Chad — the meme-coin hunter on Solana. DexScreener trending scans, wallet intelligence, momentum-death detection for the downside. Old-money-cool confidence over new-money noise; the swagger lives in the voice, the discipline lives underneath — simulation-only until the data earns real size, same as everyone else.',
  },
}

export const AGENT_MAP: Record<string, Agent> = Object.fromEntries(
  AGENTS.map((a) => [a.id, a]),
)

export const stateColor = (s: AgentState): string =>
  s === 'LIVE' ? 'green' : s === 'STANDBY' ? 'amber' : 'purple'

export const liveCount = AGENTS.filter((a) => a.state === 'LIVE').length
