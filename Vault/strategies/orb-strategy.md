# 15-Minute Opening Range Breakout (ORB)

The foundational strategy [[../agents/blade|Blade]] runs across three sessions.

## The setup
1. Session opens (00:00 ASIA, 08:00 LONDON, 18:00 NY_PM, all UTC).
2. The first 15-minute candle defines the **opening range** — record its
   high and low.
3. Watch M1 candles after that. The first M1 candle that **closes** beyond
   the ORB high (long) or ORB low (short) triggers entry. First break wins
   per instrument per session.
4. Enter a 3-position cluster (see [[blade-d3-sizing]] for full structure).

## Why this strategy
- Range expansion at session open is a documented edge in futures + forex
- The 15-min window is wide enough to filter noise, narrow enough to
  generate clear levels
- M1 *close* (not wick) is the qualifying event — reduces false breakouts
- One trade per instrument per session caps over-trading risk

## What's NOT this strategy
- Wick-touch breakouts (rejected by design)
- Multiple re-entries after stop-out in the same session
- News-driven setups (Blade doesn't read economic calendars)

## Variants we explored and rejected
The previous Strategist's strategy-selection layer offered 5 variants
(`orb`, `momentum_orb`, `sweep_fade`, `trend_continuation`, `breakout_expansion`)
gated on a 0-100 convergence score. **Blade v5 ignored all of them.** When
we discovered Blade v5 explicitly bypassed Strategist's recommendation, we
deleted the variant selector entirely (2026-06-01). The pure ORB is the
strategy.

## Session-specific notes
- **ASIA** (00:00–06:00 UTC): SPX500 only. Thinner book, but cleaner 15m
  ranges since there's less news. ORB tends to be smaller (~8-15 pts).
- **LONDON** (08:00–12:00 UTC): SPX500 + DE30 + CHF/JPY. The widest
  liquidity window. DE30 ranges run wider (~40-100 pts).
- **NY_PM** (18:00–21:00 UTC): SPX500 only. After the NY close — calmer
  drift, occasional late-day momentum.

## Per-instrument pip definitions
- SPX500: 1 pip = 1 index point, 1 OANDA unit = $1/pt
- DE30: 1 pip = 1 index point, 1 OANDA unit = €1/pt
- CHF/JPY: 1 pip = 0.01 (price terms)
- **Known issue**: `PIP_VALUE` in `blade_bot.py` stores price-increment per
  pip, not USD-per-unit-per-pip. CHF_JPY and DE30 paper P&L slightly
  mis-stated. Fix before live trading.

## Position management (D3)
See [[blade-d3-sizing]] for the full math. Summary:
- pos1 (20% of cluster risk) → TP at 1R
- pos2 (30% of cluster risk) → TP at 2R
- pos3 (50% of cluster risk) → trails 1R below high-water once pos1 fires
- When pos1 TP hits → pos2 SL → BE, pos3 trail activates

## Related
- [[blade-d3-sizing]] — the full sizing redesign with backtest
- [[../agents/blade]] — agent overview
- [[../decisions/decision-log#jarvis-strategist-trim-2026-06-01]] — why
  the strategy-selection variants were deleted
