# 🌐 Lens — Macro Analyst

**Internal id:** `lens`
**Role:** Daily macro briefing across BTC, XAU, US100, SPX500, US OIL
**Status:** Active
**Voice:** Macro analyst — measured, sources its claims.

## What Lens does
Every morning at 04:55 UTC, calls `claude-sonnet-4-6` with the `web_search`
tool to gather the latest news + analysis for each tracked pair. Produces:
- Bias (bullish/bearish/neutral) + confidence (0-100) per pair
- Market impact lines (which assets get hit, which way)
- Watchlist + discovery calculations (cross-references [[sentinel]])
- Earnings calculations (beat/miss scenarios)
- 1-3 sentence summary + 3-5 sentence morning report + 5 priorities

Writes everything to `dashboard/market_bias.json` — **the file every
downstream agent reads**.

## Skill methodology baked into prompt
- `market-news-analyst` — impact scoring formula `(Price × Breadth) × Forward`:
  - Price impact tier: severe ±2% eq / ±5% comm = 10 pts; significant 1-2% = 5; modest <1% = 2
  - Breadth multiplier: systemic ×3, cross-asset ×2, sector ×1.5, single-stock ×1
  - Forward modifier: ±50% based on leading vs lagging
  - Rank by score, not chronology
- `market-environment-analysis` — 4-dimension scan: TREND, RISK SENTIMENT,
  VOLATILITY (VIX-banded), SECTOR ROTATION. Tie regional/asset biases back
  to the broader regime. Note conflicts.

See [[../infrastructure/model-routing]] for skill integration approach.

## Pairs covered
- BTC/USDT
- XAU/USD (Gold)
- US100 (Nasdaq)
- SPX500
- US OIL (WTI)

## Confidence rules
- 75+: strong conviction, clear directional signals
- 50-74: moderate, mixed signals
- <50: use neutral, flag conflicts in the note

## Key files
- `agents/lens/lens_brain.py` — the only live entrypoint
- `agents/lens/run_lens_brain.sh` — cron launcher (has `.env` source fix)
- `dashboard/market_bias.json` — downstream consumers all read this

## Schedule
`55 4 * * 1-5` (04:55 UTC weekdays, before all trading sessions).

## Cross-agent connections
- Reads: [[sentinel]] (watchlist signals fold into Lens's calculations)
- Read by: [[blade]], [[edge]], [[jerry]], [[_retired/jarvis|jarvis]], [[victoria]], the
  Intelligence dashboard, every Telegram briefing
- Wraps Telegram via: [[huncho]]

## Model routing
`claude-sonnet-4-6` with web_search. Needs `.env` sourced before launch —
the `set -a / source .env / set +a` block is in `run_lens_brain.sh`. See
[[../infrastructure/model-routing#env-auth-fix]].

## Related decisions
- Bot directory (`bot/run_lens.sh`) deprecated 2026-04 in favor of `lens_brain.py`.


## Absorbed 2026-07-25 (consolidation)

Lens took over two functions when [[_retired/jarvis|Jarvis]] and
[[_retired/norman|Norman]] were retired:

### Regime briefing (from Jarvis)
`agents/lens/lens_regime.py` + `run_lens_regime.sh`. Two runs/day (06:00
pre-London, 12:00 pre-NY) — kept **separate** from Lens's 04:55 macro thesis,
because a 04:55 regime read is ~7h stale by the NY open. Writes
`dashboard/strategy_recommendation.json` — a **frozen 5-consumer contract**
([[blade]], [[edge]], [[jerry]], Crisp, hq-app). New keys additive only.
Adds a Multi-Timeframe Convergence read (0-100, **observation only, never a
gate**) and the Time-Based Edge Map.

### Risk validation for Blade + Edge (from Norman)
`agents/lens/lens_validator.py`, importing Norman's pipeline from
`scripts/risk_validation.py` — Monte Carlo, the sample-size gate, verdict
synthesis. Writes `dashboard/lens_validation.json`. The deterministic gate
outranks the LLM: `--test-gate` proves it.

⚠️ Both are `#HOLD PENDING-APPROVAL` in cron as of 2026-07-25.
