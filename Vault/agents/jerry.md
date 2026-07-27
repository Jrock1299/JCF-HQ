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

## P&L accounting (rebuilt 2026-07-27)

Jerry's realised P&L was silently broken from day one — every closed trade
recorded `pnl: 0.0`. Three separate defects, all now fixed in `jerry_trader.py`:

| # | Defect | Fix |
|---|---|---|
| 1 | `_mark_closed` computed P&L only inside `if symbol not in positions:`, checked microseconds after submitting a market close order. Alpaca still lists the position until it fills, so the branch never ran. | P&L now comes from the close order's own fill (`_resolve_order_fill` polls to a terminal state and reads `filled_avg_price`). |
| 2 | Bracket SL/TP orders fill server-side and never call `close_position()`, so those trades stayed `open` locally forever. | `reconcile_closed_positions()` runs at the top of every tick, resolving exits from the broker FILL activity feed. |
| 3 | Entry price was the **pre-trade snapshot**, not the fill — wrong on 119 of 126 records, understating cost basis ~$5.1k. Even a correct close computation would have been wrong. | `buy_stock` / `short_stock` / `buy_option` / `sell_option` all record the broker fill. |

**Never a fake zero.** Where a fill can't be established the trade records
`pnl: None` + `pnl_status: UNVERIFIED_*` rather than `0.0` — an unverified
close counted as a $0 trade would quietly drag win rate and expectancy toward
zero. This is CLAUDE.md Rule #9 applied at the write side rather than only at
the grading side. Fields: `pnl_status`, `entry_source`, `exit_source`.

**Options are ×100** (per-share premium × 100 shares/contract). Verified against
Alpaca's own `cost_basis` (5 contracts × $0.72 × 100 = $360) and against implied
starting equity, which lands on $100,000 only with the multiplier applied.

**History backfilled** from Alpaca's FILL feed — entry prices corrected exactly
by order id, exits matched lot-level FIFO. Reconciles to broker cash flows
within **$0.04**. 116 records carry real P&L, 3 are `UNVERIFIED_NO_ENTRY_FILL`.

First real verdict from [[victoria]]: **FAIL** — 116 trades, WR 35.3%,
PF 0.972, Sharpe -0.005, net -$599.29, ruin 0.0%. A real grade on real data,
replacing the NO_DATA the validator correctly returned while the feed was empty.

## Team context (Phase 1 — observation only)
Loads context at every trade entry via `jerry_context.py`:
- [[lens]] bias for the ticker (with US100/SPX500 fallback)
- [[_retired/jarvis|jarvis]] regime for SPX500/DE30/XAU/BTC (or `neutral` if Jerry's ticker
  isn't covered)
- [[_retired/norman|norman]] verdict on Jerry itself
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
  [[_retired/jarvis|jarvis]], [[_retired/norman|norman]]
- Reports to: [[victoria]] (daily P&L), [[_retired/norman|norman]] (validation)
- Wraps Telegram via: [[huncho]]

## Model routing
`openai/gpt-5.6-terra` via the Codex gateway (`_run_codex` in `jerry_config.py`,
shared by discover + review) — **migrated 2026-07-24** off the Anthropic SDK, same
pattern as [[victoria]]/[[_retired/norman|norman]]/[[_retired/lucy|lucy]]. Discovery still web-searches via the
gateway agent's own tools. No `ANTHROPIC_API_KEY` dependency. Trade execution
stays deterministic Alpaca REST. `jerry.service` held (not started) pending
go-ahead. Also fixed a pre-existing `None`-value crash in the review's date
filter (`t.get('closed_at', '')` → `(t.get('closed_at') or '')`). See
[[../infrastructure/model-routing]], [[../sessions/2026-07-24]].
