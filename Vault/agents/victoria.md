# 🧛‍♀️ Victoria — CFO + Chief of Staff

**Internal id:** `victoria`
**Role:** Daily financial summary + operations briefing + recommendations
**Status:** Active. Daily report + Monday weekly tribunal.
**Voice:** Gothic queen — owns the operation, never coddles. *"The coffers
neither grew nor shrank. A stagnant eve."*

## What Victoria does
Reads everything every day at 21:00 UTC and on Monday mornings, then calls
`claude-sonnet-4-6` to produce a structured JSON report:
- Financial summary (P&L breakdown by source, MTD, net worth, API costs)
- Operations briefing (plain English)
- Agent status snapshot
- Recommendations
- Alerts
- **Fix prompts** — paste-ready Claude Code prompts for every actionable
  issue she identifies (her best feature; act on these)

## Data she reads
- TradeLocker trades (Blade live broker)
- Edge portfolio
- Tao portfolio
- Blade/Crisp agent P&L (`agent_pnl.json`)
- Plaid accounts, Robinhood, Trustwallet, Kraken (portfolio syncs)
- Net worth aggregator
- [[lens]] `market_bias.json`
- [[sentinel]] `sentinel_data.json`
- [[norman]] `norman_report.json`
- API cost rollups per agent
- Service statuses (systemctl is-active for `edge`, `crisp-v5`, `jcf-hq`, `hq-storage`)

## Output files
- `dashboard/victoria_report.json` — latest daily
- `dashboard/victoria_weekly.json` — latest weekly tribunal
- `logs/victoria_history.json` — chronological history
- `logs/victoria_api_costs.json`

## Schedule
- **Daily** — `0 21 * * *` (21:00 UTC)
- **Weekly tribunal** — `0 7 * * 1` (Monday 07:00 UTC)

## Key files
- `agents/victoria/victoria_brain.py` — main analyzer
- `agents/victoria/run_victoria.sh` / `run_victoria_weekly.sh` — both have
  the `.env` source fix

## Cross-agent connections
- Reads: everyone (she's the financial reporter)
- Read by: Jase (Telegram)
- Wraps Telegram via: [[huncho]] (her own emoji 🧛‍♀️ + footer)

## Recent updates
- 2026-07-24: Migrated off the Anthropic SDK to Codex (`openai/gpt-5.5` via
  the `openclaw agent` subprocess pattern). Both call sites (daily + the
  two-turn JSON fallback) and the weekly tribunal now route through
  `_run_codex`. Voice verified intact on test runs. See [[../sessions/2026-07-24]].
- 2026-06-01: All Oracle / Kalshi data sources removed from `victoria_brain.py`
  (no more `_format_oracle`, `_load_kalshi_csv`, etc.). Service status list
  no longer includes `kalshi-bot`. See [[../sessions/2026-06-01]].

## Model routing
`openai/gpt-5.5` via the Codex runtime (Lucy's `_run_codex` subprocess
pattern). No separate `system` slot, so the gothic-queen persona is prepended
into the user message — mild drift expected, not collapse; verified on test.
No longer draws on `ANTHROPIC_API_KEY`. The working `--model` override is
`openai/gpt-5.5` (the `-codex` suffixed ids are rejected as overrides).
