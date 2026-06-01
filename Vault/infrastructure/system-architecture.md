# System Architecture

How JCF HQ's pieces talk to each other.

## Cross-agent comms (Phase 1-3)

The principle: **trading agents SEE shared context but DO NOT GATE on it
during Phase 1.** Everything is logged for later analysis. Patterns get
validated by [[../agents/norman|Norman]] before any gating wire goes live.

### The wire diagram

```
   Lens (market_bias.json)         ─┐
   Jarvis (strategy_rec.json)      ─┼─→  Blade   ─→ blade_learning_log.json
   Norman (norman_report.json)     ─┤    Edge    ─→ edge_learning_log.json
   H4 read (scripts/h4_read.py)    ─┘    Jerry   ─→ jerry_learning_log.json
```

### Phase 1 — NOW
Blade / Edge / Jerry call a context loader at trade entry. Snapshot the
team's view into the trade record AND write a row to the agent's learning
log. **Every entry method, no exceptions.**

Fields stamped on every record:
- `regime_at_entry` (Jarvis)
- `strategist_bias_at_entry` (Jarvis per-instrument)
- `lens_bias_at_entry` + `lens_confidence_at_entry`
- `strategist_aligned` (bool — did the team's bias match trade direction?)
- `norman_verdict_at_entry` (PASS / FAIL / INSUFFICIENT_DATA for that agent)
- `norman_ruin_prob_at_entry`
- `h4_read_at_entry` (compact dict: trend, bias, confidence, swings, regime)

Plus agent-specific:
- Blade: `orb_range_pts`, `stop_pts`, `breakout_distance_pts`, `pos3_trail_r_achieved`
- Edge: `h4_trend`, `entry_sma21`
- Jerry: `lens_overall_at_entry`

**No code in any trading agent reads its own learning log.** Phase 1 is
write-only from a behavior standpoint.

### Phase 2 — gated on Norman validation
Once a learning log accumulates **≥ 100 closed records**:
1. Replace the stub `agents/blade/bot/blade_learning_analyzer.py` (and
   equivalents for Edge / Jerry) with real bucketed analysis
2. Bucket trades by regime × alignment × Norman verdict × ORB quality
3. Require ≥ 30 trades per bucket before claiming a pattern
4. Compute MC p5 per bucket; reject any pattern where p5 ≤ 0
5. Norman runs Monte Carlo on the surviving patterns; emit PASS / REVISE / ABANDON

### Phase 3 — act on validated patterns
Only patterns Norman PASSes go live, and **only via a separate explicit PR**
per pattern. Never a hard binary gate — soft filters or sizing modifiers.
Example shape: "in COMPRESSED regime with Norman FAIL verdict, scale size to
50%; never block entirely."

The structure is intentionally conservative: it takes effort to enable a
new gate. That's the design — we don't want to act on assumed-true patterns
before they're statistically real.

## H4 read pipeline

`scripts/h4_read.py` — text-based 4-hour technical read used by every
trading agent and the session prep ping.

### What it builds
For each instrument:
1. Pulls H4 + D1 OANDA / Binance candles (same fetchers Jarvis uses)
2. Computes indicators: EMA 20/50, ATR(14), ADR(10d), BB squeeze, recent
   swing high/low, prior-day H/L, regime label
3. Asks Codex (`openai/gpt-5.5` primary, `openrouter/auto` fallback) to
   write a clean read using the `technical-analyst` methodology
4. Returns a structured dict: `{narrative, bias, confidence, data, generated_at}`

### Cache
30-min TTL per instrument at `/tmp/h4_reads/h4_<instrument>.json`. So
`session_prep_ping.sh` at T-10min generates the read, Blade reuses the
cached version at T-0.

### Consumers
- `session_prep_ping.sh` — Telegram delivery via [[../agents/huncho|Huncho]]
- [[../agents/blade]] — at session start, logged on every position
- [[../agents/edge]] — at cluster entry, logged on every trade

## Centralized config

Two files in `dashboard/`:

### `agent_strategies.json`
Tunable knobs per agent. Loaded by every agent at startup via
`scripts/agent_config.py:load_strategy(name, defaults)`. Falls back to the
hardcoded defaults if the file or key is missing — **non-breaking by design**.

Blocks:
- `blade` — D3 sizing knobs (see [[../strategies/blade-d3-sizing]])
- `edge` — `MAX_DAILY_LOSSES`, `MAX_DAILY_LOSS_PCT`, `TP1_PTS`, `TP2_PTS`,
  `UNITS`, `MARKET_OPEN_BLACKOUT_MIN`
- `norman` — `MIN_TRADES_FOR_VERDICT`, `RUIN_DRAWDOWN_PCT`, `DOUBLE_TARGET_PCT`
- `sentinel` — `WATCHLIST_PATH` pointer

### `watchlist.json`
Jase's by-theme tickers. Read by [[../agents/sentinel|Sentinel]] with
hardcoded fallback. Themes: `holdings`, `quantum_nuclear`, `energy`,
`metals`, `robotics_ai`, `saudi`, `tech_semis`.

See [[config]] for the full breakdown.

## Secret hygiene

`.gitignore` covers:
- `.env`, `*.pem`, `**/auth-profiles.json`, `openclaw.json`
- `**/credentials/`, `**/plaid_tokens*`, `kalshi_private*`
- `dashboard/plaid_data.json`, `dashboard/hq_userdata.json`
- `identity/device-auth.json`, `**/device-auth.json`
- `**/.aster-keys`, `**/*-keys`
- All `logs/`, `*.log`, `*.bak`, `/tmp/`, `venv/`

**Before every `git push`** run:
```bash
git diff --cached --name-only | grep -E "\.env|\.pem|auth-profiles|openclaw\.json|plaid_data|device-auth|aster"
```

Empty output = safe.

### Known un-scrubbed leak (deferred)
Prior commit `a13e8fe` (2026-05-27) tree still contains
`identity/device-auth.json` (operator token) and `workspace/agents/crisp/.aster-keys`
(Aster API keys). Tracked deletion landed in commit `e91d5e8` (2026-06-01)
but git history retains the values. User opted not to rotate or scrub
history this pass. To scrub later:
```bash
git filter-repo --invert-paths \
  --path identity/device-auth.json \
  --path workspace/agents/crisp/.aster-keys
# then force-push
```
That requires explicit confirmation before running.

## Related
- [[cron-schedule]] — what runs when
- [[model-routing]] — which agent uses which LLM
- [[config]] — central config files in detail
- [[personalities]] — Telegram voice system
- [[../sessions/2026-06-01]] — when most of this was wired up
