# ⚠️ Norman — Risk Validator

> 🪦 **RETIRED 2026-07-25 — merged into Lens/Victoria.**
> **Absorbed by:** [[../lens]] (Blade, Edge) and [[../victoria]] (Jerry, Chad) — pipeline in `scripts/risk_validation.py`
> **What moved:** Monte Carlo simulation, the sample-size gate, verdict synthesis.
> Code archived in place at `agents/norman/` (see `RETIRED.md` there).
> Cron lines held permanently (`#HOLD RETIRED`), not deleted. History preserved.
> The note below is kept as the historical record of how this agent worked.



**Internal id:** `norman`
**Role:** Monte Carlo strategy validator for every trading agent
**Status:** RETIRED 2026-07-25 (see banner above)
**Voice:** Brutally honest, cold, calculated. Named after the strategist
from *The Promised Neverland*. Doesn't coddle.

## What Norman does
Every Saturday at 10:00 UTC, loads closed trades for each active agent and
runs 10,000-simulation Monte Carlo on the P&L series. Produces per-agent
verdicts + portfolio-level assessment + actionable recommendations.

## Skill methodology baked into prompt
- `backtest-expert` — 6 phases:
  1. Hypothesis stated and rule-codified
  2. Initial backtest spans ≥5 years AND ≥2 distinct regimes
  3. Parameter sensitivity: vary key knobs ±15-30%; require PnL stays positive
     across the sweep. Narrow peak = OVERFIT — call it out.
  4. Execution friction: assume 1.5-2× claimed slippage and commissions
  5. Out-of-sample / walk-forward validation
  6. Score 5 dimensions (Sample Size, Expectancy, Risk Management,
     Robustness, Execution Realism) 0-100
  Verdict: DEPLOY (survives all), REFINE (sound logic), ABANDON (fragile).
- `position-sizer` — Fixed Fractional ≤1% default; ATR-based for varying vol;
  HALF KELLY only (never full); portfolio heat ceiling 6-8%; flag any
  combination breaching the rails.

## Verdict rules (the math)
- Minimum 20 trades before any verdict (else INSUFFICIENT_DATA)
- Probability of ruin > 10% → FAIL
- Sharpe < 0.5 → FAIL
- Profit factor < 1.2 → MARGINAL
- Profit factor > 1.5 → STRONG
- Recent 10 trades diverge >2 std from overall → FLAG

## Key files
- `agents/norman/norman_brain.py` — main analyzer (~1100 lines)
- `agents/norman/run_norman.sh` — cron launcher with `.env` source fix
- `dashboard/norman_report.json` — latest verdicts (consumed by [[blade]],
  [[edge]], [[jerry]], [[victoria]])
- `logs/norman_history.json` — historical reports
- `logs/norman_api_costs.json` — cost tracking

## Tunable knobs
From `dashboard/agent_strategies.json` `"norman"` block:
- `MIN_TRADES_FOR_VERDICT` = 20
- `RUIN_DRAWDOWN_PCT` = 0.50 (50% drawdown = ruin)
- `DOUBLE_TARGET_PCT` = 1.00 (100% gain = doubled)

## Schedule
`0 10 * * 6` (Saturday 10:00 UTC).

## Cross-agent connections
- Reads: trade histories from [[blade]], [[edge]], [[jerry]] (and [[crisp]]
  when it returns from parking)
- Read by: [[blade]], [[edge]], [[jerry]] at session/cycle start (verdict
  ride-along), [[victoria]] (folded into daily report)
- Wraps Telegram via: [[huncho]]

## Recent verdicts (last run 2026-06-01)
- **Blade**: FAIL — 53.3% WR but PF 1.114 and max DD 72.9% on the old TP
  structure. Triggered the [[../strategies/blade-d3-sizing|D3 redesign]].
- **Crisp**: INSUFFICIENT_DATA (n=6)
- **Edge**: INSUFFICIENT_DATA (n=0 post-reset)

## Model routing
`openai/gpt-5.6-terra` via the Codex runtime — **migrated 2026-07-24** off the
Anthropic SDK to Lucy's `openclaw agent` subprocess pattern (`_run_codex`), then
bumped 5.5→5.6 Terra the same day. No tools, so it ported cleanly; the system
prompt is prepended into the user message (the gateway agent has no `system`
slot). Test runs (both 5.5 and 5.6-terra) confirmed the cold voice survives and
the report JSON schema is unchanged. No longer draws on `ANTHROPIC_API_KEY`.
Note: the override must be a **plain** tier id (`openai/gpt-5.6-terra`) AND be
whitelisted in `agents.defaults.models`; the `-codex` suffixed ids are
runtime-bound and rejected as overrides. Sol 400s on this backend. See
[[../sessions/2026-07-24]].

## Phase 2 role (upcoming)
Once Blade's `blade_learning_log.json` hits 100 closed records, Norman will
validate buckets (regime × alignment × Norman-verdict × ORB-quality) before
any Phase 2 gating wire goes live. See
[[../infrastructure/system-architecture#cross-agent-comms-phase-1-3]].
