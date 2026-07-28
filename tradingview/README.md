# TradingView indicators

Pine v5 ports of JCF HQ strategies. **Ports, not sources of truth** — if the
Python code and Pine code disagree, the Python is authoritative
(`agents/lens/ict_strategies.py`, `agents/lens/ict_backtest.py`,
`dashboard/strategy_library.json`). Every Pine file here MUST be updated
in the same PR as any material change to the underlying Python strategy.

## Files, by validation status

### ✅ Validated (trade-signal quality — same-basis PASS)

- **`meanrev_sweep_fade.pine`** — the validated post-sweep-fade strategy
  (library id `ict.turtle_soup.{SPX500_USD, DE30_EUR, XAU_USD}`,
  `deployable=true`). Green arrows, standard colours. This is the same
  signal the Blade + Edge live-paper executors trade. Use on the
  `OANDA:*` symbols listed in the file's header.

### ⚠️ BETA / research-only (NOT validated on futures)

- **`sweepfade_ES.pine`** — beta port for CME e-mini S&P (CME_MINI:ES1!)
- **`sweepfade_NQ.pine`** — beta port for CME e-mini Nasdaq (CME_MINI:NQ1!)
- **`sweepfade_GC.pine`** — beta port for COMEX gold (COMEX:GC1!)

All three are **identical rule set** to `meanrev_sweep_fade.pine`, but on
futures data the strategy grades **MARGINAL at M15** (PF 1.22-1.28 vs the
1.5 PASS floor) — 60d of free yfinance data was too thin to confirm the
edge on the strategy's validated timeframe. H1 "passes" are at the
wrong timeframe and don't count.

**Do not trade signals from these on Jase's live Lucid eval.** They exist
so eyeballs can be gathered on whether the arrows actually print at real
reversal points — the visual gating step before spending money on paid
CME M15 tick data (Databento / Polygon) to close the same-basis
validation. Every alert message includes "BETA — research only" so a
phone push can't be mistaken for a validated signal, and every file
plots signals in **orange** rather than green/red so they're visually
distinct on-chart.

Full grade evidence: `dashboard/futures_validation.json`.

## How to install (one-time)

1. TradingView → open a chart on the symbol listed in the file's header
   (each `.pine` file's header block lists its intended TV symbol).
2. Bottom of chart → **Pine Editor** tab.
3. Paste the entire contents of the `.pine` file into the editor.
4. **Save** (give it a descriptive name), then **Add to Chart**.
5. To enable phone / email alerts: right-click the indicator → **Add Alert…**
   → pick the "BUY" or "SELL" alert condition from the Condition dropdown.
   Set frequency to **Once Per Bar Close** (not "Once Per Bar") — otherwise
   you'll be alerted before the bar closes and could act on a signal that
   hasn't confirmed yet.

## No-repaint guarantee

Every `.pine` file includes a header block explaining exactly which
mechanisms it uses to avoid repainting:
1. `barstate.isconfirmed` gate on every signal
2. `ta.pivothigh(k, k)` / `ta.pivotlow(k, k)` with the confirmation delay
3. `request.security(..., barmerge.lookahead_off)` for HTF bias

The signals print at the same bar the Python backtest would have entered —
not shifted forward after the fact. If you compare a live signal to the
same signal 10 bars later, it must be at the same bar.

## TradingView symbol mapping

| Pine file                     | TV symbol            | Status              |
|-------------------------------|----------------------|---------------------|
| `meanrev_sweep_fade.pine`     | `OANDA:SPX500USD`    | ✅ Validated (live) |
| `meanrev_sweep_fade.pine`     | `OANDA:DE30EUR`      | ✅ Validated (live) |
| `meanrev_sweep_fade.pine`     | `OANDA:XAUUSD`       | ✅ Validated (live) |
| `sweepfade_ES.pine`           | `CME_MINI:ES1!`      | ⚠️ BETA (M15 MARGINAL) |
| `sweepfade_NQ.pine`           | `CME_MINI:NQ1!`      | ⚠️ BETA (M15 MARGINAL) |
| `sweepfade_GC.pine`           | `COMEX:GC1!`         | ⚠️ BETA (M15 MARGINAL) |

Prefer the exact symbol listed. In particular the OANDA validated files
are best used on OANDA feeds — the Python backtest ran against OANDA
practice data, so the fine-grained bar timing matches.
