# CRISP — Configuration

## Exchange: Aster DEX

**Exchange:** Aster DEX
**API Endpoint:** (configured internally)
**Mode:** Paper Trading (Simulated)
**Simulated Capital:** $1,000 USD

---

## Authentication

API credentials are stored securely in encrypted config.
Crisp has access to trade execution, order management, and position monitoring.

---

## Trading Environment

- **Mode:** Paper Trading
- **Starting Capital:** $1,000 (simulated)
- **Leverage Available:** Up to 5x
- **Position Limit:** 3 concurrent (as per STRATEGY.md)
- **Risk Per Trade:** 3-5% of equity

---

## Strategy Active

- **Framework:** Aggressive Momentum Expansion + ORB (STRATEGY.md)
- **Assets:** BTC, ETH, SOL, XRP only
- **Regime Gate:** BTC-based directional filter
- **Entry Methods:**
  - Strategy 1: Momentum Expansion (3 of 6 conditions)
  - Strategy 2: 15-Minute Opening Range Breakout (ORB)
- **Exit:** Partial TP at +6-8%, runners on trail, 24h time stop (Momentum) / 4h (ORB)

---

## Active Trading Sessions

| Session | Open (UTC) | Open (EST) | Window |
|---|---|---|---|
| **New York Morning** | 14:30 UTC | 9:30 AM EST | 4 hours (until 13:30 EST) |
| **Asia Open** | 00:00 UTC | 7:00 PM EST | 4 hours (until 11:00 PM EST) |

### Session Rules
- Crisp is ACTIVE during both sessions
- ORB setups: mark 15m opening range at session open, monitor for breakout within 4h window
- Momentum setups: scan continuously during active session windows
- Between sessions: no new trades, manage open runners only
- Regime reassessment at the start of each session

---

## Operational Status

✅ Paper trading initialized
✅ $1,000 simulated capital ready
✅ Connected to Aster DEX API
✅ Strategy framework loaded (Momentum + ORB)
✅ Two active sessions: NY Morning + Asia Open
✅ Ready to execute on regime confirmation

---

## Session Management

- Two trading windows per day (NY Morning + Asia Open)
- Regime reassessment at the start of each session
- ORB validity: 4 hours per session
- Runners managed between sessions (trail or time stop)
- Daily PnL tracking independent from drawdown calculations
- Emergency halt at 15% session loss or 30% total drawdown

---

## Reporting

Crisp reports to Huncho after each session:
- Trade entry/exit summaries
- Confidence score per trade (e.g. 3/6, 4/6 for Momentum; ORB regime alignment)
- Session performance
- Regime status
- Any halts or emergency closures
- Opportunity log (missed setups)

No direct communication with Jase.
