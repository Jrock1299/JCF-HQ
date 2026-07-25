# 📡 Edge — 1H SMA Crossover

**Internal id:** `edge`
**Role:** SMA 8/21 crossover trader on 1H candle close
**Status:** Active. ~2,474 historical closed positions, cumulative -$1,226 on
the $5,000 starting balance. Norman: INSUFFICIENT_DATA post-reset.
**Instrument:** SPX500_USD only (OANDA practice `101-001-22502524-002`)
**Voice:** Clinical, laconic — no fluff.

## What Edge does
A new 1H candle close triggers a cross check: SMA(8) vs SMA(21). If aligned
(long when 8 > 21, short when 8 < 21), check the optional H4 trend filter,
then open a 3-position **cluster** as one aggregate market order.

## Trade structure
- Cluster = 3 × `UNITS` (default 2 → 6 units total) entered together
- pos1 TP = +15 pts
- pos2 TP = +25 pts
- pos3 = no fixed TP → **trails the 21 SMA** (closes when a 1H candle closes
  through SMA21)
- After pos1 fires: pos2 SL → BE, pos3 begins trailing
- 4H trend filter (optional): longs require H4 bullish, shorts require H4 bearish

## Risk
- Max 5 losing clusters/day → halts new entries
- Halts on -2% intraday drawdown
- 15-minute blackout after US cash open (13:30 UTC)
- Max 24h hold (force-close safety net)

## Team context (Phase 1 — observation only)
At cluster entry, Edge calls `_load_team_context()`:
- [[_retired/jarvis|jarvis]] regime
- [[lens]] bias for SPX500
- [[_retired/norman|norman]] verdict on Edge
- [[../infrastructure/system-architecture#h4-read-pipeline|H4 read]] (cached 30 min)

Logged to `dashboard/edge_learning_log.json` and stamped onto every trade
record. **No gating.** See [[../infrastructure/system-architecture#cross-agent-comms-phase-1-3|Phase 1/2/3]].

## Key files
- `agents/edge/edge_main.py` — main loop (5-min tick)
- `agents/edge/edge_config.py` — knobs (now sourced from `agent_strategies.json`)
- `agents/edge/edge_oanda.py` — OANDA wrappers
- `dashboard/edge_learning_log.json`
- `dashboard/edge_portfolio.json`

## Tunable knobs
All sourced from `dashboard/agent_strategies.json` `"edge"` block:
`MAX_DAILY_LOSSES` (5), `MAX_DAILY_LOSS_PCT` (2.0), `TP1_PTS` (15),
`TP2_PTS` (25), `UNITS` (2), `MARKET_OPEN_BLACKOUT_MIN` (15).
See [[../infrastructure/config]].

## Schedule
Continuous 5-min loop. See [[../infrastructure/cron-schedule#edge]].

## Cross-agent connections
- Reads: [[_retired/jarvis|jarvis]], [[lens]], [[_retired/norman|norman]], H4 read pipeline
- Reports to: [[_retired/norman|norman]] (validation), [[victoria]] (daily ledger)
- Wraps Telegram via: [[huncho]]

## Strategy detail
Full writeup in [[../strategies/edge-1h-crossover]].

## Known issues

### OANDA 403 — RESOLVED 2026-06-02
Edge was rejected with `V20Error "The provided request was forbidden."` on
every account-scoped call because the original `oanda:default` token was
authorised only for account 001, not the Scalper account 002 Edge trades
on. Jase rotated the practice token with both sub-accounts (001 + 002)
ticked; new token swapped into `oanda:default` across the four
`auth-profiles.json` files and `edge.service` restarted to pick it up.
First post-rotation tick (19:05 UTC) clean — no 403/forbidden/V20Error
events. Edge is live for the first time. No `oanda:scalper` profile was
needed; `oanda:default` now covers both accounts. See CLAUDE.md §7
decision log and [[../sessions/2026-06-02#closing-update-1905-utc]].
