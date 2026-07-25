# Cron Schedule

> ⚠️ **Timezone (updated 2026-07-25).** This build (vixie-cron 3.0pl1) schedules
> **only in UTC**. `TZ=` is inert for scheduling (man page LIMITATIONS) and
> `CRON_TZ=` **is not supported here at all** — it's a cronie feature, absent
> from this binary; a live probe never fired. The old two-line `TZ=` block was
> removed as misleading.
>
> Jobs holding an ET wall-clock time schedule **both** candidate UTC hours with
> an ET guard, so DST needs no edit:
> ```cron
> 0 12,13 * * *  [ "$(TZ=America/New_York date +\%H:\%M)" = "08:00" ] && cmd
> ```
> Regenerate with `scripts/apply_cron_standardization.py`.
> Full rationale: [[data-freshness]] · [[../decisions/decision-log]]

**Standardized ET slots (2026-07-25):**

| Job | Slot |
|---|---|
| Victoria daily · Tao daily scorer | 8:00 AM ET |
| daily_briefing (HELD) | 8:00 PM ET |
| Victoria weekly · Norman · Lens thesis · Tao compounder · Lucy | Sunday 8:00 AM ET |
| Council | Sunday 9:00 AM ET |
| Sentinel | unchanged (UTC) — separate decision |

All other times UTC. `* * 1-5` = weekdays only.

## Always-on heartbeat
```
*/2  * * * *     sync_dashboard_public.sh             # dashboard mirror, every 2 min
*/30 * * * *     sync_tradelocker.py                  # broker fills, every 30 min
*/5  * * * *     sync_agent_pnl.py                    # rolling P&L per agent, every 5 min
17   * * * *     sync_api_costs.py                    # API cost card feed, hourly
```

## Portfolio syncs (1st + 15th of month only)
```
0  6  1,15 * *   sync_robinhood.py
0  6  1,15 * *   sync_trustwallet.py
0  6  1,15 * *   sync_kraken.py
0  6  1,15 * *   plaid/sync_plaid_transactions.py    # Truist transactions
0  6  1,15 * *   plaid/sync_plaid.py                 # Truist checking/MMA balances
```
Slowed from daily to bi-monthly 2026-06-01. Robinhood was 429ing daily; the
data doesn't move fast enough to justify the spam. See
[[../decisions/decision-log]].

**Plaid balance sync restored 2026-07-24.** `plaid/sync_plaid.py` (writes
`dashboard/plaid_data.json`, the checking/MMA balances) had **never** been in
cron — it only ever ran by hand, so the dashboard balance went ~95 days stale
(last hand-run 2026-04-20). Added on the same 1st/15th cadence as the other
syncs, and un-held `sync_plaid_transactions.py` (it had been `#HOLD`). The Plaid
production access token was never the problem — it validated live and pulled
fresh balances immediately. No re-auth was needed.

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
See [[../agents/_retired/jarvis|jarvis]].

## Session prep pings (Huncho voice + auto 4H reads) — HELD 2026-07-24
```
#HOLD 40 23 * * 1-5    session_prep_ping.sh ASIA            # T-10 before ASIA
#HOLD 45 7  * * 1-5    session_prep_ping.sh LONDON          # T-10 before LONDON
#HOLD 15 13 * * 1-5    session_prep_ping.sh NY_OPEN         # T-10 before NY open (manual)
#HOLD 45 17 * * 1-5    session_prep_ping.sh NY_PM           # T-10 before NY_PM
```
Each prep ping generates an [[system-architecture#h4-read-pipeline|H4 read]]
per instrument, packages them via [[../agents/huncho|Huncho]], and Telegrams
the lot. Reads cache 30 min so Blade's session-start call hits the cache.

## Blade trading sessions — HELD 2026-07-24
```
#HOLD 50 23 * * 1-5    timeout 7200 blade/bot/run_session.sh ASIA     # SPX500
#HOLD 55 7  * * 1-5    timeout 7200 blade/bot/run_session.sh LONDON   # SPX500 + DE30 + CHF/JPY
#HOLD 55 17 * * 1-5    timeout 7200 blade/bot/run_session.sh NY_PM    # SPX500
```
2-hour `timeout` is a safety net — each session is hard-capped at the
defined close time within the script.

**Held 2026-07-24 at Jase's direction** — no live strategy yet, so Blade's
paper sessions + all session support (prep pings above, end reports below) are
`#HOLD`'d. Un-hold all three groups together to resume. Code-ready: OANDA auth
was restored the same day, nothing else blocks it.

## Session-end unified reports — HELD 2026-07-24
```
#HOLD 0  6  * * 1-5    session_end_notify.py ASIA
#HOLD 30 13 * * 1-5    session_end_notify.py LONDON
#HOLD 0  21 * * 1-5    session_end_notify.py NY_PM
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
