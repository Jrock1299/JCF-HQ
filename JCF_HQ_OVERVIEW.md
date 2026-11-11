# JCF HQ — System Overview

**Audit date:** 2026-11-11
**Status: FULLY PARKED.** Confirmed via live checks (not just memory/docs): all 6 system
systemd units and 2 user systemd units are `disabled`/inactive, `crontab -l` is 100%
commented out (`#PARKED 2026-08-11`, `#HOLD`, or `#HOLD RETIRED`), `pm2 list` is empty,
`ss -tlnp` shows nothing bound on ports 8080/8899/8900/18789, and no JCF-related process
appears in `ps aux`. Parked since commit `5f0e8a0` (2026-08-11), "Full pause — operation
parked by Jase's decision to focus on personal trading." Nothing has changed since.
**Do not restart anything without reading `RESTART.md` first** — it documents blockers
that are still unresolved (see §5).

---

## 1. Agents

| Agent | Role | Code location | Run mechanism | Status |
|---|---|---|---|---|
| **Huncho** | Orchestrator / Telegram persona, voice/router layer | `agents/huncho/killzone_sync.py`, `scripts/telegram_personalities.py` | OpenClaw gateway process | Parked |
| **Blade** | Primary FX bot — 15m ORB / turtle-soup sweep-fade on SPX500_USD, DE30_EUR, XAU_USD (the one strategy with real backtest validation) | `agents/blade/bot/blade_bot.py`, `run_session.sh` | cron (3 sessions/day: ASIA, LONDON, NY_PM) + `agents/lens/run_live_turtle.sh` (15-min live executor during London/NY killzones) | Parked. Was crash-looping before the pause (credential-path bug, see §5) |
| **Edge** | SMA 9/21 crossover scalper, SPX500_USD only, account `-002` | `agents/edge/edge_main.py`, `edge_config.py` | `edge.service` (systemd) + cron turtle wrapper (`run_edge_live_turtle.sh`) | Parked, `disabled`. Was also crash-looping |
| **Jerry** | Stocks/options paper trader on Alpaca | `agents/jerry/jerry_main.py` | `jerry.service` (systemd, loads `/root/.openclaw/.env` directly) | Parked. Graded **FAIL** by Victoria 2026-08-09 (121 trades, 36.4% WR, PF 0.95, −$1,121.59) — kept parked on merit, not just the global pause |
| **Lens** | Macro/regime brief; absorbed Jarvis's regime briefing + Norman's Blade/Edge validation (2026-07-25 consolidation) | `agents/lens/lens_brain.py`, `lens_regime.py`, `lens_validator.py` | cron, multiple daily + weekly jobs | Parked. Only Anthropic-billed cron agent |
| **Victoria** | CFO/Chief of Staff; absorbed Lucy's scouting + Norman's Jerry/Chad validation | `agents/victoria/victoria_brain.py` + `*_scout.py` / `*_validator.py` | cron, daily + weekly | Parked |
| **Crisp** (displays as "Chad") | BTC adaptive trader, wallet-intel driven decisions | `agents/crisp/crisp_main.py`, `chad_wallet_intel.py`, `chad_decision_engine.py` | `crisp-v5.service` (systemd) | Parked, awaiting a rewritten SOUL.md for a meme-coin pivot |
| **Tao** | Bittensor TAO staking/DCA | `agents/tao/tao_*.py` | cron (5 jobs: data collector, subnet scorer, DCA engine, profit monitor, weekly compounder) | **Never actually staked anything** — all 5 cron lines have been `#HOLD` since 2026-07-25 on top of the global pause. SDK drift + a silent-failure bug in `run_btcli_stake()` (no on-chain confirmation). Hard-gated until TAO > $393 *and* two code fixes land |
| **Sentinel** | Insider/market-intel briefing script | `scripts/sentinel/run_sentinel.sh` | cron, 3x/day | Parked |
| **Jarvis** (internal id `strategist`) | Retired 2026-07-25, merged into Lens | `agents/strategist/` (archived in place, do-not-import) | n/a — cron lines `#HOLD RETIRED` | Retired |
| **Norman** | Retired 2026-07-25, split into Lens (Blade/Edge validation) + Victoria (Jerry/Chad validation); shared pipeline now lives once in `scripts/risk_validation.py` | `agents/norman/` (archived) | n/a | Retired |
| **Lucy** | Retired 2026-07-25, scouting folded into Victoria | `agents/lucy/` (archived) | n/a | Retired |
| **Phantom** | Futures orchestrator | `agents/phantom/phantom_trader.py`, `phantom_config.py`, `phantom_discover.py`, `phantom_backtest.py` | None — never wired to cron/systemd | Half-finished. Code exists but no strategy was ever completed, no scheduled run ever existed |
| **Forge, Naomi, Advisor** | Benched non-trading agents (dashboard builder, Etsy copywriter, old session-prep) | `agents/forge/`, `agents/naomi/`, `agents/advisor/` | None | Benched/idle since ~April 2026 |
| **Oracle** | Sports-betting / Kalshi prediction-market bot | `workspace/agents/oracle/oracle_bot.py` (outside the main `agents/` tree) | Deleted | **Deleted 2026-06-01** — ROI was −69%, settlement pipeline was never finished. Backed up to `/tmp/oracle_deleted_backup/` |
| **Kalshi** | Not an agent — vestigial integration only (see §3) | n/a | n/a | **Deleted 2026-06-01** alongside Oracle. Backed up to `/tmp/kalshi_deleted_backup/`. Never went live |

`telegram_monitor.py` (`telegram-monitor.service`) was built to feed Oracle-related Telegram
channels; since Oracle was deleted, this unit is now vestigial even if un-parked.

---

## 2. Services & ports

Confirmed via `ss -tlnp`: **nothing is currently listening on any of the ports below.**
There is no nginx/Caddy/reverse proxy anywhere on the box — in the prior live state these
services were bound directly to the internet on their raw ports.

| Service | Purpose | Port | Mechanism | Notes |
|---|---|---|---|---|
| `serve_hq.py` | Serves the React dashboard build (`hq-app/dist/`), serves raw `dashboard/*.json` files directly over HTTP, proxies `/hq/*` to the storage API, SPA-fallback routing | 8080 (legacy duplicate listener also found on 8899) | `jcf-hq.service` + user-level `openclaw-hq.service` (duplicate unit, same script) | No auth on any route |
| `hq_storage_server.py` | Flask API backing the dashboard — persists `accounts`, `income_entries`, `trading_accounts`, basketball data to `dashboard/hq_userdata.json`; exposes `/hq/edit/<filename>`, a generic endpoint that writes arbitrary values into `dashboard/<name>.json`; `/hq/hub/collab` shells out to `hub_collab.py`; read-only passthroughs for Jerry/Phantom/Victoria/Norman/Lucy/Forge/Kraken/TAO/Robinhood JSON; `/hq/agent-status` | 8900 | `hq-storage.service` | **No auth, CORS wide open (`*`) on everything.** If this were ever re-exposed without a proxy/auth layer in front, anyone reaching port 8900 could rewrite the financial dashboard data |
| **hq-app** | React 18 + TypeScript + Vite + Tailwind + framer-motion + recharts frontend | — | `npm run build` → static output served by `serve_hq.py` (not a separate dev server in production) | Stray empty tracked file `hq-app/R9Dc` (0 bytes, committed 2026-06-01) — harmless but worth deleting in a cleanup pass |
| **OpenClaw gateway** | The Telegram/Discord/MCP routing layer underlying the whole OpenClaw agent runtime (not HQ-specific) — hosts Huncho and the model-provider auth profiles (Anthropic/OpenAI/Google/Kimi/Moonshot/OpenRouter) | 18789 | `openclaw-gateway.service` (user unit, node, v2026.7.1-2) | Config in `openclaw.json` |
| `agents/discord_bot/bot.py` | Two-way Discord bot for `#ask-the-team` / `#risk-calculator` channels | — | pm2 app `jcf-discord-bot` | pm2 list is currently empty; a stale pidfile (`/root/.pm2/pids/jcf-discord-bot-0.pid`) remains from before the pause |
| `run_gdrive_sync.sh` | Mirrors `Vault/` + `CLAUDE.md` to Google Drive ("JCF HQ Vault") | — | cron, every 30 min | Outbound only. Auth: testing-mode OAuth, token expires ~7 days, was set to Telegram-alert on expiry. OAuth is currently **revoked** per prior memory — needs interactive re-auth before this can run again |

---

## 3. External APIs / integrations

**Credential locations are paths + variable NAMES only — no values were read or recorded.**

| Integration | Used by | Credential location (path + var names) | Notes |
|---|---|---|---|
| OANDA | Blade, Edge, Lens (regime/validation/live-turtle) | Account ID hardcoded in `agents/edge/edge_config.py` (`OANDA_ACCOUNT_ID`, `OANDA_ENVIRONMENT`); token meant to come from `auth-profiles.json` via `AUTH_PROFILES_PATH` | **Credential-path bug (see §5) — this path no longer exists.** Core instrument group for the one validated strategy |
| TradeLocker | `scripts/sync_tradelocker.py`, `agents/advisor/collect_data.py` | Password passed **inline, in plaintext, directly in the crontab line** — not in any `.env` | **Exposed secret, see §5.** The sync job itself has been `#HOLD`'d since 2026-07-27 (feed dormant since 2026-05-27), independent of the exposure issue |
| Phemex | Phantom (`agents/phantom/phantom_trader.py` etc.) | `PHEMEX_API_KEY`, `PHEMEX_API_SECRET` in `agents/phantom/.env` | Confirmed gitignored (`**/.env` rule) |
| Telegram | Multiple agents + `scripts/telegram_monitor.py` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` / `TELEGRAM_ALERT_CHAT_ID` / `TELEGRAM_UID` — split across per-agent `.env` files, e.g. `agents/tao/.env`, `agents/phantom/.env` | Not centralized — multiple bot tokens across different agents |
| Kalshi | Vestigial only — a provider stub in `auth-profiles`/sqlite, an unintegrated staged skill at `workspace/skills_staging/kalshi-trading/`, setup notes at `workspace/docs/kalshi_setup.md` (`KALSHI_ENV`, `KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`) | No `KALSHI_*` vars actually set anywhere live; `/root/.openclaw/kalshi_private_key.pem` is a 1-byte placeholder, never committed to git | Never went live; was meant for the deleted Oracle agent |
| **Notion** | **Not an integration that exists.** All hits were false positives (the substring "notional" in P&L code; an unrelated vendored Codex CLI plugin cache) | — | If this was expected to exist, it was never built |
| Kraken | `scripts/sync_kraken.py` | `KRAKEN_API_KEY`, `KRAKEN_API_SECRET` in root `/root/.openclaw/.env` | Also listed in the OpenClaw gateway's `OPENCLAW_SERVICE_MANAGED_ENV_KEYS` |
| Alpaca | Jerry | `ALPACA_API_KEY`, `ALPACA_API_SECRET` in root `.env`; `jerry.service` loads it via `EnvironmentFile=` | |
| Helius (Solana) | Crisp/Chad wallet intel | `HELIUS_API_KEY` in root `.env` | |
| Discord | `agents/discord_bot/bot.py` | `DISCORD_BOT_TOKEN`, `DISCORD_BROADCAST_WEBHOOK_01`–`16`, `DISCORD_ASK_TEAM_CHANNEL_ID`, `DISCORD_RISK_CALC_CHANNEL_ID` in root `.env` | |
| Plaid | `scripts/plaid/sync_plaid.py`, `sync_plaid_transactions.py`, `plaid_link_server.py` | Not in root `.env` — Plaid-specific credential file exists but wasn't individually located in this pass | Jobs are `#PARKED` |
| Robinhood / TrustWallet | `scripts/sync_robinhood.py` / `scripts/sync_trustwallet.py` | No `.env` vars found for either — likely session-cookie-based | Both parked/held |
| Google Drive | `scripts/gdrive_auth.py`, `scripts/gdrive_sync.py` | OAuth token under `credentials/gdrive/` | OAuth currently revoked per prior session notes — needs interactive re-auth |
| Anthropic / OpenRouter / GitHub | OpenClaw gateway + Claude Code sessions | `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `GITHUB_TOKEN` in root `.env` | |
| Bittensor/TAO | Tao agent | `WALLET_NAME`, `HOTKEY_NAME`, `COLD_KEY_MNEMONIC`, `HOT_KEY_MNEMONIC`, `COINGECKO_API_KEY` + its own Telegram vars, in `agents/tao/.env` | High-value secret (wallet mnemonics) — confirmed gitignored |

---

## 4. Folder structure & key files

```
/root/.openclaw/
├── CLAUDE.md, README.md, RESTART.md   — architecture docs; RESTART.md lists restart blockers
├── .env                                — root credential file (mode 600, gitignored)
├── agents/                             — one subdir per agent (see §1); several retired/archived in place
├── scripts/                            — cron-invoked jobs: sync_*.py (per-integration), sentinel/,
│                                          plaid/, hq_storage_server.py, serve_hq.py, run_*.sh wrappers
├── dashboard/                          — JSON state files the HQ UI reads/writes (net_worth.json,
│                                          jerry_portfolio.json, kraken_data.json, robinhood_data.json, etc.)
│                                          + _archive/ (quarantined stale data)
├── hq-app/                             — React/Vite dashboard frontend source; builds to hq-app/dist/
├── Vault/                              — curated knowledge base (agents/, decisions/, infrastructure/,
│                                          sessions/, strategies/), mirrored to Google Drive
├── credentials/                        — auth-profiles/, gdrive/ OAuth token, telegram pairing files
├── cron/                               — cron run logs/backups
├── workspace/                          — OpenClaw workspace; also holds workspace/agents/{blade,crisp,oracle}
│                                          (a separate, older agent tree outside the main agents/ dir)
├── crontab_backup_*.txt, crontab_held_*.txt, crontab_halt_backup.txt
│                                        — historical crontab snapshots, **currently git-tracked** (see §5)
├── gateway.systemd.env                 — OpenClaw gateway env file (gitignored)
├── kalshi_private_key.pem              — 1-byte placeholder, never used, never committed
└── docs/STANDBY.md                     — standby-state notes
```

Systemd units live outside this tree at `/etc/systemd/system/{jcf-hq,crisp-v5,edge,hq-storage,jerry,
telegram-monitor}.service` and `/root/.config/systemd/user/{openclaw-gateway,openclaw-hq}.service`.

Git remote: `origin → https://github.com/Jrock1299/JCF-HQ.git`, branch `master`, 214 commits
(2025-10-22 → 2026-08-11, HEAD `5f0e8a0`). Repo responds `200` to an unauthenticated fetch,
**consistent with public but not independently confirmed** (no `gh` auth available in this
environment) — verify visibility directly in GitHub repo Settings.

---

## 5. Broken, disabled, or half-finished

### Security — exposed secrets (act on these)
1. **TradeLocker password committed in plaintext, currently tracked at HEAD.** At least
   8 commits and 9+ currently-tracked crontab-backup files (e.g.
   `crontab_backup_full_pause_20260811-130950.txt`, `crontab_halt_backup.txt`,
   `crontab_held_2026-07-21.txt`, files under `cron/`) contain a plaintext
   `TRADELOCKER_PASS=...` assignment inline before the `sync_tradelocker.py` call. This is
   **not just old history** — the files are tracked right now on `master`. `.gitignore` has
   no rule for `crontab_backup*` / `crontab_held*` / `crontab_halt*`, so new backups will
   keep leaking it. **Needs: rotate the TradeLocker password, remove/scrub the tracked
   backup files from the repo, add a gitignore rule.** (No value reproduced anywhere in this
   audit or this file.)
2. **Public repo tracks real financial data.** `dashboard/jerry_portfolio.json`,
   `dashboard/kraken_data.json`, `dashboard/net_worth.json`, and the `dashboard/public/`
   copies of `net_worth.json` / `robinhood_data.json` are currently tracked in git. Per prior
   session notes, Jase was told about this risk and chose to accept it rather than scrub —
   treating as a known/accepted risk here, not re-flagging as new, but noting it persists.
3. Everything else checked clean: `.env`, `*secret*`, `*credential*`, `*.pem` files were
   never committed to history; `gateway.systemd.env` has been gitignored since its creation;
   `kalshi_private_key.pem` has zero git history; all per-agent `.env` files (`agents/tao/.env`,
   `agents/phantom/.env`, etc.) are covered by the `**/.env` gitignore rule.

### Functional bugs blocking a restart
4. **Credential-path bug (still unfixed, 3+ months later).** The 2026-07-30 OpenClaw update
   migrated `agents/main/agent/auth-profiles.json` into `openclaw-agent.sqlite`
   (table `auth_profile_store`) and deleted the JSON file. **8 scripts still hard-code the
   dead path** and will crash instantly on restart: `agents/strategist/strategy_engine.py`,
   `agents/lens/lens_regime.py`, `agents/lens/live_turtle_executor.py`,
   `agents/crisp/crisp_config.py`, `agents/advisor/session_prep.py`,
   `agents/edge/edge_config.py`, `agents/blade/bot/dry_run_today.py`,
   `agents/blade/bot/blade_bot.py` — plus a stale duplicate at
   `workspace/agents/blade/bot/blade_bot.py`. This is what silently killed Blade, Edge, and
   the Lens regime briefs for 12 days before the pause.
5. **Tao staking never actually fired.** `run_btcli_stake()` has an SDK-drift bug that fails
   silently with no on-chain confirmation; all 5 Tao cron jobs were `#HOLD`'d on 2026-07-25,
   independent of the global pause. Explicitly hard-gated by Jase until TAO > $393 and the
   code is fixed.
6. **Blade `PIP_VALUE` bug** — P&L is mis-stated for CHF_JPY/DE30_EUR. Documented, unfixed,
   flagged "fix before live trading."
7. **The one validated strategy (Turtle Soup / sweep-fade on SPX500_USD, DE30_EUR, XAU_USD)
   has never traded live.** It is mean reversion, not ICT — 0 of 28 ICT models validated,
   and ICT filters were found to remove winning trades.
8. **Jerry graded FAIL** by Victoria (2026-08-09): 121 trades, 36.4% win rate, profit factor
   0.951, −$1,121.59, expectancy −$9.27. Correctly being kept parked on its own merits.

### Half-finished / abandoned
9. **Phantom** — futures-trading code exists (`phantom_trader.py`, `phantom_config.py`,
   `phantom_discover.py`, `phantom_backtest.py`) but was never wired to cron or systemd and
   never had a complete strategy.
10. **Oracle + Kalshi** — fully deleted 2026-06-01 after Oracle's sports-betting line lost
    −69% ROI and its settlement pipeline was never finished. Backups retained at
    `/tmp/oracle_deleted_backup/` and `/tmp/kalshi_deleted_backup/`.
11. **Forge, Naomi, Advisor** — benched, idle since ~April 2026, no cron/service ever wired.
12. Stale cross-references to retired agent ids (Jarvis/Norman/Lucy) remain in Discord
    fanout/risk-calc config — flagged in `CLAUDE.md` as deliberately-unfixed cleanup debt.
13. **Google Drive Vault sync** OAuth token is revoked — needs interactive re-auth before
    `run_gdrive_sync.sh` can run again, independent of the global pause.
14. Minor: stray empty tracked file `hq-app/R9Dc` (0 bytes) — harmless, worth deleting in a
    cleanup pass.

---

**Bottom line:** the parked state is real and verified live, not just documented. Before any
restart: read `RESTART.md`, fix the 8-script credential-path bug (#4), rotate the TradeLocker
password and scrub the tracked crontab backups (#1), and decide what to do about the public
repo's tracked financial-data files (#2) and PnL-affecting Blade bug (#6).
