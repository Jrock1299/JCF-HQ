# Edge — 1H SMA 8/21 Crossover

The strategy [[../agents/edge|Edge]] runs continuously on SPX500_USD.

## Signal
A new 1H candle close. Compare SMA(8) vs SMA(21):
- SMA(8) > SMA(21) → bullish cross → consider long
- SMA(8) < SMA(21) → bearish cross → consider short

## Filter (optional)
`USE_H4_FILTER = True` — also require alignment on the H4 timeframe:
- Longs require H4 bullish (SMA8 > SMA21 on H4)
- Shorts require H4 bearish

## Entry
One aggregate market order of `3 × UNITS` (default 2 → 6 units total)
placed at OANDA. Internally tracked as a 3-position cluster:

| Position | TP | SL |
|----------|----|----|
| pos1 | +15 pts | SMA21 at time of entry |
| pos2 | +25 pts | SMA21 at time of entry |
| pos3 | no fixed TP — **trails the 21 SMA** | SMA21 |

## Position management
- Pos1 TP fires → pos2 SL → BE (entry price), pos3 begins trailing the 21 SMA
- Pos3 closes when a 1H candle closes through the 21 SMA in the wrong direction
- Time-stop safety net: force-close any cluster held > 24 hours

## Risk rails
| Rail | Value |
|---|---|
| Max daily losses | 5 losing clusters → halts new entries |
| Max daily DD | -2% → halts |
| Market-open blackout | 15 min after 13:30 UTC (US cash open) |
| Max hold | 24 hours (safety net) |

All tunable from `dashboard/agent_strategies.json` `"edge"` block.

## Why this strategy
- Simple trend-following — easy to validate, hard to overfit
- 1H timeframe filters intraday noise
- The trailing pos3 captures runaway trends; the fixed TPs lock in the
  bread-and-butter
- Limited to SPX500 only — controls scope, lets us measure clean

## Cluster structure parallels Blade
Same 3-position concept as [[blade-d3-sizing|Blade D3]] but the sizing is
**fixed-units** (not R-multiple), the stop is structural (SMA21 not ORB
buffer), and the entry signal is the SMA cross (not an ORB break).

## Edge map (historical context)
Edge accumulated ~2,474 closed positions through 2026-05-18. Cumulative
P&L on $5K starting balance: **-$1,226**. Win rate 30.6% (the 3-position
structure inflates the position count vs the cluster count).

Norman verdict on Edge: **INSUFFICIENT_DATA** post-reset — the strategy
ran on this exact structure but the data set is fragmented across resets.

## Team context (Phase 1 — observation only)
At every cluster entry, Edge calls `_load_team_context()` and stamps:
- [[../agents/jarvis|Jarvis]] regime
- [[../agents/lens|Lens]] bias for SPX500
- [[../agents/norman|Norman]] verdict on Edge
- [[../infrastructure/system-architecture#h4-read-pipeline|H4 read]]

These ride along on every closed trade into `dashboard/edge_learning_log.json`.
No gating. Phase 2 validates patterns once data accumulates.

## Related
- [[../agents/edge]] · [[../agents/_retired/norman|norman]]
- [[../infrastructure/config]] — where the knobs live
