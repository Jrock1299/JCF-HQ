# ♟️ Jarvis — Strategy Architect (formerly Strategist)

**Internal id:** `strategist` (display name aliased to JARVIS via `AGENT_DISPLAY`)
**Role:** Pre-session market regime briefing twice daily + Saturday deep backtest
**Status:** Active
**Voice:** Calm, precise, intelligent right-hand-man. Composed. Subtly
confident. Three steps ahead but never showy. Warm enough that the trader
trusts him, economical enough that every sentence carries weight. Signs
every briefing `— Jarvis`.

*Example: "Morning read is in. SPX is range-bound, Lens is neutral. I'd
keep expectations measured today. — Jarvis"*

## What Jarvis does
Briefs the trader on market regime before each session. **Does NOT pick
strategies. Does NOT gate trades.** [[blade]] and [[edge]] execute on their
own rules; Jarvis briefs the trader and logs context.

### Two briefings per day
- Pre-London (`0 6 * * 1-5`)
- Pre-NY (`0 12 * * 1-5`)

### One deep backtest per week
- Saturday `0 8 * * 6` runs `deep_backtest.py` against 5 strategies on H1/M15
  history. Uses `oandapyV20` + `ccxt` (both installed in `/root/.openclaw/venv/`).

## Output
- `dashboard/strategy_recommendation.json` — per-instrument
  `{regime, bias, lens_bias, lens_confidence, adr, current_price}` +
  overall regime + Monte Carlo block. Consumed by [[blade]], [[edge]],
  [[jerry]] as observation context.
- `agents/strategist/pre_session_notes.md` — the Codex narrative briefing
  text (delivered to Telegram)

## Skill methodology baked into prompt
- `macro-regime-detector` — 1-2 year structural regimes from cross-asset
  ratios: Concentration / Broadening / Contraction / Inflationary /
  Transitional. Mentioned only when it conflicts with the tactical read.
- `market-breadth-analyzer` — 0-100 composite from 6 components, exposure
  guidance per zone. Flag weakening breadth (<40) as risk-on-the-margin.
- `sector-analyst` — cycle position from sector leadership. Cyclical lead
  (XLF/XLI/XLY) = risk-on; defensive lead (XLP/XLU/XLV) = late cycle.

## What was removed 2026-06-01
The pre-trade engine was trimmed from 1042 → 446 lines. Removed dead code
that no trading agent read:
- 0-100 convergence score
- Strategy-selection logic (orb / sweep_fade / breakout_expansion / etc.)
- Fair Value Gap detection
- Liquidity-level detector
- All TRADE/SKIP recommendation outputs

Edge map functions (`build_edge_map`, `is_in_top_window`) retained — only
because `deep_backtest.py` uses them.

Why the trim: Blade v5 explicitly ignores any score; [[../agents/_benched/crisp|Crisp]]
is parked. See [[../decisions/decision-log#jarvis-strategist-trim-2026-06-01]].

## Key files
- `agents/strategist/strategy_engine.py` — lean (446 lines)
- `agents/strategist/run_research.sh` — Codex narrative + Telegram delivery
  (uses `--target` flag, not the broken `--to`)
- `agents/strategist/deep_backtest.py` — Saturday weekly
- `agents/strategist/CLAUDE.md` — Jarvis identity + voice
- `dashboard/strategy_recommendation.json`

## Model routing
Codex via `openclaw infer model run --model openai/gpt-5.6-terra` (bumped
2026-07-24 from 5.5; fallback `openai/gpt-5.5` → `openrouter/auto`). Sol would
suit regime reasoning but is unavailable on this Codex OAuth backend (400s), so
Terra is the top working tier. `infer model run` is not gated by the
`agents.defaults.models` allow-list. Older `gpt-5.3-codex` alias retired.
Fallback `openrouter/auto`. Pre-trade engine itself is pure Python.

## Cross-agent connections
- Reads: [[lens]] `market_bias.json` (folded into regime briefing)
- Read by: [[blade]], [[edge]], [[jerry]] at trade/session start
- Wraps Telegram via: [[huncho]]

## Telegram identity
- Emoji: ♟️
- Display header: `JARVIS` (aliased — internal id stays `strategist`)
- Sign-off: `— Jarvis` followed by `— via H`

See [[../infrastructure/personalities]] for the alias system.
