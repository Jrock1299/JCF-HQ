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
- [[_retired/norman|norman]] `norman_report.json`
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
`openai/gpt-5.6-terra` via the Codex runtime (Lucy's `_run_codex` subprocess
pattern); bumped 5.5→5.6 Terra 2026-07-24. No separate `system` slot, so the
gothic-queen persona is prepended into the user message — verified intact on
test ("The coffers neither grew nor shrank. A stagnant eve."). No longer draws
on `ANTHROPIC_API_KEY`. Override must be a plain tier id whitelisted in
`agents.defaults.models`; `-codex` ids and Sol don't work on this backend.


## Absorbed 2026-07-25 (consolidation)

Victoria took over two functions when [[_retired/lucy|Lucy]] and
[[_retired/norman|Norman]] were retired:

### Scouting desk (from Lucy)
`agents/victoria/victoria_scout.py`. Weekly hunt for skills / tools / MCP
servers, run **inline by the weekly tribunal** so the CFO rules on findings in
her own voice rather than sending a second disconnected report. Writes
`dashboard/victoria_scout.json`.
**DEFAULT OFF** (`--with-scout` / `VICTORIA_WITH_SCOUT=1`) — her weekly cron is
already live, and defaulting it on would have activated Lucy's function on a
schedule without approval.

### Risk validation for Jerry + Chad (from Norman)
`agents/victoria/victoria_validator.py`, importing the pipeline from
`scripts/risk_validation.py`. Writes `dashboard/victoria_validation.json`.
**[[jerry]] is new to validation** — Norman never covered him. His P&L feed is
currently unpopulated (all closed positions report 0.00), so the validator
correctly returns `NO_DATA` rather than grading a FAIL off nothing.

⚠️ The validation cron line is `#HOLD PENDING-APPROVAL` as of 2026-07-25.
