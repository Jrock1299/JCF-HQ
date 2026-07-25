# Phantom Build — Placeholder

**Status:** PLACEHOLDER. [[../agents/_benched/phantom|Phantom]] is parked
pending a collaborative, data-driven design pass.

## Why this note exists
When Phantom rebuilds, the design spec — thesis, entry rules, position
sizing, stops, validation plan — goes here. The vault is the second brain;
strategy design lives next to the rest of the operating knowledge.

## What to fill in when design starts

### Thesis
What's the edge? What inefficiency does Phantom exploit? Be specific.

### Instruments / venue
Futures, but which contracts? CME? OANDA CFDs? Need:
- Tick size and tick value per contract
- Margin requirements
- Trading hours (overlap with Blade sessions or distinct?)

### Entry rules
The trigger — needs to be deterministic enough that a backtest can replay it.

### Position sizing
Same rails as Blade D3 enforce:
- ≤ 1% risk per single trade
- ≤ 2% per cluster
- -4% daily DD circuit breaker
- Compounding off current balance
- Min R:R ≥ 1.5 : 1 overall

Use [[../infrastructure/config|`agent_strategies.json`]] for tunable knobs.

### Stops + exits
Structural (level-based) or volatility (ATR-based)? Trailing logic?

### Validation plan
Before any deployment:
1. Backtest ≥ 5 years AND ≥ 2 distinct regimes
2. Parameter sensitivity sweep ±15-30% — must stay profitable
3. Execution friction modeling (1.5-2× claimed slippage)
4. Walk-forward / out-of-sample validation
5. [[../agents/norman|Norman]] runs Monte Carlo, must PASS before paper deploy
6. Paper trade until ≥ 100 closed clusters
7. Norman re-validates → only then live

### Team context wiring
When implemented, Phantom plugs into the same Phase 1 observation layer as
[[../agents/blade]] / [[../agents/edge]] / [[../agents/jerry]]:
- Reads [[../agents/_retired/jarvis|jarvis]] regime
- Reads [[../agents/lens]] bias
- Reads [[../agents/_retired/norman|norman]] verdict
- Reads [[../infrastructure/system-architecture#h4-read-pipeline|H4 read]]
- Writes to `dashboard/phantom_learning_log.json`
- Phase 1 logs only; never gates

## Holding pattern
Phantom waits until either:
- Jase identifies a futures-specific edge thesis worth coding
- The Blade / Edge / Jerry learning logs surface a pattern that suggests
  a futures angle (e.g. specific session/regime where futures lead indices)

## Related
- [[../agents/_benched/phantom]]
- [[../infrastructure/system-architecture#cross-agent-comms-phase-1-3]]
- [[../decisions/decision-log]] (will add the rebuild decision here when it happens)
