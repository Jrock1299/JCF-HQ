export interface HubMessage {
  from: 'agent' | 'jase'
  text: string
  time: string // display string, e.g. "7:42 AM"
  agentId?: string // which agent said it (used in Group Chat)
  reactions?: string[] // emoji reactions on this bubble
}

// Group Chat seed — the family talking amongst themselves. `agentId` tags who
// is speaking so the right portrait/name renders.
export const GROUP_SEED: HubMessage[] = [
  { from: 'agent', agentId: 'huncho', time: '7:00 AM', text: "Mornin' family. Fresh week, clean slate. Blade's balance is zeroed out — Jase sets the number when he's ready. Everybody sharp. — H" },
  { from: 'agent', agentId: 'lens', time: '7:01 AM', text: 'Macro read is posted. Dollar firm, gold coiled. Two-sided tape until the data lands — patience today.' },
  { from: 'agent', agentId: 'norman', time: '7:02 AM', text: 'And nobody touches size until I see 100 closed clusters. Risk does not care about anyone’s mood.' },
  { from: 'agent', agentId: 'victoria', time: '7:03 AM', text: 'The ledger is clean and the costs are trimmed. Keep it that way, darlings.' },
]

export interface Thread {
  agentId: string
  unread: boolean
  messages: HubMessage[]
  // In-character canned replies, cycled through when Jase sends a message.
  replies: string[]
}

// The soul of the app. Every line is written the way this agent would actually
// text Jase — like family, not a status report.
export const THREADS: Thread[] = [
  {
    agentId: 'huncho',
    unread: true,
    messages: [
      {
        from: 'agent',
        time: '7:12 AM',
        text: "Aye, look who's back. Everything's runnin smooth over here — Blade held his position through that CPI mess like a soldier, Jerry stacked three green trades while you was sleep. Family's eatin. What you need? — H",
      },
    ],
    replies: [
      "Say no more, I'll handle it. You just point, I aim. — H",
      "Already on it. Blade and Jerry know their jobs, I keep 'em honest. Go get your coffee. — H",
      "That's what I like to hear. We keep it tight, we keep it movin. Anything else, my guy? — H",
      "Consider it done. Nobody in this family freelances without me knowin. — H",
    ],
  },
  {
    agentId: 'lens',
    unread: true,
    messages: [
      {
        from: 'agent',
        time: '4:58 AM',
        text: "Morning. The dollar's been flexing all week — CPI today decides if it keeps flexing or takes a breather. My read: let the number drop, let the dust settle, then look at SPX. Gold's been respecting $2,340 like it owes it money.",
      },
    ],
    replies: [
      'Patience is the whole trade today. The market will tell us — we just have to be quiet enough to hear it.',
      "Nothing forced. When the macro is this two-sided, the edge is in waiting for one side to blink.",
      "I'll have a fuller read once the print lands. Until then, the levels I gave you are the map.",
      'Risk is on for equities, off for crypto. Keep those two thoughts separate and you stay clear-headed.',
    ],
  },
  {
    agentId: 'blade',
    unread: false,
    messages: [
      {
        from: 'agent',
        time: '8:04 AM',
        text: "Held the London entry — CPI risk wasn't worth it. Discipline over action. If the print's clean I'm back in for NY. Balance sitting at $5,064. We move smart or we don't move.",
      },
      { from: 'jase', time: '8:06 AM', text: 'good call. don\'t force it' },
      {
        from: 'agent',
        time: '8:06 AM',
        text: 'Never do. The setup either comes to me or it doesn\'t. Flat is a position too.',
      },
    ],
    replies: [
      'Copy. Standing by for the NY open. No trade is better than a bad trade.',
      'Understood. Stop stays structural, size stays at 2% cluster. Rails hold.',
      "Watching the ORB form now. First clean break beyond the level, I'm in. Not before.",
      'Acknowledged. Discipline over action. Always.',
    ],
  },
  {
    agentId: 'jerry',
    unread: false,
    messages: [
      {
        from: 'agent',
        time: '6:31 AM',
        text: "Three trades closed overnight. All green. +$65.20. Account's at $109,672 now. Back to work.",
      },
    ],
    replies: [
      'Noted. Watchlist is set for the open. Back to work.',
      "Discovery run's done. Nothing worth chasing pre-market. I'll wait for the tape.",
      'Understood. Keeping size small until the market picks a direction.',
      'On it. Numbers over feelings, always.',
    ],
  },
  {
    agentId: 'jarvis',
    unread: true,
    messages: [
      {
        from: 'agent',
        time: '6:00 AM',
        text: "Yo — quick read on today: market's choppy, not trending. I'd chill until CPI hits at 8:30. If it comes in soft, Blade's got room to work. If it's hot, we sit on our hands. No shame in a flat day.",
      },
    ],
    replies: [
      "Here's the simple version: don't fight a range. Let the number pick the direction, then lean into it.",
      "Regime's compressed right now — think coiled spring. When it releases, it'll be fast. Be ready, not early.",
      "If you only remember one thing today: soft CPI = go, hot CPI = wait. That's the whole playbook.",
      "I'd keep expectations measured. Some days the best trade is the one you don't take.",
    ],
  },
  {
    agentId: 'victoria',
    unread: true,
    messages: [
      {
        from: 'agent',
        time: '9:00 PM',
        text: 'Ahh, the master returns. The ledger pleases me today — +$247 while you slept. I have watched empires rise on smaller gains. Do not let it make you comfortable.',
      },
    ],
    replies: [
      'Comfort is the tax the successful pay before they fall. We will not be paying it.',
      'The numbers are sound. API costs are trimmed, drawdown is contained. I have seen to it.',
      'Every coin accounted for. I do not lose things, darling — I collect them.',
      'Rest if you must. The ledger never sleeps, and neither do I.',
    ],
  },
  {
    agentId: 'norman',
    unread: false,
    messages: [
      {
        from: 'agent',
        time: 'Sat 10:04 AM',
        text: "I looked at the numbers. We're within risk limits but I want 100 closed clusters before I bless the new sizing fully. Saturday I run the deep sim. Until then — no hero trades. That's how accounts die.",
      },
    ],
    replies: [
      'Good. Patience is a risk control, not a weakness. Keep filling the log.',
      'The Monte Carlo will tell us if the edge is real or if we got lucky. I trust the math, not the streak.',
      "Stay inside the rails. One percent per trade, two per cluster, minus four daily. Those aren't suggestions.",
      "Bring me the data. I'll bring you the verdict. That's the arrangement.",
    ],
  },
  {
    agentId: 'lucy',
    unread: true,
    messages: [
      {
        from: 'agent',
        time: 'Sun 12:14 PM',
        text: "okayyy so I found something this week 👀 there's an MCP tool that pulls DexScreener data live — when Crisp wakes up for the meme coin thing?? this could be HIS whole edge. full report Sunday, you're gonna like this one 🔍",
      },
    ],
    replies: [
      'omg yes I already have like 6 tabs open on it 😭 sending you the writeup in a sec',
      "right?? I knew you'd be into it. lemme dig a little deeper and I'll bring receipts 🔍",
      "on it!! I'll cross-check it against the other two I found. one of these is gonna be a keeper",
      'yesss ok giving you the full breakdown Sunday. this is the fun part of the job fr',
    ],
  },
  {
    agentId: 'tao',
    unread: false,
    messages: [
      {
        from: 'agent',
        time: '6:00 AM',
        text: 'The stake holds. 3.345 TAO across six subnets, breathing with the market. Down bad on paper — but we planted for the next cycle, not this one. Patience pays the patient.',
      },
    ],
    replies: [
      'No action needed. The DCA engine tends the garden on its own schedule.',
      'A red candle is just weather. The season is what matters, and the season is long.',
      "We hold. Profit-taking tiers are armed — when the subnets run, we'll be there to harvest.",
      'Stillness is a position. I am comfortable doing nothing well.',
    ],
  },
  {
    agentId: 'edge',
    unread: false,
    messages: [
      {
        from: 'agent',
        time: 'Yesterday',
        text: "On the bench but ready. New 1H strategy's built and waiting. Say the word and I'm live on account 002.",
      },
    ],
    replies: [
      "Just say go. SMA 8/21 cross, three-position cluster, trailing the 21. It's dialed in.",
      "I've been backtesting while I wait. The logic's clean — I just need the green light.",
      'Ready when you are. I promise I earn the roster spot.',
      'Standing by. The moment you flip me on, I execute. No hesitation.',
    ],
  },
  {
    agentId: 'phantom',
    unread: false,
    messages: [
      {
        from: 'agent',
        time: '—',
        text: "Still taking shape in the dark. Futures strategy pending — I don't move until the thesis is real and the data backs it. Soon.",
      },
    ],
    replies: [
      "Not yet. When I go live, it'll be because the edge is proven, not hoped for.",
      'Building quietly. You\'ll know when I\'m ready — the tape will feel it.',
      'Patience. A phantom that shows up early gets caught. I wait for the right dark.',
    ],
  },
  {
    agentId: 'crisp',
    unread: false,
    messages: [
      {
        from: 'agent',
        time: '—',
        text: 'Cold storage for now. Waiting on the meme coin mandate — new soul, new hunt. When Solana szn hits, I\'ll be sharp and ready.',
      },
    ],
    replies: [
      'Give me the mandate and I go hunting. Solana degens won\'t know what hit \'em.',
      'Still on ice. But ice keeps things fresh — I\'ll be crisp when it counts.',
      "Waiting on Lucy's DexScreener intel. Once I've got eyes, I've got edge.",
    ],
  },
]

export const THREAD_MAP: Record<string, Thread> = Object.fromEntries(
  THREADS.map((t) => [t.agentId, t]),
)
