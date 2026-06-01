# 🔍 Sentinel — Insider + Market Intel

**Internal id:** `sentinel` (script-based, not a Telegram personality)
**Role:** Pulls insider trading + market intelligence from free API tiers
**Status:** Active. 3× daily on weekdays.
**Voice:** N/A — Sentinel is a data pipeline, not a chatty agent. Its
output is consumed by other agents.

## What Sentinel does
Calls Finnhub Free + FMP Free to pull:
- Watchlist insider buy/sell signals (Form-4 filings)
- Top discoveries (small/mid-cap institutional moves outside watchlist)
- Analyst recommendations
- Earnings calendar
- Market news headlines

Aggregates into `dashboard/sentinel_data.json` for downstream agents.

## Watchlist source
Read from `dashboard/watchlist.json` (Jase's by-theme tickers — `holdings`,
`quantum_nuclear`, `energy`, `metals`, `robotics_ai`, `saudi`, `tech_semis`).
Falls back to a hardcoded copy in `sentinel_sync.py` if the file is missing.

See [[../infrastructure/config#watchlist]] for the move from hardcoded
WATCHLIST dict to the external JSON.

## Schedule
- `0 8  * * 1-5`
- `0 14 * * 1-5`
- `0 20 * * 1-5`

3× daily weekdays.

## Key files
- `scripts/sentinel/sentinel_sync.py` — main pipeline
- `scripts/sentinel/run_sentinel.sh` — cron launcher
- `dashboard/sentinel_data.json` — output (consumed by Jerry + Lens + dashboard)
- `dashboard/watchlist.json` — Jase's tickers (now external)

## Cross-agent connections
- Reads: Finnhub + FMP (external)
- Read by: [[jerry]] (gates discovery), [[lens]] (folds into morning bias),
  [[victoria]] (folded into daily report), the React Intelligence dashboard
- Wraps Telegram via: none directly — surfaces through Jerry / Lens / Victoria

## Why no personality
Sentinel never sends its own Telegram messages. It's a data agent — its
value is the JSON it produces. Reasoning agents read the data and draw
the conclusions.
