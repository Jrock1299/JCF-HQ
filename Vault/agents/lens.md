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

## Reporting fixes — 2026-07-30

Two defects in the regime briefing path, both live since 2026-07-28.

### Debug output leaked into Telegram
When Codex hit its subscription limit (2026-07-27, resets Aug 23) both
`gpt-5.6-terra` and `gpt-5.5` began returning 429 and the chain fell through to
`openrouter/auto`. That path **works**, but emits `[provider-transport-fetch]`
transport lines before the metadata block — and `call_codex()` stripped the
header by breaking on the first unrecognised line, so it broke at line 0 and
returned the whole stdout as "the narrative". Six briefings shipped that way.

Fixed at the destination (`scripts/output_sanitizer.py`, applied inside
`telegram_personalities.wrap_message()` so every agent is covered) **and** at
the source (`call_codex` now scans every line and logs what it filtered). See
[[../infrastructure/personalities]] and [[../sessions/2026-07-30]].

### "Data unavailable" on SPX/DE30/XAU was throttling, not auth
At 12:00 UTC the briefing shares one OANDA practice token with Blade's and
Edge's turtle ticks on the same cron minute. OANDA answers part of that burst
with **401 "Insufficient authorization"** — which reads like an auth failure and
isn't one; the same credential returns 200 minutes later. A single-shot fetch
turned the blip into a whole instrument going dark for the session.
`scripts/oanda_retry.py` adds bounded retry on transient markers only. A run
that genuinely cannot get data still reports the gap honestly (Rule #9).

### Three messages a day is by design
04:55 macro thesis + 06:00 pre-London regime + 12:00 pre-NY regime. There are no
duplicate cron entries; the appearance of a malfunction came from two of the
three being garbage. A per-slot lock
(`/tmp/lens_regime_sent_<date>-<hour>.lock`) now makes a double-fire physically
unable to send twice — no lock is written on failure, so genuine retries still
deliver. Override with `LENS_REGIME_FORCE_SEND=1`.
