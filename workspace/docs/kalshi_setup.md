# Kalshi Setup Notes

- Environment variables required:
  - KALSHI_ENV (prod|demo)
  - KALSHI_KEY_ID
  - KALSHI_PRIVATE_KEY_PATH
- Private key file path: `/root/.openclaw/kalshi_private_key.pem`
- Ensure file permissions: `chmod 600 /root/.openclaw/kalshi_private_key.pem`

These are referenced by Oracle scripts (oracle_bot.py, oracle_crypto.py).

---

## Kalshi Prediction Market Bot

**Location:** /root/kalshi-bot/
**Service:** kalshi-bot.service (systemd, auto-starts on boot, Restart=always)
**Status:** Live as of March 2026
**Logs:** /root/kalshi-bot/bot.log and /root/kalshi-bot/trades_log.csv

### Strategy
- Scans Kalshi 15-minute crypto markets every 60 seconds
- Targets: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXHYPE15M
- Momentum scoring (0–100): only trades signals scoring 65+
- Scoring factors: price distance from 50¢ fair value, time to expiry
  (sweet spot 8–14 min), orderbook liquidity depth

### Risk Rules
- Position size: 2% of bankroll per trade (minimum $1, maximum $50)
- Max 15 trades per day
- Stop trading if daily loss exceeds 10% of bankroll
- Max 5 open positions simultaneously
- Unfilled orders auto-cancelled after 2 minutes

### Key Files
- main.py       — main loop (DRY_RUN flag at line 24)
- strategy.py   — momentum scoring engine
- risk.py       — RiskManager class, position sizing, daily limits
- trader.py     — Kalshi API order execution
- scanner.py    — market discovery
- config.py     — RSA auth, API calls
- .env          — KALSHI_KEY_ID + KALSHI_PRIVATE_KEY_PATH

### Authentication
- RSA-PSS signing with 2048-bit private key
- Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
- Private key stored at /root/kalshi-bot/kalshi_private.pem

### Known Issues & Fixes

**Ghost positions bug (fixed March 28 2026)**
- Settled Kalshi contracts were not being cleared from the risk manager's
  in-memory state, blocking all new trades (Open: 5/5 with 0 signals for hours)
- Fix: `sync_open_positions()` added to risk.py — calls `GET /portfolio/positions`
  at the top of every loop and removes any ticker with net position == 0 or absent
- Daily trade counter now uses `datetime.now(timezone.utc).date()` to prevent
  midnight rollover issues when server local time differs from UTC

### Known API Quirks
- Order placement requires exactly one of yes_price OR no_price (not both)
- Order ID field in response is order_id (not id)
- Orderbook returns yes_dollars/no_dollars as dollar-string arrays sorted ascending
- Prices are in cents (65 = $0.65)

### Performance Tracking
- Starting bankroll: $20.64 (March 2026)
- Review trades_log.csv after 20–30 trades to tune score threshold
