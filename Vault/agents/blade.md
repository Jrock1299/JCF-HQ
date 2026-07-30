# 🔪 Blade — Primary Trading Agent

**Internal id:** `blade`
**Role:** Pure 15-minute Opening Range Breakout (ORB) bot
**Status:** Active on paper. Reset 2026-06-01 to $5,000. Awaiting [[norman|Norman]]
100-cluster D3 validation before any live deployment.
**Voice:** Stoic, military report format. "LONG SPX500 @ 7600 | SL 7582 | TPs 1R/2R/TRAIL"

## What Blade does
3-session ORB on three instruments. First M1 candle close beyond the
session's 15m ORB level wins. Enters a 3-position cluster sized off the
**real** stop distance (not a fixed buffer). TPs and trailing logic from
[[../strategies/blade-d3-sizing|D3]].

## Sessions (UTC, Mon–Fri)

| Session | Cron  | Open  | Close | Instruments                    |
|---------|-------|-------|-------|--------------------------------|
| ASIA    | 23:50 | 00:00 | 06:00 | SPX500_USD                     |
| LONDON  | 07:55 | 08:00 | 12:00 | SPX500_USD, DE30_EUR, CHF_JPY  |
| NY_PM   | 17:55 | 18:00 | 21:00 | SPX500_USD                     |

## D3 sizing in one line
Per-cluster risk = 2% of current balance; weighted 20/30/50 across pos1/2/3;
TPs at 1R / 2R / trailing; pos3 trail = 1R below high-water once pos1 fires.
Full math in [[../strategies/blade-d3-sizing]].

## Rails (HARD)
- ≤ 1% risk on any single trade (pos3 = exactly 1% at the design's weight cap)
- ≤ 2% risk per cluster
- -4% daily drawdown circuit breaker (halts remaining sessions today)
- Min balance floor: $100 (refuses to trade below)

## Compounding
Balance persists in `dashboard/blade_balance.json` between sessions.
Defaults to $5,000 if missing. Reloaded at session start; saved at session
end **and** on every monitor-loop tick (~30 s) **and** on SIGTERM/SIGINT,
so a cron `timeout` kill mid-session can't lose accrued gains.
See [[../strategies/blade-d3-sizing#compounding-persistence]] and
[[../sessions/2026-06-02#3-blade-balance-json-never-created-fixed]].

## Team context (Phase 1 — observation only)
At session start, Blade reads:
- [[lens]]'s `market_bias.json` for macro bias per instrument
- [[_retired/jarvis|jarvis]]'s `strategy_recommendation.json` for regime per instrument
- [[_retired/norman|norman]]'s `norman_report.json` for the latest verdict on Blade itself
- [[../infrastructure/system-architecture#h4-read-pipeline|H4 read]] per instrument

These ride along on every closed position into `blade_learning_log.json` as
`regime_at_entry`, `lens_bias_at_entry`, `strategist_aligned`,
`norman_verdict_at_entry`, `h4_read_at_entry`. **Blade does not gate on any
of this yet** — see [[../infrastructure/system-architecture#cross-agent-comms-phase-1-3|Phase 1/2/3]].

## Key files
- `agents/blade/bot/blade_bot.py` — D3 engine
- `agents/blade/bot/run_session.sh` — cron wrapper
- `agents/blade/bot/blade_learning_analyzer.py` — Phase 1 stub (not active)
- `dashboard/agent_strategies.json` (`"blade"` block) — all tunable knobs
- `dashboard/blade_balance.json` — compounding state
- `dashboard/blade_learning_log.json` — Phase 1 dataset

## Schedule
See [[../infrastructure/cron-schedule#blade]]. Three sessions weekdays plus
prep pings 10 min before each.

## Cross-agent connections
- Reads: [[lens]], [[_retired/jarvis|jarvis]], [[_retired/norman|norman]], H4 read pipeline
- Reports to: [[victoria]] (daily ledger), [[_retired/norman|norman]] (weekly validation)
- Wraps Telegram via: [[huncho]]

## Decision context
- Why D3 was built: [[../decisions/decision-log#blade-d3-redesign-2026-06-01]]
- Why team context is observation-only: [[../infrastructure/system-architecture#cross-agent-comms-phase-1-3]]
- Session reset 2026-06-01: balance, P&L, trade history all cleared. See
  [[../sessions/2026-06-01]].

## Known issues
- *(resolved 2026-06-01)* CHF_JPY and DE30_EUR P&L conflated price-increment
  with USD-per-unit-per-pip. Now split: `PIP_VALUE` keeps its pip-size role
  for stop placement, and a new `usd_per_pt_per_unit(instrument)` helper
  resolves USD value via live OANDA mid (EUR_USD for DE30_EUR;
  `1/USD_JPY` for CHF_JPY). FX rate is locked in at entry time per position
  so attribution isn't smeared by intraday FX drift. **Accounting only** —
  entry/exit/sizing logic untouched.
  See [[../strategies/blade-d3-sizing#usd-pl-conversion]] and
  [[../sessions/2026-06-01]] for the change record.

## Zero trades 2026-07-28 → 07-30 — shared DD breaker, not "no setup"

The turtle executor logged **203 decisions and 0 orders** in its first two days.
83% of those decisions were `DAILY_DD_HALTED`; the strategy was only allowed to
evaluate a setup 8 times. This was never mean reversion failing to fire.

**Root cause.** Blade and Edge run the same `live_turtle_executor.py` on the same
`*/15` cron minute against **different OANDA books** — `…-001` at $2,000 (Blade)
and `…-002` at $5,000 (Edge) — but the daily-drawdown state file was keyed only
by UTC date. Whichever agent ticked first wrote its own balance as
`day_start_balance`; the other measured its genuinely different balance against
that foreign anchor:

```
(2000 - 5000) / 5000 = -60%  ->  breaches the -4% rail  ->  halted
```

The halt is a day-scoped latch, so one crossed wire stopped **both** agents for
the rest of every UTC day, ~10 seconds after the first tick.
`dashboard/live_turtle_balance.json` was shared the same way.

**Fix.** Both files are keyed on the **OANDA account id** (`_book_key()`), not
the agent name — *one daily-drawdown rail per book*. Two agents on one account
should share a rail (same money); two agents on separate accounts must not.
Verified: each book anchors to its own balance, neither halts the other, and the
rail **still bites** (-5% halts and latches, the other agent unaffected).

A further 10% of ticks were OANDA 401s from token burst-contention on the same
cron minute — now retried via `scripts/oanda_retry.py`.

First-fire Telegram alerts never triggered, which was **correct**: the monitor
only fires on `SIGNAL_FIRED` and no order existed. It is healthy and armed.

See [[../sessions/2026-07-30]].
