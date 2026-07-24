# 📊 Jerry — Stocks & Options Trader

**Internal id:** `jerry`
**Role:** Autonomous stocks and options paper trader on Alpaca
**Status:** Active. systemd service `jerry.service`. Paper account.
**Voice:** Professional money manager — measured, structured.

## What Jerry does
A daily cycle of discovery → execution → review against the day's watchlist.
Claude Sonnet 4.6 brain reasons about [[sentinel]] signals, market context,
and Lens biases to build the day's high-conviction list. Alpaca executes
during market hours.

## Daily cycle (UTC)
- **13:00** — pre-market discovery: Claude reasons about [[sentinel]] + macro,
  produces the day's watchlist + thesis per ticker
- **13:30–20:00** — 5-min trading ticks; checks watchlist entry zones, opens
  positions with bracket SL/TP, manages open positions
- **20:30** — daily review
- **Outside hours** — 60-sec heartbeat sleep

## Safety
- `STARTING_BALANCE = $100,000` paper
- `SAFETY_FLOOR = 0.25 × STARTING_BALANCE` = $25K floor — pauses if portfolio
  drops below, sends Telegram alert
- Position cap: 15% of balance per stock
- Options cap: 5 contracts per trade

## Team context (Phase 1 — observation only)
Loads context at every trade entry via `jerry_context.py`:
- [[lens]] bias for the ticker (with US100/SPX500 fallback)
- [[jarvis]] regime for SPX500/DE30/XAU/BTC (or `neutral` if Jerry's ticker
  isn't covered)
- [[norman]] verdict on Jerry itself
- `strategist_aligned` flag (does bias match trade direction?)

Logged to `dashboard/jerry_learning_log.json` AND stamped onto every row in
`trade_history.json`. No gating. See
[[../infrastructure/system-architecture#cross-agent-comms-phase-1-3|Phase 1/2/3]].

## Key files
- `agents/jerry/jerry_main.py` — daily cycle orchestrator
- `agents/jerry/jerry_trader.py` — Alpaca execution layer + learning-log writer
- `agents/jerry/jerry_discover.py` — discovery brain (Claude call)
- `agents/jerry/jerry_review.py` — daily review
- `agents/jerry/jerry_context.py` — team-context loader (Lens/Jarvis/Norman)
- `agents/jerry/jerry_config.py` — env + paths
- `dashboard/jerry_portfolio.json`
- `dashboard/jerry_learning_log.json`

## Cross-agent connections
- Reads: [[sentinel]] (insider/discovery signals — primary input), [[lens]],
  [[jarvis]], [[norman]]
- Reports to: [[victoria]] (daily P&L), [[norman]] (validation)
- Wraps Telegram via: [[huncho]]

## Model routing
`openai/gpt-5.6-terra` via the Codex gateway (`_run_codex` in `jerry_config.py`,
shared by discover + review) — **migrated 2026-07-24** off the Anthropic SDK, same
pattern as [[victoria]]/[[norman]]/[[lucy]]. Discovery still web-searches via the
gateway agent's own tools. No `ANTHROPIC_API_KEY` dependency. Trade execution
stays deterministic Alpaca REST. `jerry.service` held (not started) pending
go-ahead. Also fixed a pre-existing `None`-value crash in the review's date
filter (`t.get('closed_at', '')` → `(t.get('closed_at') or '')`). See
[[../infrastructure/model-routing]], [[../sessions/2026-07-24]].
