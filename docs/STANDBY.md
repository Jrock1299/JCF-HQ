# JCF HQ — Full Standby

**Entered:** 2026-07-01
**Reason:** Pause all operations to zero token usage and notifications.
**Reversibility:** Fully reversible. Nothing deleted. All code, configs, and data intact.

## What is stopped and disabled

### systemd services (system)
| Service | State | Notes |
|---|---|---|
| `edge.service` | inactive, disabled | Edge SMA scalper (SPX500 1m 9/21) |
| `jerry.service` | inactive, disabled | Jerry stocks/options trader |
| `jcf-hq.service` | inactive, disabled | HQ dashboard :8080 |
| `hq-storage.service` | inactive, disabled | HQ storage API :8900 |
| `phantom.service` | inactive, disabled | Phantom crypto futures |
| `telegram-monitor.service` | inactive, disabled | Oracle Telegram channel monitor |
| `crisp-v5.service` | failed, disabled | Crisp v5 BTC adaptive |

### systemd services (user)
| Service | State | Notes |
|---|---|---|
| `openclaw-hq.service` | inactive, disabled | HQ dashboard (user unit) |
| **`openclaw-gateway.service`** | **active, enabled** | **Kept up — Huncho reachable if user messages first** |

### Cron
No user crontab exists (`crontab -l` → "no crontab for root"). No JCF entries in `/etc/cron.d/`. No JCF systemd timers. Only OS-default housekeeping timers remain (apt, logrotate, fstrim, etc.).

Snapshot of cron state at standby entry: `/tmp/crontab_full_backup_2026-07-01.bak`

## Portfolio / broker syncs — confirmed OFF

All broker and portfolio sync scripts live under `/root/.openclaw/scripts/` and are invoked by the agent services that are now stopped. Nothing will pull from:

- **Plaid** (bank data) — `scripts/plaid/sync_plaid*.py` — no scheduler, no running caller
- **Robinhood** — `scripts/sync_robinhood.py` — no scheduler, no running caller
- **Trust Wallet** — `scripts/sync_trustwallet.py` — no scheduler, no running caller
- **Kraken** — `scripts/sync_kraken.py` — no scheduler, no running caller
- **OANDA / Alpaca** — accessed by edge/jerry/phantom (all stopped)

## Notifications — silent

No proactive Telegram messages will originate from HQ:
- All agent services (senders) are stopped.
- `telegram-monitor.service` is stopped/disabled.
- Gateway remains a passive listener — it responds only to inbound user messages.

## Expected ongoing spend

- **Token spend from HQ agents: ≈ $0/day.** No agent is executing loops or LLM calls.
- Residual: only inbound-triggered gateway responses when the user messages Huncho.

## How to resume

Re-enable and start each service. Everything is preserved:

```bash
for svc in edge jerry jcf-hq hq-storage phantom telegram-monitor; do
  systemctl enable --now "$svc"
done
systemctl --user enable --now openclaw-hq
# crisp-v5 was already in a failed state pre-standby — inspect logs before enabling
```

Cron was empty at standby entry, so no cron restoration is required. Snapshot at `/tmp/crontab_full_backup_2026-07-01.bak` documents the prior state.
