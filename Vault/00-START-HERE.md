# JCF HQ Vault — Start Here

> Welcome to JCF HQ's second brain. This is a navigable knowledge vault.
> Every note links to its neighbors via `[[wiki-links]]` — open it in
> Obsidian for the best experience.
>
> **Authoritative source:** the repo-root [`CLAUDE.md`](../CLAUDE.md) is
> the canonical state-of-the-system document. The notes here expand on
> it for navigation and depth. If they disagree, CLAUDE.md wins.
>
> **Maintenance rule:** Any session that changes an agent, strategy, or
> piece of infrastructure must update the matching note here AND drop a
> dated entry in [[sessions/2026-06-01|the session log]]. The vault is
> a living second brain — keep it current as a byproduct of work.

---

## Three-environment model

JCF HQ lives in three places that stay synchronized via the GitHub spine:

1. **VPS** — `/root/.openclaw/` — production. Cron-driven agents run here,
   talk to OANDA / Binance / Alpaca / Telegram. This is what trades.
2. **Laptop Claude Code** — development. Edits flow to the VPS via GitHub.
3. **GitHub (`master`)** — `github.com/Jrock1299/JCF-HQ`. Push from either
   environment, pull on the other. **The code + the repo-root CLAUDE.md =
   the source of truth.**

If something isn't in the code or the docs, assume it doesn't exist.

---

## Navigate the vault

### Active agents (11)
Trading & ops:
- [[agents/huncho|👑 Huncho]] — orchestrator, Telegram router, Don personality
- [[agents/blade|🔪 Blade]] — pure 15m ORB on SPX500 / DE30 / CHF_JPY · primary trader
- [[agents/edge|📡 Edge]] — 1H SMA 8/21 crossover on SPX500
- [[agents/jerry|📊 Jerry]] — Alpaca paper stocks + options

Intelligence & oversight:
- [[agents/lens|🌐 Lens]] — daily macro analyst (Claude Sonnet 4.6 + web_search)
- [[agents/jarvis|♟️ Jarvis]] — regime briefing twice daily (internal id `strategist`)
- [[agents/sentinel|🔍 Sentinel]] — insider / market intel pipeline
- [[agents/norman|⚠️ Norman]] — Monte Carlo strategy validator, brutally honest
- [[agents/victoria|🧛‍♀️ Victoria]] — CFO + chief of staff
- [[agents/tao|☯️ Tao]] — Bittensor staking, passive
- [[agents/lucy|🔍 Lucy]] — weekly skills / tools scout

### Benched & parked
- [[agents/_benched/forge|Forge]] · [[agents/_benched/naomi|Naomi]] · [[agents/_benched/advisor|Advisor]] — benched (non-trading)
- [[agents/_benched/crisp|Crisp]] — parked, awaiting meme coin pivot
- [[agents/_benched/phantom|Phantom]] — parked, awaiting strategy build

### Strategies (the math)
- [[strategies/orb-strategy|15-Minute Opening Range Breakout]]
- [[strategies/blade-d3-sizing|Blade D3 Sizing Redesign]] — full writeup + Monte Carlo
- [[strategies/edge-1h-crossover|Edge 1H SMA Crossover]]
- [[strategies/phantom-build|Phantom Build]] — placeholder for the collaborative design

### Infrastructure
- [[infrastructure/system-architecture|System Architecture]] — comms layer, learning logs, Phase 1/2/3
- [[infrastructure/cron-schedule|Cron Schedule]] — annotated
- [[infrastructure/model-routing|Model Routing]] — which agent uses which LLM, and why
- [[infrastructure/config|Centralized Config]] — `agent_strategies.json`, `watchlist.json`, the loader
- [[infrastructure/personalities|Telegram Personalities]] — voice, emoji, display aliases

### Operating history
- [[decisions/decision-log|Decision Log]] — every major call and the reason
- [[sessions/2026-06-01|2026-06-01 session]] — Oracle/Kalshi removal, Blade D3, comms layer, Jarvis, vault build

---

## Key principles
1. **Code wins.** When notes disagree with the code, fix the notes.
2. **Phase 1 is observation-only.** Blade / Edge / Jerry SEE team context but
   never gate on it. Patterns get validated by [[agents/norman|Norman]] at
   the 100-cluster checkpoint before any gating wire goes live. See
   [[infrastructure/system-architecture]].
3. **Risk rails are not advisory.** Blade max 1% per trade, 2% per cluster,
   -4% daily DD halt. See [[strategies/blade-d3-sizing]].
4. **Skills live in `~/.claude/skills/`** (67 installed). Bake methodology
   into agent prompts; don't spawn sub-agents to call them. See
   [[infrastructure/model-routing]].
5. **Secrets never go to GitHub.** See the secret-hygiene block in
   [[infrastructure/system-architecture]].
