# Trading Strategy — Blade (Forex & Indices)

## Objective: $2,000 -> $200,000
Environment: Forex & Indices via OANDA Practice
Style: Session-based ORB with adaptive learning

---

## Tradable Instruments
- GBP/JPY
- AUD/CAD
- XAU/USD
- NAS100_USD
- SPX500_USD

---

## Global Risk
- Starting balance: $2,000
- Risk per trade: 2%
- Max concurrent positions: 3
- Max session loss: 10% -> halt
- Max total drawdown: 20% -> halt

---

## STRATEGY 1 — 15-Minute ORB

### Sessions
London Open: 08:00 UTC / 3:00 AM EST
New York Open: 13:30 UTC / 8:30 AM EST

### Setup Rules
1. At session open record HIGH and LOW of first 15m candle including wicks
2. Wait for the 15m candle to fully close — no early entries
3. Drop to 1m chart
4. Wait for a full 1m candle body to close above or below the range
5. Enter on the next 1m candle open

### Entry
- Full 1m candle body closes ABOVE range -> LONG
- Full 1m candle body closes BELOW range -> SHORT
- Wicks do not count — body must fully close beyond range

### Stop Loss
- LONG: stop at LOW of opening 15m candle
- SHORT: stop at HIGH of opening 15m candle

### Take Profit
- Target: 2x the range size from entry
- Partial exit: 50% at 1x range, move stop to breakeven
- Runner: trail remaining 50% until stopped out

### ORB Validity
- Setup expires 4 hours after session open
- No entries after the 4-hour window

---

## STRATEGY 2 — Adaptive (Coming Soon)
Blade will develop additional strategies through:
- Log analysis and pattern recognition
- ICT concepts: liquidity grabs, fair value gaps, order blocks
- ClaHub community strategies
- Backtesting on historical OANDA data

---

## Position Sizing
Risk Amount = Balance x Risk %
Stop Distance = Entry - Stop Loss in price
Lot Size = Risk Amount / Stop Distance / Pip Value

---

## Exit Management
- Stop: placed immediately on entry, never widened
- Breakeven: move stop to entry after 1x range profit
- Trail: move stop to lock in profits on runner
- Time stop: close at market 4 hours after entry if neither TP nor SL hit

---

## Trade Log Format
Instrument:
Session: London / NY
Direction: LONG / SHORT
Entry Price:
Stop Loss:
Take Profit:
Lot Size:
Entry Time UTC:
Exit Price:
Exit Time UTC:
PnL $:
Result: WIN / LOSS / BREAKEVEN
Notes:

---

## Learning Rules
- Log EVERY trade no matter how small
- After each session write a debrief
- Weekly review: identify best performing instruments and sessions
- Monthly: propose strategy updates based on data
- Never repeat the same mistake twice
