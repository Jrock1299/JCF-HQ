# CRISP — Trading Environment Setup

## Paper Trading Initialization

✅ **Status:** READY FOR DEPLOYMENT

---

## Environment Details

**Exchange:** Aster DEX
**Mode:** Paper Trading (Simulated)
**Capital:** $1,000 USD (simulated)
**API Version:** Latest
**Connection Status:** Active

---

## Account Configuration

- **Trading Pair Assets:** BTC, ETH, SOL, XRP
- **Max Concurrent Positions:** 3
- **Leverage Capability:** 5x (controlled per STRATEGY.md)
- **Risk Per Trade:** 3-5% of current equity
- **Position Size:** Calculated from risk ÷ stop %

---

## Starter Strategy Parameters

From STRATEGY.md — Aggressive Momentum Expansion:

**Entry Conditions (LONG):**
1. Price > 24h MA
2. Higher highs, higher lows (1h/4h structure)
3. 3+ of last 4 hourly candles green
4. Break of previous 4h high OR shallow pullback (<2%)
5. 1h volume ≥ 1.3× 24h average
6. 1h ATR ≥ 1.2× 24h ATR average

**Entry Conditions (SHORT):**
1. Price < 24h MA
2. Lower highs, lower lows structure
3. 3+ of last 4 hourly candles red
4. Breakdown of previous 4h low
5. 1h volume ≥ 1.3× 24h average
6. No major support within 2% below entry

**Exit Management:**
- Initial stop: 3-4% from entry (placed immediately)
- Partial TP: 50-70% at +6-8%
- Move stop to breakeven after partial TP
- Runners: Trail at +10% to +3-5% or hold to exhaustion
- Time stop: Close at market if no expansion within 24h

---

## Risk Parameters (Hard Limits)

- **Max Session Loss:** 15% → HALT if hit
- **Max Total Drawdown:** 30% → HALT strategy if hit
- **Max Leverage:** 5x
- **Max Risk Per Trade:** 5% (default 4%)

---

## Session Schedule

- **Max Session Duration:** 8 hours
- **Regime Reassessment:** Every 8 hours
- **Position Closure:** At session end (runners close or reset)
- **Daily Reset:** New regime assessment each morning

---

## First Session Protocol

1. Load current BTC regime (price vs 24h MA + candle confirmation)
2. Scan for valid setups across BTC, ETH, SOL, XRP
3. Enter ONLY if all 6 conditions are met
4. Execute with calculated position size
5. Place stop immediately
6. Monitor for partial TP trigger (+6-8%)
7. Report to Huncho at session end

---

## Monitoring & Alerts

Crisp monitors continuously:
- Open positions and PnL
- Session drawdown vs 15% limit
- Total drawdown vs 30% limit
- Regime changes
- Time stops approaching (24h)

Immediate alerts to Huncho if:
- 15% session loss reached → HALT
- 30% total drawdown reached → HALT
- Emergency system error → Close all positions

---

## Paper Trading Notes

- No real capital is deployed
- All trades are simulated against Aster DEX's paper trading engine
- Execution fills are realistic (based on current market data)
- Purpose: Test strategy execution, refine timing, build confidence
- Transition to live trading requires Jase's explicit command: "Switch to live" or "Go live"

---

## Ready to Deploy

Crisp is configured and ready to execute. Awaiting signal from Huncho/Jase.

Command: "Start trading"
