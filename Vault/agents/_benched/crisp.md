# Crisp — Parked (Meme Coin Pivot Pending)

**Internal id:** `crisp`
**Status:** **Parked** for meme coin pivot. systemd service `crisp-v5`
currently `failed`. Cron entry commented out. Trade history preserved.

## What Crisp was
BTC/USDT multi-strategy framework on a 15m timeframe. Two-session structure
(ASIAN + NY) with multiple strategy modes. Previously the crypto counterpart
to [[../blade]].

## Why parked
Halted around 2026-05-18. Awaiting a **meme coin pivot rebuild** — Jase's
direction is to reframe Crisp around meme coins rather than BTC/USDT.
Requires:
1. A new `SOUL.md` defining the agent's new mandate + voice
2. New strategy spec (probably not 15m ORB)
3. New venue / data source (meme coins likely won't be on OANDA)
4. New backtest before any deployment

## What's preserved
- `agents/crisp/bot/crisp_bot.py` — old v4 framework (kept for reference)
- `agents/crisp/data/trade_history.json` — historical trades
- `agents/crisp/enrichment_log.csv` — enrichment data used by
  `scripts/enrichment_tracker.py` (Saturday weekly analyzer still reads this)
- The systemd unit file (failed state)

## Key files (parked)
- `agents/crisp/bot/crisp_bot.py`
- `agents/crisp/crisp_main.py`
- `agents/crisp/position_manager.py`
- `agents/crisp/crisp_config.py`
- `agents/crisp/data/trade_history.json`

## Cron status
Commented out in crontab (this line is intentionally left commented for
reference):
```
# 55 23 * * 1-5 timeout 7200 bash /root/.openclaw/agents/crisp/bot/run_session.sh ASIAN
```

## Revival path
Awaiting Jase's design call on the meme coin pivot. When ready, this will
become a from-scratch rebuild not a revival of the BTC/USDT framework.

## Cross-agent context
- Used to read [[../jarvis|Jarvis]]'s `strategy_recommendation.json` for
  the now-deleted convergence score. That dead wire was a factor in the
  Jarvis trim — see [[../jarvis#what-was-removed-2026-06-01]].
