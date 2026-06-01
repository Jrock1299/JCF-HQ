# 👑 Huncho — Orchestrator

**Internal id:** `huncho`
**Role:** Orchestrator, Telegram router, kill-zone scheduler
**Status:** Always-on (Telegram gateway)
**Voice:** NY mob-boss energy — terse, knowing, slightly amused. Catchphrases:
*"Aye." "My guy." "— H"*

## What Huncho does
- Receives all inbound Telegram messages from Jase and routes them
- Delegates chart reads to [[blade]] via `chart_analysis.py` (image vision)
- Fires session-prep pings 10 min before each Blade session, now augmented
  with an automated 4H chart read per instrument via [[../infrastructure/system-architecture#h4-read-pipeline|the H4 read pipeline]]
- Wraps every outbound message with the right personality (see [[../infrastructure/personalities]])

## Model routing
- Primary reasoning: Codex (`openai/gpt-5.3-codex` via Codex runtime), but
  most inference now flows through `openai/gpt-5.5` (Codex aliases redirect).
- Chart analysis pipeline uses image-capable fallback list:
  `codex/gpt-5.4` → `codex/gpt-5.5`. Default `moonshot/kimi-k2.5` is
  **billing-suspended** — do not use until restored. See [[../infrastructure/model-routing]].

## Schedule
- Always on (Telegram listener)
- Session-prep pings: `40 23 / 45 7 / 15 13 / 45 17 * * 1-5` (10 min before
  ASIA / LONDON / NY_OPEN / NY_PM). See [[../infrastructure/cron-schedule]].

## Key files
- `agents/huncho/killzone_sync.py` — kill-zone timing logic
- `agents/main/skills/chart_analysis.py` — on-demand chart reads (image model fallback)
- `scripts/session_prep_ping.sh` — pre-session ping + auto 4H reads
- `scripts/telegram_personalities.py` — voice wrapper

## Cross-agent connections
- Delegates to: [[blade]] (chart analysis), all agents via Telegram routing
- Reads: nothing directly — agents Telegram through him via `wrap_message`
- Writes: Telegram out to Jase

## Related notes
- [[../infrastructure/personalities]] — Huncho's voice + the wrap_message system
- [[../infrastructure/system-architecture#h4-read-pipeline|H4 read pipeline]]
- [[../sessions/2026-06-01]] — recent changes (Telegram formatting cleanup, --target flag fix)
