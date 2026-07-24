# JCF HQ — Master Context

> **Read this top-to-bottom.** This file is the single source of truth for the
> current state of JCF HQ. The code in this repo and this document are
> authoritative — not conversational memory, not older docs, not screenshots.
> If something is in this file, it's current. If it's not, assume it doesn't
> exist or was deleted.
>
> **Last updated:** 2026-07-24 (see `git log` for revision history).

---

## 1. System Overview

**JCF HQ** is Jase's personal multi-agent trading and finance operations
center. A roster of specialized agents — each with its own job, voice, and
schedule — runs autonomously on a VPS, coordinated by Huncho (the
orchestrator) and reporting to Jase via Telegram.

### Mission
Build, validate, and operate an automated trading system across forex,
indices, crypto, and equities while keeping risk under explicit rails and
turning every trade into structured learning data.

### Three-environment model
- **VPS** (`/root/.openclaw/`) — production. Cron-driven agents run here.
  Talks to OANDA, Binance, Alpaca, Telegram. This is what trades.
- **Laptop Claude Code** — development and code work. Edits sync via this
  GitHub repo (`Jrock1299/JCF-HQ`).
- **GitHub (`master` branch)** — the shared spine. Push from either
  environment; pull on the other. **The code + this file = source of truth.**

### Key principle
Conversations end; the code persists. Anything important about how the system
behaves lives in code, config files, or this CLAUDE.md. Do not rely on
remembering — write it down here.

---

## 2. Active Agents

**Fleet state (2026-07-24):** the fleet is back online after the June hold —
**19 active agent cron lines** (plus supporting infra, 29 active cron lines
total). Live on cron: **Lens, Blade** (3 sessions), **Jarvis** (2 briefings),
**Lucy, Tao** (5 jobs), **Victoria** (daily+weekly), **Norman, Sentinel** (3×),
plus the Drive-sync and Blade support crons (session prep/end pings, agent-PnL,
TradeLocker sync, dashboard mirror), plus the **Kraken** sync (keys wired
2026-07-24). **Held:** **Jerry** (migrated to Codex 2026-07-24 but `jerry.service`
not yet started — awaiting go-ahead), **Edge** (systemd — down on a missing OANDA
`auth-profiles.json`), **Robinhood** sync, and **Crisp/Phantom** (parked). **Lens
is now the only Anthropic-billed cron agent.** Internal agent ID shown in
`code-format`; display name (Telegram header) shown in **bold**.

### 👑 **HUNCHO** — `huncho`
**Job:** Orchestrator. Telegram router. Kill-zone scheduler. Don personality
(NY mob-boss energy: terse, knowing, slightly amused — "Aye." "My guy."
"— H").
**Model:** Codex (`openai/gpt-5.3-codex` via the Codex runtime) for chart
analysis / message routing; reasoning agents he delegates to use their own
models.
**Schedule:** Always-on via Telegram gateway; session-prep pings 10 min
before each Blade session.
**Key files:**
- `agents/huncho/killzone_sync.py`
- `agents/main/skills/chart_analysis.py` (on-demand chart reads)
- `scripts/session_prep_ping.sh` (auto 4H reads, see §4)
- `scripts/telegram_personalities.py` (personality wrapper)

### 🔪 **BLADE** — `blade`  ← **PRIMARY TRADING AGENT**
**Job:** Pure 15-min ORB breakout bot on SPX500, DE30, CHF/JPY.
**Sessions (UTC, Mon–Fri):**

| Session | Cron  | Open  | Close | Instruments |
|---------|-------|-------|-------|--------------------------------|
| ASIA    | 23:50 | 00:00 | 06:00 | SPX500_USD                     |
| LONDON  | 07:55 | 08:00 | 12:00 | SPX500_USD, DE30_EUR, CHF_JPY  |
| NY_PM   | 17:55 | 18:00 | 21:00 | SPX500_USD                     |

**Logic:** Wait for session open → record first 15m candle's H/L (= ORB) →
poll M1; first M1 close beyond ORB level wins → enter 3 paper positions
sized off real stop distance.

**D3 SIZING (the current design — Norman fixed Blade's broken R:R math)**

Norman flagged Blade as FAIL: 53% WR was fine but PF=1.114 and max DD=72.9%
because the old TPs (3/5/10pt) were sub-1R against a typical ~12pt ORB stop —
two of three positions had inverted reward-to-risk.

**Now (D3):**
- Stop: structural — opposite ORB level ± 3pt buffer. Real stop distance.
- Risk per cluster: **2% of current balance**, split by weights.
- Position weights: **pos1 20% / pos2 30% / pos3 50%** of cluster risk.
- TPs as **R-multiples** of the actual stop:
  - pos1 → 1R
  - pos2 → 2R
  - pos3 → **trailing stop** at 1R below high-water (no hard cap)
- After pos1 TP fires: pos2 SL → BE, pos3 SL → BE + trailing activates.
- Sizing uses **real** stop distance (units = `int(per_pos_risk_$ / (stop_pts × pip_value))`).
  Old code used the 3pt buffer as divisor — bug, fixed.
- **Rails (hard):** ≤1% per single trade, ≤2% per cluster, -4% daily
  drawdown circuit breaker, min 1.5:1 cluster R:R (D3 = 3.3:1 best case).
- **Compounding:** balance persisted in `dashboard/blade_balance.json` between
  sessions. Default $5,000 if missing. Session-start reload + session-end save.
- **Daily DD breaker:** state in `/tmp/blade_dd_<UTC-date>.json`. Halts all
  remaining sessions today once breached. Resets next UTC day.
- **Min balance floor:** $100 (refuse to trade below this).

**Key files:**
- `agents/blade/bot/blade_bot.py` — D3 engine
- `agents/blade/bot/run_session.sh` — cron wrapper
- `agents/blade/bot/blade_learning_analyzer.py` — Phase 1 stub (see §4)
- `dashboard/blade_balance.json` — compounding balance
- `dashboard/blade_learning_log.json` — Phase 1 context dataset
- `dashboard/agent_strategies.json` (`"blade"` block) — all tunable knobs

**Status:** Active on paper. Reset 2026-06-01 to $5,000 clean. Norman D3
validation at 100 closed clusters before any live deployment.

### 📡 **EDGE** — `edge`
**Job:** 1H SMA 8/21 crossover on SPX500_USD only (OANDA practice account
`101-001-22502524-002`).
**Logic:** Cross fires → check optional H4 trend filter → open 3-position
cluster (3 × `UNITS` aggregate market order) → pos1 TP +15pt, pos2 TP +25pt,
pos3 trails the 21 SMA (closes when 1H candle closes through SMA21).
**Risk:** Max 5 losing clusters/day, halts at -2% intraday DD, 15-min
market-open blackout.
**Schedule:** Continuous loop (5-min tick) via the `edge` systemd service or
manual launch.
**Status:** Active. ~2,474 historical closed positions, -$1,226 cumulative
PnL on the $5,000 starting balance (Norman: INSUFFICIENT_DATA on the
post-rebuild dataset because the strategy was reset).
**Key files:**
- `agents/edge/edge_main.py`
- `agents/edge/edge_config.py` (knobs sourced from `agent_strategies.json`)
- `agents/edge/edge_oanda.py`
- `dashboard/edge_learning_log.json`

### 📊 **JERRY** — `jerry`
**Job:** Autonomous stocks + options paper trader on Alpaca.
**Model:** `openai/gpt-5.6-terra` via Codex (discovery & review; migrated off
the Anthropic SDK 2026-07-24). Trade execution is deterministic Alpaca REST.
**Cycle (UTC):**
- 13:00 — pre-market discovery run (Claude reasons about Sentinel + market context)
- 13:30–20:00 — 5-min trading ticks against the day's watchlist
- 20:30 — daily review
- ~$25K safety floor (pauses if portfolio drops below 25% of starting)
**Schedule:** Always-on via `jerry.service` (systemd).
**Status:** Active, paper trading.
**Key files:**
- `agents/jerry/jerry_main.py` / `jerry_trader.py` / `jerry_discover.py`
- `agents/jerry/jerry_context.py` — reads Lens/Jarvis/Norman before every entry
- `dashboard/jerry_learning_log.json`

### 🌐 **LENS** — `lens`
**Job:** Daily macro analyst. Web-searches + analyzes BTC/USDT, XAU/USD,
US100, SPX500, US OIL. Outputs bias + confidence per pair, plus a morning
report and priority list.
**Model:** `claude-sonnet-4-6` with web_search tool.
**Schedule:** `55 4 * * 1-5` (04:55 UTC, before all sessions).
**System prompt:** Includes baked-in methodology from `market-news-analyst`
and `market-environment-analysis` skills — impact-scored news, 4-dimension
environment assessment (trend / risk sentiment / volatility / sector rotation).
**Key files:**
- `agents/lens/lens_brain.py` (the only live entrypoint; legacy `bot/run_lens.sh` deprecated)
- `agents/lens/run_lens_brain.sh`
- `dashboard/market_bias.json` (the file every downstream agent reads)

### ⚠️ **NORMAN** — `norman`
**Job:** Risk validator. Monte Carlo on every trading agent's closed trades.
Issues PASS / FAIL / INSUFFICIENT_DATA verdict + recommendation. Brutally
honest by design.
**Model:** `openai/gpt-5.6-terra` via Codex runtime (migrated 2026-07-24 off the
Anthropic SDK, using Lucy's `openclaw agent` subprocess pattern; bumped 5.5→5.6
Terra same day). No tools.
**Schedule:** `0 10 * * 6` (Saturday 10:00 UTC weekly).
**System prompt:** Includes `backtest-expert` 6-phase stress-test methodology
(hypothesis → backtest ≥5yr → parameter sensitivity ±15-30% → 1.5-2× slippage
→ walk-forward → 5-dimension score) and `position-sizer` guardrails (≤1%
per trade, Half-Kelly not full, 6-8% portfolio heat ceiling).
**Verdict rules:** PF<1.2 = MARGINAL, PF>1.5 = STRONG. Sharpe<0.5 = FAIL.
Ruin prob >10% = FAIL.
**Key files:**
- `agents/norman/norman_brain.py`
- `agents/norman/run_norman.sh` (has the `set -a / source .env / set +a` fix)
- `dashboard/norman_report.json`

### 🧛‍♀️ **VICTORIA** — `victoria`
**Job:** CFO + Chief of Staff. Reads everything (TradeLocker, Edge, Tao,
Norman, Lens, Sentinel, Plaid, Robinhood, Trustwallet, Kraken). Produces a
daily Telegram financial summary + operations briefing + recommendations +
fix_prompts. Persona: gothic queen — owns the operation, never coddles.
**Model:** `openai/gpt-5.6-terra` via Codex runtime (migrated 2026-07-24 off the
Anthropic SDK, using Lucy's `openclaw agent` subprocess pattern; bumped 5.5→5.6
Terra same day). Persona is prepended into the user message since the gateway
agent has no `system` slot; voice verified intact on test runs. No tools.
**Schedule:**
- Daily: `0 21 * * *` (21:00 UTC) — daily report
- Weekly: `0 7 * * 1` (Monday 07:00 UTC) — weekly tribunal
**Key files:**
- `agents/victoria/victoria_brain.py`
- `agents/victoria/run_victoria.sh` (has the `.env` source fix)
- `dashboard/victoria_report.json` / `victoria_weekly.json`

### ♟️ **JARVIS** — internal id `strategist`
**Job:** Pre-session market regime briefing. Calm, precise right-hand-man.
**Model:** Codex (`openai/gpt-5.6-terra`, fallback `openai/gpt-5.5`) via
`openclaw infer model run`. (Sol would suit regime reasoning but is unavailable
on this Codex OAuth backend — it 400s — so Terra is the top working tier.)
**Schedule:**
- `0 6 * * 1-5` (pre-London brief, 06:00 UTC)
- `0 12 * * 1-5` (pre-NY brief, 12:00 UTC)
- `0 8 * * 6` (Saturday deep_backtest)

**Output JSON** (`dashboard/strategy_recommendation.json`): per-instrument
`{regime, bias, lens_bias, lens_confidence, adr, current_price}` + overall
regime + Monte Carlo block.

**System prompt** includes `macro-regime-detector` (Concentration / Broadening
/ Contraction / Inflationary / Transitional), `market-breadth-analyzer`
(0-100 composite, exposure recommendations), and `sector-analyst`
(cyclical/defensive leadership) methodologies.

**Important:** Jarvis briefs, **does not gate**. The 0-100 convergence score,
strategy-selection logic, FVG detection, and edge-map were all deleted in
the 2026-06-01 trim — they were dead code that no trading agent read. Edge
map functions retained only because `deep_backtest.py` uses them.

**Telegram header:** ♟️ JARVIS (internal id `strategist` → display name
`JARVIS` via `AGENT_DISPLAY` alias map in `telegram_personalities.py`). Signs
every briefing `— Jarvis`.

**Voice:** Composed, intelligent, subtly confident. Three steps ahead but
never showy. Brief. Direct. No filler. Example: *"Morning read is in. SPX
is range-bound, Lens is neutral. I'd keep expectations measured today.
— Jarvis"*

**Key files:**
- `agents/strategist/strategy_engine.py` (lean, 446 lines)
- `agents/strategist/run_research.sh` (narrative via Codex + Telegram via `--target` flag)
- `agents/strategist/deep_backtest.py` (Saturday weekly; needs `oandapyV20` + `ccxt` in venv)
- `agents/strategist/CLAUDE.md` (full Jarvis brief)

### 🔍 **SENTINEL** — script, not an agent personality
**Job:** Insider trading + market intel pipeline. Pulls 13F / Form-4 data
and watchlist signals from Finnhub + FMP free tiers.
**Schedule:** `0 8 * * 1-5`, `0 14 * * 1-5`, `0 20 * * 1-5` (3×/day).
**Watchlist:** Read from `dashboard/watchlist.json` (Jase's by-theme holdings)
with hardcoded fallback in `sentinel_sync.py`.
**Output:** `dashboard/sentinel_data.json` (watchlist signals, top
discoveries, analyst recs, earnings calendar, market news).
**Consumed by:** Jerry (gates discovery), Victoria, the Intelligence dashboard.

### ☯️ **TAO** — `tao`
**Job:** Bittensor TAO staking + DCA + subnet scoring. Passive allocation,
not active trading.
**Schedule (UTC):**
- Data collection: `0 3,11,19 * * *` (3×/day)
- Subnet scoring: `0 6 * * *`
- DCA engine: `0 9,21 * * *`
- Profit monitor: `0 0,6,12,18 * * *` (4×/day)
- Saturday compounder + weekly report: `0 8 * * 6`
**Key files:** `agents/tao/tao_*.py` (separate scripts for each cycle)
**Knobs:** in `tao_config.py` (env-gated; should eventually migrate to
`agent_strategies.json`).

### 🔍 **LUCY** — `lucy`
**Job:** Weekly skills/tools/MCP research scout. Searches GitHub, Reddit,
HackerNews, Product Hunt, Anthropic docs, MCP registries.
**Schedule:** `0 12 * * 0` (Sunday noon UTC).
**Output:** Suggestions for new skills / MCPs / tools to evaluate.
**Status:** Active but low-traffic. Not a trading agent. (Considered for
benching once — kept active by Jase.)

---

## 3. Benched / Parked Agents

These have **code on disk** but are **not running**. They will not appear in
cron, systemd, or Telegram. Their dirs are preserved for revival.

### Benched (not running, not currently planned)
| Agent | Was | Why benched |
|---|---|---|
| **Forge** | HTML dashboard / Excel builder via Claude | Idle since 2026-04-17. Creator/product tooling, not trading. |
| **Naomi** | Etsy listing copywriter for Forge products | Idle since 2026-04-15. E-commerce, not trading. |
| **Advisor** | Old session prep — replaced by Victoria | Retired 2026-04-15. Cron entries fully removed. |

### Parked (awaiting rebuild)
| Agent | Was | Pending |
|---|---|---|
| **Crisp** | BTC/USDT multi-strategy bot. `crisp-v5.service` (now `failed`). | Awaiting **meme coin pivot** — new SOUL.md + strategy. Cron line commented out in crontab. Trade history preserved. |
| **Phantom** | Futures orchestrator (5-min cycle). Service `inactive`. | Awaiting **strategy build** — collaborative, data-driven design pending data accumulation. |

---

## 4. Key Architecture

### 4a. Cross-agent communication layer (Phase 1 — observation only)

**Principle:** Trading agents SEE shared context but DO NOT GATE on it.
Everything is logged for later analysis.

**The wire diagram:**
```
   Lens (market_bias.json)      ─┐
   Jarvis (strategy_rec.json)   ─┼─→  Blade   ─→ blade_learning_log.json
   Norman (norman_report.json)  ─┤    Edge    ─→ edge_learning_log.json
   H4 read (scripts/h4_read.py) ─┘    Jerry   ─→ jerry_learning_log.json
```

Each closed position writes a record with: `regime_at_entry`,
`strategist_bias_at_entry`, `lens_bias_at_entry`, `lens_confidence_at_entry`,
`strategist_aligned` (bool), `norman_verdict_at_entry`,
`norman_ruin_prob_at_entry`, `h4_read_at_entry`, plus Blade-specific
`orb_range_pts`, `stop_pts`, `breakout_distance_pts`, `pos3_trail_r_achieved`.

**The H4 read** (`scripts/h4_read.py`): structured 4H technical read built
from OANDA candles + indicators + Codex (gpt-5.5) narrative. Cached 30 min
per instrument. Delivered to Telegram 10 min before each session via
Huncho (`session_prep_ping.sh`). Same read is stamped onto every position.

**Phase 1 (now):** Observation. Blade/Edge/Jerry take every valid setup
their existing rules generate. Context just rides along.

**Phase 2 (gated on Norman validation):** Once a learning log accumulates
100+ closed records, `blade_learning_analyzer.py` (currently a stub)
buckets the data by regime × alignment × Norman verdict × ORB quality and
hands it to Norman. Norman validates whether any pattern is statistically
real (≥30 trades/bucket, MC p5 > 0).

**Phase 3 (only after Norman PASS):** A separate, explicit PR wires the
validated pattern into the agent as a soft filter or sizing modifier. Even
then it's never a hard binary gate.

### 4b. Centralized config

| File | Purpose |
|---|---|
| `dashboard/agent_strategies.json` | Risk knobs per agent (Blade D3, Edge, Norman, Sentinel). Tunable without code edits. |
| `dashboard/watchlist.json` | Jase's by-theme tickers. Read by Sentinel. |
| `scripts/agent_config.py` | Shared loader — `load_strategy(name, defaults)`. Falls back to defaults if file/key missing. Non-breaking by design. |
| `agents/strategist/CLAUDE.md` | Jarvis identity + voice. |
| Agent system prompts (in `*_brain.py`) | Skills methodology baked in (see §2 each agent). |

### 4c. Personality system

`scripts/telegram_personalities.py`:
- `AGENT_EMOJIS` — emoji per agent
- `AGENT_DISPLAY` — alias map: internal id → Telegram display NAME
  (e.g. `strategist → JARVIS`)
- `wrap_message(agent, body)` — emoji header + body + `— via H` footer
  (Huncho omitted — his messages already sign `— H`)

Each agent has its own voice:
- **Huncho:** NY mob-boss. Terse, knowing. "Aye. My guy. — H"
- **Jarvis:** calm right-hand-man. "Morning read is in. I'd keep expectations measured. — Jarvis"
- **Blade:** stoic military. "LONG SPX500 @ 7600 | SL 7582 | TPs 1R/2R/TRAIL"
- **Edge:** clinical/laconic.
- **Jerry:** professional money manager.
- **Lens:** macro analyst.
- **Norman:** brutally honest, cold ("FAIL. Sharpe 0.012. Suspend live trading.").
- **Victoria:** CFO with gothic-queen energy. Owns the operation.
- **Tao:** zen.

### 4d. Model routing

| Agent | Primary | Why |
|---|---|---|
| Lens | `claude-sonnet-4-6` (Anthropic SDK) | web_search depth + structured JSON. **Only** remaining Anthropic-billed cron agent. |
| Norman, Victoria, Lucy | `openai/gpt-5.6-terra` via Codex runtime (`openclaw agent` subprocess, Lucy pattern) | Migrated 2026-07-24; bumped 5.5→5.6 Terra. Override id must be a **plain** tier id AND whitelisted in `agents.defaults.models` — the `-codex` suffixed ids are runtime-bound and rejected as `--model` overrides. Terra + Luna work; **Sol 400s** on this backend and plain `gpt-5.6` is unknown. |
| Jarvis, H4 reads, Huncho narratives | `openai/gpt-5.6-terra` via `openclaw infer model run`, fallback `openai/gpt-5.5` → `openrouter/auto` | `infer model run` is not gated by the allow-list. Retired: `gpt-5.2-codex` / `gpt-5.3-codex`. |
| Jerry brain | `openai/gpt-5.6-terra` via Codex (`_run_codex` in `jerry_config.py`) | **Migrated 2026-07-24** off the Anthropic SDK (discover + review). Discovery keeps web search via the gateway agent's own tools (like Lucy). `jerry.service` still held — not started pending go-ahead. |
| Blade, Edge | none (pure algorithmic bots) | No LLM calls at runtime. The stale `openai/gpt-5.3-codex` entries under `agents.list` (crisp/blade/oracle), the duplicate in `agents.defaults.model.fallbacks`, and the dead allow-list entry were **pruned 2026-07-24** via `openclaw config patch`. |
| chart_analysis.py | Image-capable models with fallback list: `codex/gpt-5.4` → `codex/gpt-5.5` | Default `moonshot/kimi-k2.5` is currently suspended for billing — do NOT use until restored. |

**Critical .env auth fix:** Anthropic SDK calls fail with *"Could not resolve
authentication method"* unless the run script sources `/root/.openclaw/.env`.
Every run script that calls `anthropic.Anthropic()` must include:
```bash
set -a
source /root/.openclaw/.env
set +a
```
Currently applied in: `run_lens_brain.sh`, `run_victoria.sh`, `run_norman.sh`.
**If you add a new Anthropic-using agent, add this block to its launcher.**

### 4e. Google Drive Vault mirror

Mirrors `CLAUDE.md` + `Vault/**/*.md` to a Google Drive folder (**"JCF HQ
Vault"**) so Claude (chat) can read current project state via the Google Drive
connector without manual pasting. Added 2026-07-24.

| Piece | Path |
|---|---|
| Sync script | `scripts/gdrive_sync.py` (`--dry-run` plans without creds) |
| One-time auth | `scripts/gdrive_auth.py` (mints the refresh token) |
| Cron wrapper | `scripts/run_gdrive_sync.sh` (uses the openclaw venv) |
| Credentials | `credentials/gdrive/{client_secret.json,token.json}` (gitignored) |
| Change manifest | `state/gdrive_sync_manifest.json` (path → {drive id, sha256}) |
| Log | `logs/gdrive_sync.log` |
| Schedule | **ACTIVE** — `*/30 * * * * run_gdrive_sync.sh` (live 2026-07-24) |
| Drive folder | "JCF HQ Vault" — `https://drive.google.com/drive/folders/1jTqwCeNWPPYatuz3dSgWZk4tGKn91jv9` (in **crocjay9@gmail.com**'s Drive, the connected account) |

- **Auth:** OAuth *user* credentials (not a service account — the account is a
  personal `@gmail.com`, and service accounts can't own files in consumer
  Drive). Least-privilege scope `drive.file`: the app only ever sees files it
  created. **Consent screen is in "Testing" mode → the refresh token expires
  ~7 days after issuance** (verification not worth it for a private tool). When
  it dies, `gdrive_sync.py` **Telegram-alerts the owner** (via `openclaw message
  send`, throttled once per outage) — just re-run `gdrive_auth.py` to reconnect.
  Google libs live in `venv/` (system Python is PEP-668 externally-managed).
- **Efficiency:** SHA-256 content hash vs the manifest — unchanged files are
  skipped, so idle 30-min runs make near-zero API calls.
- **Trigger choice — cron, not a post-commit hook:** decoupled from git (Vault
  edits land from either the VPS or the laptop; a hook only fires on the machine
  that commits and would need creds there), no commit latency, and self-healing
  (a failed run just retries next tick). See `Vault/infrastructure/gdrive-sync.md`.

### 4f. Discord broadcast (alongside Telegram)

Agents post their reports to Discord webhooks **in addition to** Telegram
(never replacing it). Added 2026-07-24.

- **Helper:** `scripts/discord_notify.py` — `notify(agent, text, channels=None)`.
  Posts with a per-agent username (emoji + name, matching the Telegram voice)
  and optional avatar. Chunks content to Discord's **2000-char** limit, retries
  once on HTTP 429. **No-ops silently when a channel's webhook env var is unset**,
  so it's safe to wire in before webhooks exist.
- **Webhooks** live in `.env` (gitignored), one per channel:
  `DISCORD_WEBHOOK_<CHANNEL>` — e.g. `DISCORD_WEBHOOK_LENS`,
  `DISCORD_WEBHOOK_STOCK_NEWS`, `DISCORD_WEBHOOK_BLADE_SIGNALS`,
  `DISCORD_WEBHOOK_JERRY_PAPER`, `DISCORD_WEBHOOK_ALERTS`,
  `DISCORD_WEBHOOK_AGENT_HUB`. Default per-agent routing is in `_ROUTES`.
- **Avatars** (optional): set `DISCORD_AVATAR_BASE` to a **public** base URL
  serving `<agent>.png` (portraits live at `hq-app/public/agents/*.png`, but
  the repo is private so GitHub-raw won't work — host them or leave unset for
  username-only). Jarvis maps to `strategist.png`.
- **Wiring:** each agent calls `discord_notify(agent, report)` right after its
  `_send_telegram(...)`. **Lens is wired first** (proven agent); the rest get
  wired after Lens's delivery is confirmed. To add an agent: import
  `from discord_notify import notify as discord_notify` and call it beside the
  Telegram send.

### 4g. Claude Code mobile access (Remote Control)

`/remote-control` (alias `/rc`) links a **local** Claude Code session to Jase's
phone/browser via `claude.ai/code`; code still executes on the VPS. Requires a
Pro/Max/Team plan (**Max ✓**), a **claude.ai `/login`** (not API-key auth), and
`ANTHROPIC_BASE_URL` = api.anthropic.com (unset ✓). Session ends if the terminal
closes or after a 10-min network outage — so run it inside **tmux** for
persistence.

**Persistent session (tmux 3.4 installed; `claude-main` created):**
```bash
tmux attach -t claude-main     # or: tmux new -s claude-main
claude                         # start Claude Code (once, accept trust dialog)
/remote-control                # inside the session → prints URL; SPACEBAR toggles QR
# detach (leave it running):  Ctrl+B  then  D
# reattach later over SSH:    tmux attach -t claude-main
```
**Phone pairing (one-time):** scan the QR (or open the URL) → opens in the
Claude app / `claude.ai/code`; the session shows a green dot when online.
`/mobile` inside Claude Code shows the app-download QR. After pairing, Jase can
reconnect from the app's **Code** tab **without SSH**. Docs:
https://code.claude.com/docs/en/remote-control

---

## 5. Cron Schedule (annotated)

All times UTC unless noted. Mon–Fri = weekdays only.

```cron
# ── Always-on heartbeat
*/2  * * * *     sync_dashboard_public.sh             # dashboard mirror, every 2 min
*/30 * * * *     sync_tradelocker.py                  # broker fills, every 30 min
*/5  * * * *     sync_agent_pnl.py                    # rolling P&L per agent, every 5 min

# ── Portfolio syncs — every 2 weeks (1st + 15th, 06:00 UTC)
0  6  1,15 * *   sync_robinhood.py
0  6  1,15 * *   sync_trustwallet.py
0  6  1,15 * *   sync_kraken.py
0  6  1,15 * *   plaid/sync_plaid_transactions.py

# ── Lens (macro briefing)
55 4  * * 1-5    run_lens_brain.sh                    # 04:55 — before all sessions

# ── Jarvis (regime briefing, formerly Strategist)
0  6  * * 1-5    strategist/run_research.sh           # pre-London brief
0  12 * * 1-5    strategist/run_research.sh           # pre-NY brief
0  8  * * 6      strategist/deep_backtest.py          # Saturday weekly deep backtest

# ── Session prep pings (Huncho voice + auto 4H chart reads)
40 23 * * 1-5    session_prep_ping.sh ASIA            # 10 min before ASIA
45 7  * * 1-5    session_prep_ping.sh LONDON          # 10 min before LONDON
15 13 * * 1-5    session_prep_ping.sh NY_OPEN         # 10 min before NY open (manual session)
45 17 * * 1-5    session_prep_ping.sh NY_PM           # 10 min before NY_PM

# ── Blade trading sessions (D3 sizing)
50 23 * * 1-5    timeout 7200 blade/bot/run_session.sh ASIA
55 7  * * 1-5    timeout 7200 blade/bot/run_session.sh LONDON
55 17 * * 1-5    timeout 7200 blade/bot/run_session.sh NY_PM

# ── Session-end unified reports
0  6  * * 1-5    session_end_notify.py ASIA
30 13 * * 1-5    session_end_notify.py LONDON
0  21 * * 1-5    session_end_notify.py NY_PM

# ── Sentinel (insider/market intel) — 3x daily weekdays
0  8  * * 1-5    sentinel/run_sentinel.sh
0  14 * * 1-5    sentinel/run_sentinel.sh
0  20 * * 1-5    sentinel/run_sentinel.sh

# ── Daily ops
0  7  * * *      daily_briefing.py                    # consolidated Telegram digest
0  8  * * *      scrape_bball_stats.py                # Jase's eurobasket stats (personal)
30 5,21 * * *    sync_market_data.py                  # 2x daily market data refresh
0  21 * * *      victoria/run_victoria.sh             # daily CFO report
0  23 * * *      daily_cost_tracker.sh                # API cost rollup

# ── Tao (Bittensor)
0  3,11,19 * * *      tao_data_collector.py           # 3x daily
0  6  * * *           tao_subnet_scorer.py
0  9,21 * * *         tao_dca_engine.py               # 2x daily DCA check
0  0,6,12,18 * * *    tao_profit_monitor.py           # every 6 hours
0  8  * * 6           tao_compounder.py               # Saturday weekly

# ── Weekly
0  10 * * 6      norman/run_norman.sh                 # Saturday 10:00 — Norman validation
0  12 * * 0      lucy/lucy_brain.py --research        # Sunday noon — skills/tools scout
0  7  * * 1      victoria/run_victoria_weekly.sh      # Monday — weekly tribunal
0  8  * * 6      enrichment_tracker.py                # Saturday — Crisp enrichment analysis

# ── Commented out (parked / replaced)
# 55 23 * * 1-5  crisp/bot/run_session.sh ASIAN       # Crisp parked
# 55 4  * * 1-5  lens/bot/run_lens.sh                 # replaced by lens_brain.py
```

---

## 6. Critical Rules

1. **Never edit `openclaw.json` with sed/Edit.** Use `openclaw config`
   commands. The file contains nested provider profiles with secrets and
   the openclaw CLI will refuse to start on a malformed file. Backups at
   `openclaw.json.bak.*` and `openclaw.json.last-good`.

2. **Every Anthropic-using run script needs the `.env` source block.**
   ```bash
   set -a
   source /root/.openclaw/.env
   set +a
   ```
   Without it: `TypeError: Could not resolve authentication method`.

3. **Portfolio syncs run 1st & 15th only** (`0 6 1,15 * *`). Robinhood,
   Trustwallet, Kraken, Plaid. Do not increase frequency — RH 429s and
   wallet rate limits are real.

4. **Skills live in `~/.claude/skills/`.** 67 installed as of this writing.
   Reference them by methodology (bake into agent prompts) rather than
   spawning sub-agents to call them — keeps latency and cost down.

5. **Secrets never go to GitHub.** `.gitignore` covers:
   - `.env`, `*.pem`, `**/auth-profiles.json`, `openclaw.json`
   - `**/credentials/`, `**/plaid_tokens*`, `kalshi_private*`
   - `dashboard/plaid_data.json`, `dashboard/hq_userdata.json`
   - `identity/device-auth.json`, `**/.aster-keys`, `**/*-keys` (added 2026-06-01)
   - All `logs/`, `*.log`, `*.bak`, `/tmp/`, `venv/`
   **Always run** `git diff --cached --name-only | grep -E "\.env|\.pem|auth-profiles|openclaw\.json|plaid_data|device-auth|aster"`
   before any `git push`.

6. **Blade / Edge / Jerry: Phase 1 observation only.** They SEE Lens bias,
   Jarvis regime, Norman verdict, and the H4 read. They DO NOT GATE on any
   of it. Don't add gating logic — wait for Norman to validate at the
   100-cluster checkpoint and then a separate explicit PR.

7. **Strategist's internal id is `strategist`, display name is JARVIS.**
   Code paths / JSON keys / file names use `strategist`. Telegram + user-
   facing text use `Jarvis`. The `AGENT_DISPLAY` alias map handles it.

8. **Risk rails are not advisory.** Blade max 1% per trade, 2% per cluster,
   -4% daily DD halt. Don't ship a change that breaches any of these
   without an explicit conversation about why.

---

## 7. Decision Log (brief — the "why")

| Decision | Date | Why |
|---|---|---|
| **Huncho documentation rule** | 2026-07-24 | Infra changes Huncho makes directly (e.g. `openclaw mcp add`) weren't landing in CLAUDE.md/Vault — a blind spot in the shared brain. Added a NON-NEGOTIABLE "Documenting Infrastructure Changes" rule to Huncho's SOUL: any authorized capability/config change must be logged (decision log + Vault/infrastructure note) before reporting complete. Huncho acknowledged. See `Vault/decisions/decision-log.md`. |
| **Alpaca + CoinCap MCP installed** | 2026-07-24 | Gateway-level MCP servers added by Huncho via `openclaw mcp add` (backfilled). Alpaca = 118 tools on the existing **paper** key (not live); CoinCap = 3 read-only crypto tools (Lucy-recommended). Full detail in `Vault/decisions/decision-log.md`. |
| **Oracle deleted** | 2026-06-01 | Sports betting bankroll ran -69% ROI. Resolver was firing quota-exhaustion errors hourly. Strategist's pre-trade scoring fed nobody (Blade v5 ignored it, Crisp was halted). Dead weight. Backed up to `/tmp/oracle_deleted_backup/`. |
| **Kalshi deleted** | 2026-06-01 | CSV logged order placement but not settlement — P&L was unknowable. API-key rotation and 429s were noisy. Settlement pipeline never finished. Backed up to `/tmp/kalshi_deleted_backup/`. |
| **Blade D3 redesign** | 2026-06-01 | Norman flagged Blade as FAIL. Root cause was 4× sizing under-count (used 3pt SL buffer as divisor instead of real stop distance) AND sub-1R TPs on positions 1 and 2 (0.26:1 and 0.44:1 against typical 11.4pt stop). MC backtest of D3: PF 0.92 → 1.54, max DD 25%, 0% ruin. |
| **Forge / Naomi / Advisor benched** | 2026-06-01 | Non-trading focus. Forge idle 1.5 mo, Naomi idle 1.5 mo, Advisor already replaced by Victoria. Code preserved on disk. |
| **Strategist → Jarvis (rename)** | 2026-06-01 | Jase's preference. Display alias only — internal id `strategist` unchanged for backward compat. |
| **Strategist engine trim** | 2026-06-01 | 1042 → 446 lines. Removed 0-100 convergence score, strategy-selection logic (orb/sweep_fade/breakout_expansion/...), FVG detection, liquidity-level detector — nothing downstream consumed them. Blade v5 explicitly ignored the score; Crisp was halted. |
| **Cross-agent context layer (Phase 1)** | 2026-06-01 | Build the wires, prove value with logged data, gate later. Avoids the trap of acting on assumed-true patterns. |
| **Centralized agent_strategies.json** | 2026-06-01 | Norman recommendations were unactionable when knobs were hardcoded — every tweak required a redeploy. Single file = single tunable surface. |
| **Skills methodology baked into prompts** | 2026-06-01 | Option A: reference methodology in system prompts vs Option B: port the Python. Faster, cheaper, no parallel code to maintain. |
| **OANDA practice token rotated** | 2026-06-02 | New token scoped to both sub-accounts 001 (Blade, Primary) and 002 (Edge, Scalper). Edge now able to place orders for the first time — previously blocked by 403 forbidden since the token only covered 001. `auth-profiles.json` remains gitignored; token value lives only on the VPS. |

---

## 8. Roadmap / Open Items

### Active work pending
- **Norman 100-cluster D3 validation** — Blade learning log fills naturally;
  when it crosses 100 closed clusters, replace `blade_learning_analyzer.py`
  stub with real bucketed analysis and run Norman on the buckets. Specifically
  validate the `pos3_trail_r_achieved` distribution (D3's thinnest assumption).
- **Phantom strategy build** — collaborative, data-driven. Held until enough
  futures-relevant context (or a specific edge thesis) exists.
- **Crisp meme coin pivot** — new SOUL.md required. Holding until Jase
  defines the new mandate.

### Deferred
- **Obsidian vault (second brain)** — in progress on Jase's local. Not part
  of this repo.
- **HQ React dashboard redesign** — ✅ done 2026-07-17. `hq-app/` rebuilt as a
  6-route glassmorphism command center (React 18 + TS + Vite + framer-motion/
  recharts) around the current agent roster. See
  `Vault/infrastructure/hq-dashboard.md` + decision log below.

### Conditional (gated on data)
- **Blade live deployment** — after D3 paper results pass Norman validation.
- **Edge live deployment** — currently $5K notional in `edge_portfolio.json`
  but executes on OANDA practice. Same gate: Norman PASS first.
- **Phase 2 gating in Blade/Edge/Jerry** — only after Norman validates a
  specific pattern from the learning logs as statistically real (≥30
  trades/bucket, MC p5 > 0). Then a separate PR per pattern.

### Known small issues
- `agents/blade/bot/blade_bot.py:76-78` — TODO: `PIP_VALUE` stores price
  increment per pip, not USD per unit per pip. CHF_JPY and DE30_EUR P&L
  slightly mis-stated in paper accounting. Fix before live trading.
- Tao knobs still in `.env` rather than `agent_strategies.json`. Migrate
  when convenient.
- `device-auth.json` + `.aster-keys` are in prior commit `a13e8fe` history.
  Untracked going forward but not scrubbed from history. Rotate tokens or
  run `git filter-repo` if/when the repo goes public.

---

## Appendix — Quick directory map

```
/root/.openclaw/
├── CLAUDE.md                          ← this file
├── README.md                          ← copy of this file (GitHub front page)
├── .gitignore                         ← secrets list
├── openclaw.json                      ← master config (NEVER sed-edit; gitignored)
├── .env                               ← secrets (gitignored)
├── agents/
│   ├── blade/    bot/blade_bot.py + blade_learning_analyzer.py (D3)
│   ├── crisp/    PARKED — meme coin pivot pending
│   ├── edge/     edge_main.py (SMA 8/21)
│   ├── huncho/   killzone_sync.py
│   ├── jerry/    jerry_main.py + jerry_context.py
│   ├── lens/     lens_brain.py
│   ├── lucy/     lucy_brain.py
│   ├── main/     skills/chart_analysis.py
│   ├── norman/   norman_brain.py
│   ├── phantom/  PARKED — strategy pending
│   ├── strategist/  (display: JARVIS) strategy_engine.py + run_research.sh
│   ├── tao/      tao_*.py
│   ├── victoria/ victoria_brain.py
│   └── (benched) forge/, naomi/, advisor/
├── scripts/
│   ├── agent_config.py                ← shared config loader
│   ├── h4_read.py                     ← automated 4H chart reads
│   ├── telegram_personalities.py      ← voice + emoji + display names
│   ├── session_prep_ping.sh           ← Huncho pre-session ping + H4 reads
│   ├── daily_briefing.py
│   ├── hq_storage_server.py           ← dashboard backend
│   ├── sync_*.py                      ← portfolio syncs (1st/15th)
│   └── sentinel/                      ← insider/market intel pipeline
├── dashboard/
│   ├── agent_strategies.json          ← central risk knobs
│   ├── watchlist.json                 ← Jase's tickers
│   ├── market_bias.json               ← Lens output
│   ├── strategy_recommendation.json   ← Jarvis output
│   ├── norman_report.json
│   ├── victoria_report.json / victoria_weekly.json
│   ├── blade_balance.json             ← Blade compounding balance
│   ├── blade_learning_log.json        ← Phase 1 dataset
│   ├── edge_learning_log.json
│   └── jerry_learning_log.json
└── hq-app/                            ← React dashboard
```

---

## Vault Maintenance (standing instruction)

A navigable knowledge vault lives at `Vault/` (start at
[`Vault/00-START-HERE.md`](Vault/00-START-HERE.md)). It expands this file
into ~28 linked notes — one per agent, one per strategy, infrastructure,
decisions, and dated session logs.

**Standing rule for every Claude Code / Codex session:**

If your work makes a **significant change** to an agent, a strategy, an
infrastructure piece, or introduces a new design decision, you MUST do
both of these in the same task / PR — not as a follow-up:

1. **Update the matching vault note** at `Vault/agents/<name>.md`,
   `Vault/strategies/<name>.md`, or `Vault/infrastructure/<name>.md`. The
   note should remain a clean standalone explainer for the current state.
   Add new `[[wiki-links]]` to neighbors where it helps navigation.

2. **Append a dated entry** to the matching session note at
   `Vault/sessions/YYYY-MM-DD.md`. Create the file if it doesn't exist
   for today. Note what changed, why, and which commit it landed in.

3. **Update [`Vault/decisions/decision-log.md`](Vault/decisions/decision-log.md)**
   if the change reflects a *decision* (a chosen path with a why) — not
   for routine implementation work.

**What counts as a "significant change":**
- New agent, new strategy, new infrastructure piece
- Removal / benching / parking of an agent
- A rule, rail, threshold, or tunable knob that affects trading behavior
- A new cross-agent wire, integration, or data source
- A change to the comms / observation layer (Phase 1 → 2 → 3 transitions)
- A model routing change or new skill methodology baked into a prompt
- A new security / secret-hygiene rule

**What doesn't count** (no vault update needed):
- Pure refactors with no behavior change
- Typo or formatting fixes
- Log-only output tweaks

If you change the code but not the vault, future Claude sessions will read
a stale map. The vault drifting from the code is technical debt — pay it
down in the same task.

When in doubt, update the vault. It's a living second brain — keep it
current as a byproduct of the work.

---

*If anything in this file disagrees with the code, the code wins — and this
file is wrong. Fix it.*
