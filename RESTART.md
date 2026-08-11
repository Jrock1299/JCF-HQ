# RESTART.md — How to bring JCF HQ back

**Parked:** 2026-08-11 by Jase's decision, to focus on personal trading.
**Nothing was deleted.** All research, strategies, indicators and the Vault are intact.
Everything was stopped cleanly and is restartable.

Read this whole file before turning anything back on. There are four known
blockers. If you re-enable the crons without clearing them first, the system will
go straight back to crash-looping silently — which is exactly what it was doing
for the twelve days before it was parked.

---

## 1. The honest state of things

### There is exactly ONE validated strategy

**Turtle Soup / sweep-fade**, on three instruments: `SPX500_USD`, `DE30_EUR`, `XAU_USD`.

Two things about it you need to remember, because they are easy to misread later:

1. **It is mean reversion, not ICT.** The research set out to validate ICT/smart-money
   models. 28 were tested; **0 of 28 passed.** What survived was a plain post-sweep
   fade. The ICT filters (H4 bias, London/NY killzones) actively *removed winning
   trades* — the 24/7 baseline beat the filtered version on every headline metric.
   The library records this in each entry's `mechanism_label`. Don't let a future
   session re-label this as an ICT win.

2. **It has never actually traded.** Not once. It was deployed to live paper
   executors on 2026-07-28, and every single invocation since 2026-07-30 has
   crashed before placing an order (see Blocker A). Its live track record is not
   "bad" — it is **empty**. There is no live evidence for or against this edge.

The other **25 researched models are retained** in the library as
`not_validated`, deliberately, so the work is preserved and cannot be mistaken
for approval.

### Everything else

- **Jerry** — graded **FAIL** by Victoria on 2026-08-09: 121 trades, 36.4% win
  rate, 0.951 profit factor, −$1,121.59 total, −$9.27 expectancy per trade.
  Recommendation was *keep parked*. Do not restart Jerry without a setup-level
  attribution of what is destroying expectancy. Note its last 4 records are
  `UNVERIFIED_NO_EXIT_FILL` with `pnl: null` — those are **ungradeable, not $0**.
- **Blade / Edge** — live turtle executors, crash-looping, zero trades.
- **Crisp** — service was already dead and disabled before the pause.
- **Lens** — regime briefs dead since Jul 30 (same Blocker A).
- **Victoria, Sentinel, Council** — were running fine up to the pause.

---

## 2. Blockers to clear BEFORE re-enabling anything

### Blocker A — the credential-path bug (this is the big one)

The `openclaw` update on **2026-07-30** migrated `auth-profiles.json` into
SQLite and **deleted the JSON file**:

- Gone: `/root/.openclaw/agents/main/agent/auth-profiles.json`
- Now lives in: `agents/main/agent/openclaw-agent.sqlite`, table `auth_profile_store`
- Migration receipt: `agents/main/agent/auth-profiles.json.sqlite-import.1785432524882.bak`

**Eight scripts still hard-code the dead path** and crash instantly on startup:

| File | Note |
|---|---|
| `agents/lens/live_turtle_executor.py:76` | Blade + Edge executors — 552 + 184 logged crashes |
| `agents/lens/lens_regime.py:76` | twice-daily regime brief |
| `agents/lens/ict_data.py` | |
| `agents/blade/bot/blade_bot.py` | |
| `agents/edge/edge_config.py` | |
| `agents/crisp/crisp_config.py` | |
| `agents/advisor/session_prep.py` | |
| `scripts/system_status_report.py` | |

**The fix (not done — deliberately left for you):** write one shared credential
accessor that reads `auth_profile_store` from the SQLite DB, with a JSON
fallback, and repoint all eight call sites at it. It is a contained change and it
revives Blade, Edge and the Lens regime brief together.

### Blocker B — the OANDA auth question (unresolved)

This one matters and is *not* the same as Blocker A. Look at
`logs/live_turtle.log`: **before** the FileNotFoundError started appearing, the
log was already showing:

```
V20Error: {"errorMessage":"Insufficient authorization to perform request."}
```

on SPX500, DE30 and XAU. So OANDA was **already rejecting the credentials**
before the file disappeared. Fixing Blocker A may simply uncover this older
problem underneath.

**It was never verified whether the `oanda:default` profile survived the SQLite
migration at all.** Check that first — before writing any code. If the profile
didn't survive, or the token is dead, you need fresh OANDA practice credentials.

### Blocker C — the watchdog gap

`scripts/live_turtle_first_fire.py` logged **690 heartbeats** reading
`waiting on: ['blade','edge']` while the executors were crashing every 15
minutes. It cannot tell *"no signal yet"* from *"the executor is dead."*

That gap is arguably worse than the bug it failed to catch — it is why nobody
noticed for twelve days. **Fix this before re-enabling live trading**: make it
alert on N consecutive executor errors, not just on silence.

### Blocker D — billing

- **Anthropic:** `credit balance is too low to access the Anthropic API` — agents
  were 400ing. Needs credit before Victoria/Lens/Council will run.
- **Codex:** subscription usage limit hit; **resets 2026-08-23**.
- Recorded API spend was modest: **$3.70 month-to-date** against a $50 ceiling
  (`dashboard/api_costs.json`), so cost was never the problem — the balance was.

### Also broken (lower priority)

- **Google Drive sync:** OAuth refresh token expired/revoked
  (`invalid_grant`). Needs **interactive** re-auth — run `scripts/gdrive_auth.py`
  yourself; a script can't do it unattended. The token is testing-mode and
  expires roughly weekly, so expect this again.
- **Sentinel:** intermittent Finnhub `insider-sentiment` read timeouts. Noisy but
  probably transient.

---

## 3. How to turn it back on, in order

Do these in sequence. Don't skip ahead — each step depends on the one before.

**Step 0 — clear Blockers A, B and D first.** Nothing below will work otherwise.

**Step 1 — the gateway** (this is a *user* unit, not a system unit):
```bash
systemctl --user enable --now openclaw-gateway
systemctl --user is-active openclaw-gateway     # expect: active
```
This is also what reconnects Telegram, so expect notifications to resume here.

**Step 2 — the dashboard** (read-only, safe, no trading, no spend):
```bash
systemctl enable --now jcf-hq        # port 8080
systemctl enable --now hq-storage    # port 8900
```

**Step 3 — the crons.** The entire crontab was preserved in place. Every active
line was prefixed with `#PARKED 2026-08-11 `. To restore a line, strip that
prefix. To restore *everything* at once (**not recommended** — see below):
```bash
crontab /root/.openclaw/crontab_backup_full_pause_20260811-130950.txt
```

Re-enable selectively instead, cheapest and safest first:
1. `sync_dashboard_public.sh`, `sync_agent_pnl.py`, `sync_api_costs.py` — plumbing, no spend
2. Sentinel — read-only market data
3. Lens regime briefs — **only after Blocker A is fixed**
4. Victoria / Council — **only after Blocker D is fixed** (they burn LLM credit)
5. Live turtle executors — **only after A, B *and* C are fixed**

**Step 4 — leave parked unless you have a reason:**
- **Jerry** (`jerry.service`) — graded FAIL, keep parked
- **Crisp** (`crisp-v5.service`) — already dead pre-pause
- **Edge** (`edge.service`), **telegram-monitor.service**
- Everything already marked `#HOLD` or `#HOLD RETIRED` in the crontab — those
  were Jarvis/Norman/Lucy, retired 2026-07-25. Leave them retired.

---

## 4. Where the real assets live

| What | Where |
|---|---|
| **Validated strategy library** | `dashboard/strategy_library.json` — 3 validated entries + 25 retained not-validated. Written by `lens/ict_research.py`; read by blade, edge, jerry, chad. Nothing in it self-deploys. |
| **Pine indicators** (TradingView) | `tradingview/meanrev_sweep_fade.pine`, `sweepfade_ES.pine`, `sweepfade_NQ.pine`, `sweepfade_GC.pine` — the ES/NQ/GC ones are **BETA, research/watch only, NOT validated** |
| **The Vault** | `Vault/` — 42 markdown notes, 420K |
| **Full pre-pause crontab** | `crontab_backup_full_pause_20260811-130950.txt` |
| **Validation verdicts** | `dashboard/lens_validation.json` (Blade/Edge), `dashboard/victoria_validation.json` (Jerry/Chad) — use these, **not** the retired `norman_report.json` |
| **Old gateway job scheduler** | `cron/jobs.json` deletion was committed — it migrated into SQLite on 2026-07-07 and today's openclaw no longer reads it. All 16 jobs were already disabled. Content preserved in git history plus `cron/jobs.json.bak` and `cron/jobs.json.migrated`. |

---

## 5. If you only read one paragraph

The operation is off, cleanly, and nothing is lost. You have one genuinely
validated edge — a sweep-fade mean-reversion strategy on SPX500/DE30/XAU — and
it has **never been tested against a live market**, because a credential path
broke on 2026-07-30 and a blind watchdog reported the resulting crash loop as
patience. So the honest position is: you have a promising backtest and zero live
evidence. If you come back, fix the credential accessor, verify OANDA actually
authenticates, fix the watchdog so it can never lie to you again, and only then
let it trade. Jerry is a proven loser — leave it parked. The 25 unvalidated ICT
models are kept as research, not as a to-do list.
