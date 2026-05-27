# HUNCHO — JCF HQ Data Routing Instructions
## New Dashboard Deployment + Agent Feed Map

---

## STEP 1 — DEPLOY THE NEW FILE

Replace the dashboard with the new file Jase will send you:

```bash
cp /path/to/jcf_hq_FINAL.html /root/.openclaw/dashboard/jcf_hq.html
bash /root/.openclaw/scripts/deploy_hq.sh /root/.openclaw/dashboard/jcf_hq.html
```

Confirm it's live at: `187.124.3.145:8899/jcf_hq.html`

---

## STEP 2 — JSON FEED MAP
### Every agent writes to a specific file. Here is the complete routing table.

---

### 📁 `/root/.openclaw/dashboard/tradelocker_trades.json`
**Written by:** `sync_tradelocker.py` (cron every 30 min)
**Read by:** Trading tab (trade log, P&L calendar, stats), Portfolio tab (TradeLocker account balance)

Required schema:
```json
{
  "balance": 100354.43,
  "pnl": 354.43,
  "last_sync": "2026-03-11T09:30:00",
  "trades": [
    {
      "open_time": "2026-02-10T14:32:00",
      "symbol": "XAU/USD",
      "direction": "buy",
      "lots": 0.50,
      "open_price": "2104.50",
      "close_price": "2118.90",
      "pnl": 77.39,
      "date": "2026-02-10"
    }
  ]
}
```

**Action:** Confirm TradeLocker password with Jase and re-run sync script. Verify `balance`, `pnl`, and `trades` array are populating correctly.

---

### 📁 `/root/.openclaw/dashboard/agent_trades.json`
**Written by:** `crisp_bot.py` and `blade_bot.py` after each trade
**Read by:** Dashboard (Agent P&L Today), Portfolio (Crisp P&L, Blade P&L), Agents tab

Required schema:
```json
{
  "trades": [
    {
      "agent": "crisp",
      "symbol": "BTC/USDT",
      "direction": "long",
      "pnl": 42.10,
      "date": "2026-03-11",
      "timestamp": "2026-03-11T08:14:00"
    },
    {
      "agent": "blade",
      "symbol": "XAU/USD",
      "direction": "buy",
      "pnl": 31.20,
      "date": "2026-03-11",
      "timestamp": "2026-03-11T07:55:00"
    }
  ]
}
```

**Action:** Verify both `crisp_bot.py` and `blade_bot.py` are writing to this file with an `"agent"` field on each trade. The dashboard filters by date to calculate today's P&L per agent.

---

### 📁 `/root/.openclaw/dashboard/oracle_picks.json`
**Written by:** Oracle agent daily (written fresh each morning)
**Read by:** Sports Betting tab (Oracle's bets panel, Oracle card), Dashboard (Oracle Win Rate, Bankroll), Agents tab, Portfolio tab

Required schema:
```json
{
  "bankroll": 500.00,
  "record": "12W – 4L",
  "win_rate": "75%",
  "total_pnl": 84.50,
  "last_updated": "2026-03-11T08:00:00",
  "picks": [
    {
      "date": "2026-03-11",
      "sport": "NBA",
      "pick": "Lakers -4.5 vs Clippers",
      "odds": "-110",
      "stake": "10",
      "result": "pending",
      "pnl": 0
    },
    {
      "date": "2026-03-11",
      "sport": "Parlay",
      "pick": "Gonzaga ML + Wright State ML",
      "odds": "-165",
      "stake": "10",
      "result": "pending",
      "pnl": 0
    }
  ]
}
```

**Action:** When Oracle resolves a pick, update `"result"` to `"win"` or `"loss"` and set the `"pnl"` value. Also update top-level `bankroll`, `record`, `win_rate`, and `total_pnl` fields accordingly. The `sync_agent_pnl.py` script should handle this automatically — confirm it's running.

---

### 📁 `/root/.openclaw/dashboard/bet_log.json`
**Written by:** Jase manually (via bet log edit buttons in the Sports Betting tab) OR via Huncho when Jase logs a bet through Telegram
**Read by:** Sports Betting tab (Your Bets panel, Bankroll hero)

Required schema:
```json
{
  "bankroll": 250.00,
  "record": "8W – 3L",
  "win_rate": "72.7%",
  "total_pnl": 62.30,
  "roi": "24.9%",
  "total_wagered": 250.00,
  "bets": [
    {
      "date": "2026-03-11",
      "sport": "NBA",
      "pick": "Celtics -6 vs Knicks",
      "odds": "-110",
      "stake": "25",
      "result": "win",
      "pnl": 22.73
    }
  ]
}
```

**Action:** Create this file at the path above if it doesn't exist. When Jase sends you a bet to log via Telegram (e.g. "log NBA, Celtics -6, -110, $25"), append it to the `bets` array and update the summary stats at the top.

---

### 📁 `/root/.openclaw/dashboard/market_bias.json`
**Written by:** Lens agent (3x daily: pre-market, mid-day, close)
**Read by:** Intel tab (Daily Brief, Macro Desk, Forex news feed), Dashboard (Morning Report, Priorities)

Required schema:
```json
{
  "last_updated": "2026-03-11T08:00:00",
  "summary": "Key risk today: Powell speaks at 10 AM EST. DXY elevated after CPI beat. GBP/JPY approaching weekly resistance at 193.40. BTC weak below $82K...",
  "morning_report": "Morning report text here — 3-5 sentences on what to watch today.",
  "priorities": "1. Watch Powell 10 AM<br>2. GBP/JPY resistance test<br>3. Oracle picks lock tonight",
  "pairs": [
    {
      "symbol": "GBP/JPY",
      "bias": "bullish",
      "confidence": 78,
      "note": "BoJ staying dovish. GBP supported by sticky UK inflation. Trend intact above 191.80."
    },
    {
      "symbol": "XAU/USD",
      "bias": "bullish",
      "confidence": 82,
      "note": "Safe haven demand. Key resistance $2,155. Fed speech risk today."
    },
    {
      "symbol": "AUD/CAD",
      "bias": "neutral",
      "confidence": 51,
      "note": "Both central banks on hold. Range bound 0.8990–0.9050."
    },
    {
      "symbol": "BTC/USD",
      "bias": "bearish",
      "confidence": 64,
      "note": "Below 21D EMA. Volume declining on bounces. $80K key level."
    }
  ],
  "forex_news": [
    {
      "headline": "DXY breaks above 104.20 on strong PPI data",
      "source": "Reuters",
      "time": "38m ago",
      "impact": "high"
    }
  ]
}
```

**Action:** Confirm Lens is writing all required fields — especially `morning_report`, `priorities`, and `forex_news`. These are new fields added for the new dashboard. Update Lens's output template to include them.

---

### 📁 `/root/.openclaw/dashboard/robinhood_data.json`
**Written by:** Robinhood sync script (if configured)
**Read by:** Portfolio tab (Robinhood account card)

Required schema:
```json
{
  "equity": 12450.00,
  "last_sync": "2026-03-11T09:00:00"
}
```

---

### 📁 `/root/.openclaw/dashboard/trustwallet_data.json`
**Written by:** Trust Wallet sync script (if configured)
**Read by:** Portfolio tab (Trust Wallet account card)

Required schema:
```json
{
  "total_usd": 8200.00,
  "last_sync": "2026-03-11T09:00:00"
}
```

---

## STEP 3 — VERIFY CRON JOBS

Confirm these cron entries exist in crontab (`crontab -l`):

```
*/30 * * * * python3 /root/.openclaw/scripts/sync_tradelocker.py
*/5  * * * * python3 /root/.openclaw/scripts/sync_agent_pnl.py
0 7,12,16 * * * python3 /root/.openclaw/agents/lens/run.py
```

---

## STEP 4 — NEW FIELDS CHECKLIST FOR LENS

Lens needs to add these fields to its output in `market_bias.json`:

- [ ] `morning_report` — 3-5 sentence morning briefing
- [ ] `priorities` — HTML string listing today's 2-3 top priorities (can use `<br>` for line breaks)
- [ ] `forex_news` — array of recent forex headlines with `headline`, `source`, `time`, `impact` fields

Update Lens's system prompt / output template to include these.

---

## STEP 5 — TELEGRAM LOGGING (NEW CAPABILITY)

Huncho can now accept direct bet logging from Jase via Telegram. When Jase sends:

> "log bet: NBA, Lakers -4.5, -110, $25"

Huncho should:
1. Parse sport, pick, odds, stake from the message
2. Append to `/root/.openclaw/dashboard/bet_log.json`
3. Update summary stats (record, bankroll, etc.)
4. Confirm back to Jase: "Logged — Lakers -4.5 at -110 for $25. Bankroll: $X"

---

## SUMMARY — FILE LOCATIONS

| File | Path | Updated By | Frequency |
|------|------|-----------|-----------|
| TradeLocker trades | `/root/.openclaw/dashboard/tradelocker_trades.json` | sync_tradelocker.py | Every 30 min |
| Agent trades | `/root/.openclaw/dashboard/agent_trades.json` | crisp_bot.py / blade_bot.py | Per trade |
| Oracle picks | `/root/.openclaw/dashboard/oracle_picks.json` | Oracle agent | Daily AM + on resolve |
| Bet log | `/root/.openclaw/dashboard/bet_log.json` | Jase / Huncho | Per bet |
| Market bias | `/root/.openclaw/dashboard/market_bias.json` | Lens | 3x daily |
| Robinhood | `/root/.openclaw/dashboard/robinhood_data.json` | Robinhood sync | Daily |
| Trust Wallet | `/root/.openclaw/dashboard/trustwallet_data.json` | TW sync | Daily |
