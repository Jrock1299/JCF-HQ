# 🔍 Lucy — Skills & Tools Scout

**Internal id:** `lucy`
**Role:** Weekly scout for new skills, tools, APIs, and MCP servers
**Status:** Active but low-traffic. Not a trading agent.
**Voice:** Curious researcher — surfaces options, doesn't decide.

## What Lucy does
Every Sunday at noon UTC, Lucy researches:
- GitHub trending repos in trading / agent infra / quant
- Reddit (r/algotrading, r/quant, r/MachineLearning)
- HackerNews threads relevant to the system
- Product Hunt launches
- Anthropic docs (skills, MCP, new features)
- MCP registries

Outputs suggestions for new skills / MCPs / tools to evaluate. The user
decides what to integrate.

## Why kept active
Lucy is the only agent that proactively scouts for tools that could
strengthen the rest of the system. She caught the skills system we now
bake into [[jarvis]], [[norman]], [[lens]], and the chart-analysis prompt.

She was considered for benching in the 2026-06-01 rundown but kept by user
decision — non-trading but feeds the meta-system.

## Schedule
`0 12 * * 0` (Sunday noon UTC).

## Key files
- `agents/lucy/lucy_brain.py` — main entrypoint (run with `--research`)
- `logs/lucy.log`

## Cross-agent connections
- Reads: external sources (GitHub, Reddit, HN, etc.)
- Read by: none directly — output is research suggestions for the user
- Wraps Telegram via: [[huncho]]

## Model routing
Codex via the `openclaw agent` subprocess pattern (`_run_agent`), not the
Anthropic SDK. PRIMARY `openai/gpt-5.6-terra` (bumped 2026-07-24 from the dead
`openai/gpt-5.3-codex`, which was a runtime-bound id the gateway silently
rejected → always fell back), FALLBACK `openai/gpt-5.5`. web_search runs inside
the gateway agent turn.
