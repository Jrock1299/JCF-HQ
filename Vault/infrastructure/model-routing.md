# Model Routing

Which agent uses which LLM, and why.

## The matrix

| Agent | Primary | Fallback | Why |
|---|---|---|---|
| [[../agents/lens]] | `claude-sonnet-4-6` (Anthropic SDK) | none | Needs web_search + reasoning depth + structured JSON |
| [[../agents/_retired/norman|norman]] | `claude-sonnet-4-6` (Anthropic SDK) | none | Structured verdict reasoning |
| [[../agents/victoria]] | `claude-sonnet-4-6` (Anthropic SDK) | none | Long-context aggregation across all agent outputs |
| [[../agents/jerry]] discovery + review | `claude-sonnet-4-6` (Anthropic SDK) | none | Discovery requires reasoning over Sentinel signals |
| [[../agents/_retired/jarvis|jarvis]] narrative | Codex via `openai/gpt-5.5` | `openrouter/auto` | Cheap, fast prose generation |
| H4 read pipeline | `openai/gpt-5.5` | `openrouter/auto` | Same — fast prose with structured format |
| [[../agents/huncho]] chart_analysis.py | Image-capable list: `codex/gpt-5.4` → `codex/gpt-5.5` | fallback returns "couldn't get a read" | Image vision needed |
| Trade execution (everywhere) | N/A — deterministic Python | N/A | No LLM in the execution path |

## Deprecated Codex aliases
The older `openai/gpt-5.3-codex`, `openai-codex/gpt-5.5-codex`, and
`codex/gpt-5.x` aliases are **deprecated server-side**. The gateway
returns:

```
gpt-5.3-codex is no longer supported for ChatGPT/Codex OAuth accounts.
Use openai/gpt-5.5 through the Codex runtime.
```

Anywhere the code references `openai/gpt-5.3-codex` for primary inference,
use `openai/gpt-5.5` instead. The image variants (`codex/gpt-5.4`,
`codex/gpt-5.5`) still work via the Codex app-server agent runtime for
image-describe calls.

## .env auth fix

Anthropic SDK calls fail with `TypeError: Could not resolve authentication
method` unless the run script sources `/root/.openclaw/.env` before launch.

Every run script that calls `anthropic.Anthropic()` must include this
block at the top:

```bash
#!/bin/bash
source /root/.bashrc
set -a
source /root/.openclaw/.env
set +a
cd /root/.openclaw/agents/<agent>
python3 <agent>_brain.py
```

Currently applied in:
- `agents/lens/run_lens_brain.sh`
- `agents/victoria/run_victoria.sh`
- `agents/victoria/run_victoria_weekly.sh`
- `agents/norman/run_norman.sh` (fixed 2026-06-01)

**Standing rule:** if you add a new Anthropic-using agent, add this block
to its launcher. Don't rely on environment variables being inherited from
cron — they're not.

## Skills integration approach (Option A)

Rather than spawning sub-agents to call skills from `~/.claude/skills/`,
we extract the **methodology** and bake it into the agent's system prompt.

This was chosen 2026-06-01 over Option B (porting skill scripts into the
codebase) because:
- Faster — no parallel code to maintain
- Cheaper — no extra LLM calls
- No latency hit at trade time
- Methodology survives skill-script changes; agents stay stable

Methodologies currently baked in:
- [[../agents/_retired/jarvis|jarvis]] — `macro-regime-detector`, `market-breadth-analyzer`, `sector-analyst`
- [[../agents/_retired/norman|norman]] — `backtest-expert`, `position-sizer`
- [[../agents/lens]] — `market-news-analyst`, `market-environment-analysis`
- chart_analysis.py — `technical-analyst` (scenarios with invalidation levels)

67 skills total in `~/.claude/skills/`. The 8 baked above are the trading-
relevant ones.

## Related
- [[system-architecture]]
- [[../agents/lens]] · [[../agents/_retired/norman|norman]] · [[../agents/_retired/jarvis|jarvis]]
- [[../decisions/decision-log#skills-baked-into-prompts-2026-06-01]]
