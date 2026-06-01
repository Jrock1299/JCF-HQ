# Phantom — Parked (Strategy Build Pending)

**Internal id:** `phantom`
**Status:** **Parked** — awaiting strategy build. systemd service
`phantom.service` currently `inactive`.

## What Phantom was
Autonomous orchestrator for a futures strategy. 5-min tick cycle (fetch
market data, evaluate strategy conditions, manage positions).

## Why parked
Halted around 2026-05-08. The previous strategy (whatever it was) was
deprecated. Awaiting a **new strategy build** — collaborative, data-driven
design pending more context accumulation (and a specific edge thesis).

## What's preserved
- `agents/phantom/phantom_main.py` — orchestrator scaffold
- `logs/phantom_api_costs.json` — historical API spend
- `dashboard/phantom_portfolio.json` — empty/stale portfolio file

## Revival path
1. Jase identifies the edge thesis (likely after more data accumulates in
   [[../blade]] and [[../edge]] learning logs — those may surface patterns
   that suggest a futures angle)
2. Strategy spec written → backtested in [[../../strategies/phantom-build|placeholder strategy note]]
3. [[../norman|Norman]] validates the backtest
4. Paper deploy first, live only after the validation gate

## Key files (parked)
- `agents/phantom/phantom_main.py`
- `dashboard/phantom_portfolio.json`

## Cross-agent context
- No live dependencies. When Phantom returns it'll plug into the same
  [[../../infrastructure/system-architecture#cross-agent-comms-phase-1-3|Phase 1 comms layer]]
  as Blade / Edge / Jerry.

## Placeholder strategy note
[[../../strategies/phantom-build]] — currently a stub. Fill in when design
work begins.
