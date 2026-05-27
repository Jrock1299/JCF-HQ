# BLADE v4 — Multi-Instrument Multi-Strategy Framework
**Version:** 4.0
**Updated:** 2026-03-24
**Status:** Paper trading only

---

## Overview

Blade v4 expands from a single ORB strategy to a full intraday framework. Every session runs two independent trading modes and up to four strategies per instrument. The convergence score now controls **mode and size** — it no longer gates whether trading happens.

**Instrument priority (current market conditions):**
1. **DE30_EUR** — London (08:00 UTC). Cleanest ORB moves.
2. **SPX500_USD** — London / Asia / NY / NY PM. Multiple session opportunities.
3. **XAU_USD** — Any session, ONLY when Lens confidence ≥ 65%.

---

## Two Trading Modes

### MODE A — Daily ORB (runs every session, always)

- **Filters:** ORB quality (min/max pips) + ADR not extreme + 1m confirmation candle
- **No requirement** for Lens bias, EMA alignment, or convergence score
- **Lot size:** 1 OANDA unit (standard)
- **Targets:** TP1=15 pips / TP2=20 pips / TP3=30 pips
- **SL:** Opposite ORB level
- **BE:** After TP1 hit
- **Max:** 1 ORB trade per instrument per session
- **Always runs** — score does not prevent this

### MODE B — Swing Trade (score ≥ 70 only)

- **Triggers when:** Strategist convergence score ≥ 70
- **Reads:** `strategy_recommendation.json` for bias direction
- **Lot size:** 3 OANDA units (3× standard)
- **Targets:** TP1=30 pips / TP2=50 pips / TP3=100 pips
- **SL:** Below/above the H4 structure level (not just the ORB)
- **Hold:** Can stay open through multiple sessions if trend is strong
- **Entry signal:** H4 structural breakout in Strategist's bias direction

Both modes can be active simultaneously — on **different instruments**. An instrument can only hold one open position at a time.

---

## Four Strategies Per Session

After the ORB window (first 30 minutes), the bot continues monitoring for:

| # | Strategy | Window | Requirement |
|---|---------|--------|-------------|
| 1 | **ORB Breakout** | First 30 min | Always (Mode A) |
| 2 | **Sweep Fade** | 30–60 min | Score ≥ 50 |
| 3 | **EMA Pullback** | Mid-session | Score ≥ 50, ORB direction established |
| 4 | **Momentum Entry** | Any time | Score ≥ 50 |
| + | **Swing Trade** | Any time | Score ≥ 70 (Mode B) |

Each strategy fires at most **once per instrument per session**. Max 4 standard trades + 1 swing per instrument.

### Strategy Details

**Sweep Fade:** Price sweeps the ORB high/low (stop hunt), reverses, closes back inside range with ≥30% reversal. Enter the fade. TP3 = full ORB range.

**EMA Pullback:** After an ORB breakout establishes a trend direction, wait for price to retrace to the 20 EMA on M15. Enter on a bouncing 1m candle in the original direction.

**Momentum Entry:** Price breaks a prior-session high/low (last 6 hours) with a strong candle (body >60% of range) + price above/below 20 EMA. Enter in the breakout direction.

**Swing Trade (Mode B):** Reads Strategist bias. Waits for price to break an H4 structural level (high/low of prior 4 H4 candles) in the bias direction. Enters with 3× lot size and H4-structure SL.

---

## Jase's Base 15m ORB (Mode A)

1. Wait for the session open.
2. Record the high and low of the **first 15m candle** — this is the Opening Range.
3. Drop to the **1m chart** and wait for a full candle to close (and open) beyond the ORB level.
4. **Enter** on that 1m close: LONG if above ORB high, SHORT if below ORB low.
5. **Stop Loss:** Opposite side of the ORB range (full ORB stop).
6. **Take Profit:**
   - TP1: entry ± 15 pips
   - TP2: entry ± 20 pips
   - TP3: entry ± 30 pips
7. After TP1 hit → move SL to breakeven.

*Pip definitions (OANDA units):*
- SPX500: 1 pip = 1 index point. **1 OANDA unit = $1/pt**
- DE30:   1 pip = 1 index point. **1 OANDA unit = €1/pt**
- XAU:    1 pip = $1.00.        **1 OANDA unit = 1 oz**

---

## Sessions

| Session | Time (UTC) | Instruments |
|---------|-----------|-------------|
| ASIA    | 00:00–04:00 | SPX500_USD — low vol, clean breaks |
| LONDON  | 08:00–12:00 | DE30_EUR (primary), XAU_USD (Lens-conditional) |
| NY      | 13:30–17:00 | SPX500_USD, XAU_USD (Lens-conditional) |
| NY_PM   | 18:00–21:00 | SPX500_USD, XAU_USD (Lens-conditional) |

All instruments are monitored concurrently within a session.

---

## Score as Mode Selector

The convergence score is **NOT** a trade/no-trade gate. It controls which strategies are available.

| Score | Modes Enabled | Lot Size |
|-------|--------------|----------|
| < 50  | ORB only | Standard (1 unit) |
| 50–69 | ORB + sweep fade + EMA pullback + momentum | Standard (1 unit) |
| ≥ 70  | All above + Swing trade activated | Standard (1 unit) + Swing (3 units) |

---

## Filters (Applied Before Any Trading)

### 1. ADR Volatility Gate

Skip session if 5-day Average Daily Range is outside the normal band:

| Instrument | Skip if ADR > | Skip if ADR < |
|------------|--------------|--------------|
| SPX500 | 120 pts | 15 pts |
| DE40 | 400 pts | 50 pts |
| XAU | 80 pts | 8 pts |

### 2. ORB Quality Gate

Skip if the 15m ORB range is outside acceptable bounds:

| Instrument | Skip if ORB < | Skip if ORB > |
|------------|--------------|--------------|
| SPX500 | 4 pts | 60 pts |
| DE40 | 10 pts | 150 pts |
| XAU | 5 pts | 45 pts |

### 3. Lens Directional Filter (applied to ORB direction, not to trade/no-trade)

| Lens State | Effect |
|------------|--------|
| XAU, confidence < 65% | **Skip XAU entirely** for this session |
| Confidence ≥ threshold, bullish | Only take LONG breakouts on that instrument |
| Confidence ≥ threshold, bearish | Only take SHORT breakouts on that instrument |
| Confidence < threshold | Trade either direction |
| File missing | Log warning, continue without filter |

---

## Position Sizing

| Mode | Units | Risk Profile |
|------|-------|-------------|
| Mode A (ORB + additional strategies) | 1 OANDA unit | Structural stop (ORB range) |
| Mode B (Swing) | 3 OANDA units | H4 structure stop (wider) |

**Dollar P&L at 1 unit (Mode A):**
- SPX500: TP1=$15 / TP2=$20 / TP3=$30
- DE30:   TP1=€15 / TP2=€20 / TP3=€30
- XAU:    TP1=$15 / TP2=$20 / TP3=$30

**Dollar P&L at 3 units (Mode B swing):**
- SPX500: TP1=$90 / TP2=$150 / TP3=$300
- DE30:   TP1=€90 / TP2=€150 / TP3=€300
- XAU:    TP1=$90 / TP2=$150 / TP3=300

---

## Risk Rules

| Rule | Value |
|------|-------|
| Mode A lot size | 1 OANDA unit per trade |
| Mode B lot size | 3 OANDA units per swing trade |
| Max strategies per instrument per session | 4 standard + 1 swing |
| Max simultaneous positions | 3 (one per instrument) |
| Paper mode | Always on |
| Time stop | Force-close at session end |
| Breakeven | Move SL to entry after TP1 |

---

## Cron Schedule

```
# Asia session: SPX500 (new)
50 23 * * 1-5  python3 /root/.openclaw/agents/blade/bot/blade_bot.py ASIA

# London session: DE30 + XAU
50 7 * * 1-5   python3 /root/.openclaw/agents/blade/bot/blade_bot.py LONDON

# NY session: SPX500 + XAU
20 13 * * 1-5  python3 /root/.openclaw/agents/blade/bot/blade_bot.py NY

# NY PM session: SPX500 + XAU
50 17 * * 1-5  python3 /root/.openclaw/agents/blade/bot/blade_bot.py NY_PM
```

(Run ~10 minutes early — bot waits internally for the exact open time.)

---

## Reporting

Each session produces:
- Terminal output with per-instrument status every 30s
- Agent Hub post at start, on each trade, at end
- `agent_trades.json` updated with all session records
- `sync_agent_pnl.py` run at session end
- Telegram report summarising all instrument outcomes

---

## What Changed vs v3

| v3 | v4 |
|----|-----|
| Score gates trading (< 50 = skip) | Score selects mode/size — no trade gate |
| ORB only per session | Up to 4 strategies + swing per session |
| 1 trade per instrument per session | Up to 5 sequential trades per instrument |
| No swing mode | Mode B: 3x lots, H4 SL, 30/50/100 pip targets |
| LONDON + NY + NY_PM only | + ASIA session for SPX500 |
| sweep_fade always | sweep_fade requires score ≥ 50 |
| No EMA pullback strategy | EMA pullback on 20 EMA M15 added |
| No momentum entry | Prior-session-range breakout added |

---

## Performance Targets (Review every 20 trades)

| Metric | Target | Action if missed |
|--------|--------|-----------------|
| Win rate | ≥ 50% | Below 40% → pause, review |
| Profit factor | ≥ 1.3 | Below 1.0 → pause |
| Mode B win rate | ≥ 55% | If worse than Mode A → review swing criteria |
| Swing trade frequency | 1–3 per week | If 0 → check score thresholds |

---

*Updated by JCF HQ | 2026-03-24 | claude-sonnet-4-6*
