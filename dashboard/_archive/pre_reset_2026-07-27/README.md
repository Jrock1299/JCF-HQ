# Pre-reset data archive — 2026-07-27

Corrupted trading history, quarantined at Jase's direction. **Read-only
evidence. Nothing in production may read these files.**

Archived 2026-07-27T17:28:02.651842+00:00.

| File | What was wrong |
|---|---|
| `tradelocker_trades.json` | 330 trades from a broker Blade no longer uses (newest close 2026-05-27). The `*/30` sync refreshed `last_sync` so it looked live while the payload sat dormant two months. Graded as "Blade" for two months. `win_rate` stored as the string `"53.3%"` — wrong value (176W/139L = 55.87%) and a string, so numeric consumers coerced it to 0.0. |
| `norman_report.json` | Written 2026-07-25 by an agent retired the same day. Phantom Blade grade off the 330 dormant trades; impossible 468.0% max drawdown for Chad (internal id `crisp`), which signals an equity-accounting failure, not a trading result. |

Both were replaced in `dashboard/` by tombstones carrying `_QUARANTINED: true`
and **no numbers**. Consumers default to `verdict=UNKNOWN` /
`ruin_probability=None`, which is the honest state.

Superseded by:
- `dashboard/lens_validation.json` — Blade, Edge
- `dashboard/victoria_validation.json` — Jerry, Chad

The TradeLocker sync cron line is **held**; un-holding it would repopulate the
quarantined file within 30 minutes.
