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
- [[jarvis]] regime
- [[lens]] bias for SPX500
- [[norman]] verdict on Edge
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
- Reads: [[jarvis]], [[lens]], [[norman]], H4 read pipeline
- Reports to: [[norman]] (validation), [[victoria]] (daily ledger)
- Wraps Telegram via: [[huncho]]

## Strategy detail
Full writeup in [[../strategies/edge-1h-crossover]].

## Known issues

### OANDA 403 — token not authorised for account 002 (open as of 2026-06-02)
Every Edge order is rejected with `V20Error "The provided request was
forbidden."` because the `oanda:default` token in
`agents/main/agent/auth-profiles.json` is authorised only for account
**001** (`101-001-22502524-001`), not the Scalper account **002**
(`101-001-22502524-002`) Edge actually trades on. The token lists 002 via
`/v3/accounts` but per-account calls return 403 — confirmed with curl.

`edge_oanda.py` already prefers an `oanda:scalper` profile if present, but
that profile doesn't exist yet. Fix path:
1. OANDA → *Manage API Access* → regenerate or create a new token with
   account 002 enabled.
2. Add it as `"oanda:scalper"` (api_key, account_id `101-001-22502524-002`)
   alongside `oanda:default`. Edge will pick it up automatically.

Until then, signals fire but no orders place. See
[[../sessions/2026-06-02#1-edge-oanda-orders-forbidden-diagnosed-blocked-on-token]].
