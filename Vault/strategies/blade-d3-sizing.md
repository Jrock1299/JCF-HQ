# Blade D3 Sizing Redesign

**Adopted:** 2026-06-01
**Verdict it addressed:** [[../agents/norman|Norman]] FAIL on Blade —
PF=1.114, max DD=72.9%, expectancy $0.11/trade.

## The problem (what was broken)

Norman flagged Blade's old structure as failing despite a healthy 53% WR.
Two compounding root causes:

### 1. Inverted R:R on positions 1 and 2
Empirical from 287 backed-up positions, isolated to SPX500:
- Average ORB stop distance: **~11.4 pts** (derived from full-SL clusters
  averaging -$68.22 ÷ 6 units)
- Old TPs: pos1 = +3pt, pos2 = +5pt, pos3 = +10pt
- Old R:R: **0.26 / 0.44 / 0.88** — sub-1R on TWO of three positions
- Avg winner $18.71, avg loser $26.10 — losers 39% larger than winners
- Cluster-level PF on SPX500 alone: **0.34** (losing strategy when XAU and
  the rare TRAIL outcomes were stripped out)

The strategy only survived because the rare big runner (3 historical TRAIL
records averaging +$282.50 each) carried the losers.

### 2. Sizing bug
Old code: `units = int(risk_amount / (SL_BUFFER_POINTS × pip_val) / 3)`.
This used the 3-point SL **buffer** as the divisor — but actual risk is
the full stop distance (ORB-opposite ± buffer = typically 12pt+). Real
per-cluster risk was running ~3-4% of balance against an intended 1%.

## D3 — the design

### Stop placement
**Structural**, anchored to the ORB level:
```
Long:  stop_loss = orb_low  - SL_BUFFER_POINTS × pip_value
Short: stop_loss = orb_high + SL_BUFFER_POINTS × pip_value
```
`SL_BUFFER_POINTS = 3` (a few ticks beyond the level to absorb wicks).
`stop_pts` is the actual distance from entry to stop — used for sizing.

### Risk budget
Per cluster = **2% of current balance** (compounding). Split by weights:

| Position | Weight | $ risk @ $5k | TP | R:R |
|----------|--------|-------------|----|-----|
| pos1 | **20%** | $20 | 1R | 1.0 : 1 |
| pos2 | **30%** | $30 | 2R | 2.0 : 1 |
| pos3 | **50%** | $50 | trailing | 3R+ typical |

### Sizing math
`units = int(per_pos_risk_$ / (stop_pts × pip_value))`

Uses real stop distance — the bug is fixed. Unit rounding always lowers
actual risk vs target (never increases), so rails stay honored.

### Trailing pos3
Activates **after pos1 fires** (BE-after-pos1 mechanic preserved):
- pos2 SL moves to entry (BE)
- pos3 SL moves to entry AND starts trailing
- Trail distance: `POS3_TRAIL_DISTANCE_R × stop_pts` (1R = same as stop)
- On every tick: if price advances past high-water mark, raise SL to
  `high_water - trail_distance`
- pos3 closes when price reverses to the trailed SL → outcome label `TRAIL`

### Cluster R:R math
- **Best-case** (all 3 hit + trail averages 5R historically):
  reward = 0.4 + 1.2 + 5.0 = 6.6R, risk = 2.0R → **3.3 : 1**
- **All-TP without trail** (cap at 3R on pos3):
  reward = 0.4 + 1.2 + 3.0 = 4.6R, risk = 2.0R → **2.3 : 1**
- Worst-case (all SL): -2R = -2% of balance (= the per-cluster rail)

## Rails (HARD)

| Rail | Mechanism |
|---|---|
| ≤ 1% risk per single trade | `POSITION_WEIGHTS['pos3'] = 0.50 × 0.02 = 0.010` |
| ≤ 2% cluster risk | `RISK_PCT_PER_CLUSTER = 0.02`; weights sum to 1.0 |
| -4% daily DD circuit breaker | `dashboard/blade_dd_<date>.json` tracks daily cum_pnl; halts remaining sessions today once breached |
| Compounding off current balance | `dashboard/blade_balance.json` reloaded at session start, saved at session end. Default $5,000 if missing. |
| Min R:R ≥ 1.5 : 1 overall | D3 best-case = 3.3:1 ✓ |
| Min balance floor $100 | Refuses to trade below |

## Backtest — Monte Carlo (100 sims × 250 clusters)

Hit-rate decay calibrated from real data (67% hit at 3pt → 36% at 10pt → fitted
power-law α = 0.52):

| Design | Final bal avg | Avg/cluster | PF | WR | Max DD | Ruin |
|---|---|---|---|---|---|---|
| CURRENT (3/5/10 equal-weight, broken sizing) | $4,525 | -$1.90 | 0.92 | 67% | 25% | 3% |
| D1: 1R/2R/3R equal-weight | $3,780 | -$4.88 | 0.89 | 34% | 45% | 27% |
| D2: 0.75R/1.5R/3R equal-weight | $3,744 | -$5.02 | 0.88 | 39% | 42% | 16% |
| **D3: 1R/2R/trail, 20/30/50 weights** | **$20,166** | **+$60.67** | **1.54** | 34% | **25%** | **0%** |

**D3 wins** because the weighted sizing puts capital on the runner (50% of
risk on pos3), preserving the historical edge that lives in the rare big
moves. Equal-weight + wider TPs (D1, D2) actually make things worse — the
wider TPs cut hit rate faster than the bigger wins compensate.

## Honest caveats (carried forward)
- Hit-rate decay is an estimate from 3 calibration points. Could go either way.
- pos3 trail averages were +5R historically — but n=3 samples, all XAU,
  zero SPX500 in the priors. The thinnest assumption in the design.
- Every pos3 trail outcome is logged with `pos3_trail_r_achieved` in
  `dashboard/blade_learning_log.json` — gives [[../agents/norman|Norman]]
  clean data on the exact assumption the design depends on.

## Tunable knobs
All in `dashboard/agent_strategies.json` `"blade"` block. See
[[../infrastructure/config]].

```json
"blade": {
  "RISK_PCT_PER_CLUSTER":      0.02,
  "POSITION_WEIGHTS":          {"pos1": 0.20, "pos2": 0.30, "pos3": 0.50},
  "TP_R_MULTIPLES":            {"pos1": 1.0,  "pos2": 2.0,  "pos3": null},
  "POS3_TRAIL":                true,
  "POS3_TRAIL_DISTANCE_R":     1.0,
  "DAILY_DD_HALT_PCT":         0.04,
  "SL_BUFFER_POINTS":          3,
  "MIN_BALANCE":               100.0,
  "STARTING_BALANCE_DEFAULT":  5000.0
}
```

## Phase 2 gate — what Norman will validate
Once `blade_learning_log.json` accumulates 100+ closed records:
- Bucket trades by regime × strategist_aligned × Norman-verdict × ORB-quality
- Require ≥ 30 trades per bucket before claiming a pattern
- Require MC p5 > 0 for any bucket that wants to become a soft filter
- Only after Norman PASS does a separate explicit PR wire the pattern into
  Blade as a sizing modifier (NEVER a hard binary gate)
- See [[../infrastructure/system-architecture#cross-agent-comms-phase-1-3]]

## Related
- [[../agents/blade]] · [[../agents/norman]] · [[orb-strategy]]
- [[../decisions/decision-log#blade-d3-redesign-2026-06-01]]
- [[../sessions/2026-06-01]]
