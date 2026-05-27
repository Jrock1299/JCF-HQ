# CRISP v4 — BTC/USDT Multi-Strategy Framework
**Version:** 4.0
**Updated:** 2026-03-24
**Status:** Paper trading only

---

## Overview

Crisp v4 applies the same dual-mode, multi-strategy framework to BTC/USDT. The convergence score now controls **mode and lot size** — it no longer gates whether trading happens. Every session runs Mode A (ORB) unconditionally; Mode B (Swing) activates at score ≥ 70.

---

## Two Trading Modes

### MODE A — Daily ORB (runs every session, always)

- **Filters:** ORB quality + ADR not extreme + 1m confirmation candle
- **No score requirement**
- **Lot size:** 0.001 BTC (standard)
- **Targets:** TP1=$150 / TP2=$200 / TP3=$300
- **SL:** Opposite ORB level
- **BE:** After TP1 hit
- **Max:** 1 ORB trade per session (per strategy slot)

### MODE B — Swing Trade (score ≥ 70 only)

- **Triggers when:** Strategist convergence score ≥ 70
- **Lot size:** 0.003 BTC (3× standard)
- **Targets:** TP1=$300 / TP2=$500 / TP3=$1,000
- **SL:** Below/above the H4 structure level
- **Hold:** Can hold through multiple sessions if trend is strong
- **Entry signal:** H4 structural breakout in Strategist's bias direction

---

## Four Strategies Per Session

| # | Strategy | Window | Requirement |
|---|---------|--------|-------------|
| 1 | **ORB Breakout** | First 30 min | Always (Mode A) |
| 2 | **Sweep Fade** | Post-ORB | Score ≥ 50 |
| 3 | **EMA Pullback** | Mid-session | Score ≥ 50, ORB direction established |
| 4 | **Momentum Entry** | Any time | Score ≥ 50 |
| + | **Swing Trade** | Any time | Score ≥ 70 (Mode B) |

Each strategy fires at most **once per session**. Only one position open at a time.

### Strategy Details

**Sweep Fade:** BTC is aggressively stop-hunted. When price sweeps the ORB level and reverses with ≥30% recovery, enter the fade. TP3 = full ORB range traversal.

**EMA Pullback:** After ORB establishes a trend, wait for a pullback to the 20 EMA on M15. Enter on a 1m continuation candle (touch from above + bullish close, or touch from below + bearish close).

**Momentum Entry:** Price breaks the prior-session high/low (last 6 hours) with a strong candle (body >60% of range) + EMA alignment. Enter in breakout direction.

**Swing Trade (Mode B):** Uses Strategist bias direction. Enters when price breaks an H4 structural level (high/low of prior 4 H4 candles) with 3× lot size. SL is the H4 structural level.

---

## Score as Mode Selector

| Score | Modes Enabled | Lot Size |
|-------|--------------|----------|
| < 50  | ORB only | 0.001 BTC |
| 50–69 | ORB + sweep + EMA pullback + momentum | 0.001 BTC |
| ≥ 70  | All above + Swing activated | 0.001 BTC standard + 0.003 BTC swing |

---

## Jase's Base 15m ORB (BTC Adaptation)

1. Wait for session open (00:00 UTC Asian, 13:30 UTC NY).
2. Record high/low of first 15m candle → ORB.
3. Drop to 1m — wait for full candle close+open beyond ORB level.
4. Enter on 1m close.
5. **SL:** Opposite ORB level.
6. **TPs (fixed pip targets, 1 pip = $1):**
   - TP1: +$150 from entry
   - TP2: +$200 from entry
   - TP3: +$300 from entry
7. After TP1: move SL to breakeven.

---

## Sessions

| Session | Time (UTC) | Notes |
|---------|-----------|-------|
| ASIAN   | 00:00–04:00 | Primary for Crisp. Low manipulation, clean consolidation breakout. |
| NY      | 13:30–17:30 | Highest volume. US equity open drives directional BTC flow. |

---

## Filters

### ADR Gate
- Skip if ADR > $5,000 (extreme event day)
- Skip if ADR < $500 (market too flat)

### ORB Quality
- Skip if ORB range < $100 (too tight)
- Skip if ORB range > $2,500 (stop too large)

### Lens Filter
Read `market_bias.json` for BTC/USDT. Apply directional filter when confidence ≥ 65%:
- Bullish ≥ 65% → long breakouts only
- Bearish ≥ 65% → short breakouts only
- < 65% → trade either direction

---

## Position Sizing

| Mode | Lot Size | Stop | TP1 |
|------|----------|------|-----|
| Mode A (ORB + additional) | 0.001 BTC | ORB opposite level | $0.15 |
| Mode B (Swing) | 0.003 BTC | H4 structure level | $0.90 |

*At current BTC ~$75,000:*
- Mode A TP1 = $0.15 / TP3 = $0.30
- Mode B TP1 = $0.90 / TP3 = $3.00
- Scale lot_size when paper results are consistently positive.

---

## Risk Rules

| Rule | Value |
|------|-------|
| Mode A lot size | 0.001 BTC per trade |
| Mode B lot size | 0.003 BTC per swing trade |
| Max positions at once | 1 (BTC only) |
| Max strategy slots per session | 4 standard + 1 swing |
| Paper mode | Always on |
| Time stop | Force-close at session end |
| Breakeven | Move SL to entry after TP1 |

---

## BTC-Specific Notes

**Round numbers.** BTC gravitates strongly to $5k round numbers ($75k, $80k, $85k). The bot detects entry within 0.5% of these levels and logs it. Consider adjusting TP3 to stop just before the round number.

**Sweep fade priority.** BTC is stop-hunted more frequently than equity indices. Sweep fade is available from post-ORB onwards at score ≥ 50.

**NASDAQ correlation.** When Lens has no explicit BTC bias but shows strong US100 directional bias, use it as a soft filter. Bearish US100 + no BTC bias → treat BTC as bearish-leaning.

**Weekend.** Disable cron on weekends. BTC weekend sessions have weaker ORB edge. The cleanest sessions are weekday ASIAN (00:00 UTC) and NY (13:30 UTC).

**Asian session priority.** ASIAN (00:00 UTC) is now the primary session for Crisp — overnight consolidation produces the cleanest range breakouts with minimal manipulation.

---

## Cron Schedule

```
# Asian session (primary — overnight consolidation breakout)
50 23 * * 1-5  python3 /root/.openclaw/agents/crisp/bot/crisp_bot.py ASIAN

# NY session (highest volume)
20 13 * * 1-5  python3 /root/.openclaw/agents/crisp/bot/crisp_bot.py NY
```

(Run 10 minutes early — bot waits internally for the exact open time.)

---

## Reporting

- Agent Hub post on session start, each trade, session end
- `agent_trades.json` updated after session
- `sync_agent_pnl.py` run at session end
- Telegram summary with P&L and round-number notes

---

## What Changed vs v3

| v3 | v4 |
|----|-----|
| Score gates trading (< 50 = skip) | Score selects mode/size — no trade gate |
| 1 trade per session max | Up to 4 standard + 1 swing |
| ORB + sweep only | + EMA pullback + momentum + swing mode |
| TP1=$150/TP2=$200/TP3=$300 fixed | Mode A same; Mode B: $300/$500/$1,000 |
| No swing mode | Mode B: 0.003 BTC, H4 SL, high targets |
| ASIAN at 08:00 UTC | ASIAN moved to 00:00 UTC (true Asian open) |
| No Mode B | 3× lots at score ≥ 70 |

---

*Updated by JCF HQ | 2026-03-24 | claude-sonnet-4-6*
