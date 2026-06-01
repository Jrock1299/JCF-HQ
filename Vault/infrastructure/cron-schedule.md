# Cron Schedule

All times UTC. `* * 1-5` = weekdays only.

## Always-on heartbeat
```
*/2  * * * *     sync_dashboard_public.sh             # dashboard mirror, every 2 min
*/30 * * * *     sync_tradelocker.py                  # broker fills, every 30 min
*/5  * * * *     sync_agent_pnl.py                    # rolling P&L per agent, every 5 min
```

## Portfolio syncs (1st + 15th of month only)
```
0  6  1,15 * *   sync_robinhood.py
0  6  1,15 * *   sync_trustwallet.py
0  6  1,15 * *   sync_kraken.py
0  6  1,15 * *   plaid/sync_plaid_transactions.py
```
Slowed from daily to bi-monthly 2026-06-01. Robinhood was 429ing daily; the
data doesn't move fast enough to justify the spam. See
[[../decisions/decision-log]].

## Lens — macro briefing
```
55 4  * * 1-5    run_lens_brain.sh                    # 04:55 — before all sessions
```
See [[../agents/lens]].

## Jarvis — regime briefing (formerly Strategist)
```
0  6  * * 1-5    strategist/run_research.sh           # pre-London brief
0  12 * * 1-5    strategist/run_research.sh           # pre-NY brief
0  8  * * 6      strategist/deep_backtest.py          # Saturday weekly deep backtest
```
See [[../agents/jarvis]].

## Session prep pings (Huncho voice + auto 4H reads)
```
40 23 * * 1-5    session_prep_ping.sh ASIA            # T-10 before ASIA
45 7  * * 1-5    session_prep_ping.sh LONDON          # T-10 before LONDON
15 13 * * 1-5    session_prep_ping.sh NY_OPEN         # T-10 before NY open (manual)
45 17 * * 1-5    session_prep_ping.sh NY_PM           # T-10 before NY_PM
```
Each prep ping generates an [[system-architecture#h4-read-pipeline|H4 read]]
per instrument, packages them via [[../agents/huncho|Huncho]], and Telegrams
the lot. Reads cache 30 min so Blade's session-start call hits the cache.

## Blade trading sessions
```
50 23 * * 1-5    timeout 7200 blade/bot/run_session.sh ASIA     # SPX500
55 7  * * 1-5    timeout 7200 blade/bot/run_session.sh LONDON   # SPX500 + DE30 + CHF/JPY
55 17 * * 1-5    timeout 7200 blade/bot/run_session.sh NY_PM    # SPX500
```
2-hour `timeout` is a safety net — each session is hard-capped at the
defined close time within the script.

## Session-end unified reports
```
0  6  * * 1-5    session_end_notify.py ASIA
30 13 * * 1-5    session_end_notify.py LONDON
0  21 * * 1-5    session_end_notify.py NY_PM
```

## Sentinel — insider/market intel
```
0  8  * * 1-5    sentinel/run_sentinel.sh
0  14 * * 1-5    sentinel/run_sentinel.sh
0  20 * * 1-5    sentinel/run_sentinel.sh
```
3× daily weekdays. See [[../agents/sentinel]].

## Daily ops
```
0  7  * * *      daily_briefing.py                    # consolidated Telegram digest
0  8  * * *      scrape_bball_stats.py                # Jase's eurobasket stats (personal)
30 5,21 * * *    sync_market_data.py                  # 2x daily market data refresh
0  21 * * *      victoria/run_victoria.sh             # daily CFO report
0  23 * * *      daily_cost_tracker.sh                # API cost rollup
```

## Tao (Bittensor)
```
0  3,11,19 * * *      tao_data_collector.py           # 3x daily
0  6  * * *           tao_subnet_scorer.py
0  9,21 * * *         tao_dca_engine.py               # 2x daily DCA check
0  0,6,12,18 * * *    tao_profit_monitor.py           # every 6 hours
0  8  * * 6           tao_compounder.py               # Saturday weekly
```
See [[../agents/tao]].

## Weekly
```
0  10 * * 6      norman/run_norman.sh                 # Saturday 10:00 — Norman validation
0  12 * * 0      lucy/lucy_brain.py --research        # Sunday noon — skills/tools scout
0  7  * * 1      victoria/run_victoria_weekly.sh      # Monday — weekly tribunal
0  8  * * 6      enrichment_tracker.py                # Saturday — Crisp enrichment analysis
```

## Commented out (parked / replaced)
```
# 55 23 * * 1-5  crisp/bot/run_session.sh ASIAN       # Crisp parked — see [[../agents/_benched/crisp]]
# 55 4  * * 1-5  lens/bot/run_lens.sh                 # replaced by lens_brain.py
# 0 7 * * *      send_dashboard.py                    # replaced by daily_briefing.py
# 0 9 * * *      oracle_bot.py                        # Oracle deleted
# 0 */2 * * *    oracle_resolver.py                   # Oracle deleted
```

## Related
- [[system-architecture]] — the bigger picture of how this fits together
- [[../decisions/decision-log]] — why certain entries exist (or don't)
