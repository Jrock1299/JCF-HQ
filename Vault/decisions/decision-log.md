# Decision Log

Chronological. The *why* of every major call. Newest first.

---

## Context7 MCP added to Claude Code · 2026-07-24
**Decision:** `claude mcp add context7 -- npx -y @upstash/context7-mcp@latest`
(in `/root/.claude.json`, project scope). Authorized by Jase.
**Why:** gives future Claude Code sessions current library documentation when
building JCF HQ features. **Claude Code tooling only** — not wired to any trading
agent (Lens/Chad/etc.), no trading impact. Verified `✔ Connected` via
`claude mcp list`. *(This is Claude Code's MCP config, separate from the OpenClaw
gateway `mcp.servers` that hold alpaca/coincap.)*

---

## Alpaca + CoinCap MCP servers installed · 2026-07-24 *(backfilled)*
**Decision:** Two OpenClaw-managed MCP servers were added at the gateway level
(`mcp.servers` in openclaw.json), installed by Huncho/the main-agent context via
`openclaw mcp add` (per `logs/config-audit.jsonl`). Authorized by Jase.
*This entry backfills the documentation gap — the installs happened 2026-07-24
but weren't recorded until the [[../../CLAUDE.md]]/Vault check flagged it; see the
new "Documenting Infrastructure Changes" rule in Huncho's [[../../workspace/SOUL.md|SOUL]].*

- **`alpaca`** (`npx @alpaca-open-api/mcp`) — added **13:01:30 UTC**, key set
  **13:05:53 UTC**. **118 tools** (orders, positions, account, market data).
  Uses the **existing PAPER key** (`PKKYEZ…`, `ALPACA_ENV=paper`, same as Jerry's
  `.env`) — **not a new key, not live, no real-money scope.** Available to
  gateway-agent turns (not the standalone Python bots, which use their own clients).
- **`coincap`** (`npx coincap-mcp`) — added **13:02:45 UTC**. **3 tools**,
  read-only public crypto data, no key. Traces to Lucy's 2026-07-18 research
  recommendation ("CoinCap MCP, priority HIGH").
- **Status:** both functional (`openclaw mcp probe` OK). Hygiene note: the Alpaca
  key/secret are stored as literal plaintext in openclaw.json (gitignored). The
  "270+ tools / instant execution / shared across whole roster" framing in the
  original Huncho report was inaccurate — real surface is 118+3 tools, paper-only.

**Why (rule that follows from this):** infra changes Huncho makes directly must
land in this log going forward — see [[../../workspace/SOUL.md|SOUL §Documenting
Infrastructure Changes]].

---

## Google Drive Vault mirror · 2026-07-24
**Decision:** Mirror `CLAUDE.md` + `Vault/**/*.md` to a Google Drive folder via a
cron-driven Python sync, using **OAuth user credentials** (not a service account).
See [[../infrastructure/gdrive-sync.md]].

**Why OAuth over the originally-requested service account:** the Google account is
a personal `@gmail.com`. Service accounts have no consumer-Drive storage quota, so
SA-owned uploads fail (`storageQuotaExceeded`) even into a shared folder. OAuth
user creds make the VPS act as the account owner — files owned by the user, in the
user's Drive, readable by the connector. Scope `drive.file` (least privilege).

**Why cron over a post-commit hook:** decoupled from git (Vault edits come from
the VPS *and* the laptop; a hook only fires where the commit happens and would
need creds there), no commit latency, self-healing on failure. Hash-based skip
keeps idle 30-min runs near-free.

**Gotcha captured:** refresh tokens are durable only if the OAuth consent screen
is published to **"In production"** (Testing status expires them after 7 days).

**Status:** scripts built + verified (compile, dry-run, change-detection). Cron
added HELD. Real upload pending Jase's one-time Cloud Console + consent step.

---

## Prune dead gpt-5.3-codex from openclaw.json · 2026-07-24
**Decision:** Remove all `openai/gpt-5.3-codex` references from config (agents.list
crisp/blade/oracle overrides, the duplicate fallback, and the allow-list entry)
via `openclaw config patch`/`unset`. gpt-5.3-codex is retired server-side and
errored on every default-routing run. Config validates; VPS-only (openclaw.json
gitignored).

---

## Codex model routing → GPT-5.6 Terra · 2026-07-24
**Decision:** Move the Codex-routed agents from `openai/gpt-5.5` to
`openai/gpt-5.6-terra` (balanced tier) and rewrite the SOUL.md fallback chain
to what's actually live. Applies to [[../agents/victoria]], [[../agents/norman]],
[[../agents/lucy]] (PRIMARY), and [[../agents/jarvis]] (`infer` primary).

**Why:** GPT-5.6 rolled out 2026-07-09; 5.4 retired 07-23. Terra is the current
balanced everyday tier and cheaper than the Sol flagship. Reasoning/reporting
agents don't need Sol.

**Key findings (verified empirically, not assumed):**
- **Sol is unavailable on this account's Codex OAuth backend** — `openai/gpt-5.6-sol`
  returns HTTP 400 from `chatgpt.com/backend-api/codex` via *both* `openclaw agent`
  and `infer model run`. Plain `openai/gpt-5.6` is "Unknown model." So the user's
  "Sol for Jarvis" preference can't be honored; **Terra is the top working tier.**
  Terra ✅ and Luna ✅ both work.
- **A model must be whitelisted in `agents.defaults.models` to be usable as an
  `openclaw agent --model` override.** Added `openai/gpt-5.6-terra` + `-luna`
  (plain entries, like gpt-5.5) via `openclaw config patch`; removed the dead
  `-sol` entry. `infer model run` is NOT gated by this list (Jarvis's path).
- **Jerry NOT migrated.** The task listed it as "Codex-routed," but Jerry is on
  the **Anthropic SDK** (`claude-sonnet-4-6`) and last round was explicitly
  ring-fenced. It needs the same `_run_codex` refactor Victoria/Norman got — a
  migration, not a string swap. Held for a separate decision.
- **Blade & Edge have no LLM at runtime** (pure algorithmic bots) — "update to
  5.6" is a no-op for them. Stale `openai/gpt-5.3-codex` entries under
  `agents.list` (crisp/blade/oracle) in openclaw.json are dead and prunable.

**Tested:** Victoria daily + Norman weekly on Terra — voice intact, schema valid,
$0 cost. Cron still HELD.

**See:** [[../sessions/2026-07-24]].

---

## Victoria + Norman → Codex · 2026-07-24
**Decision:** Migrate [[../agents/victoria]] and [[../agents/norman]] off the
Anthropic SDK (`claude-sonnet-4-6`) onto the Codex runtime (`openai/gpt-5.5`)
via Lucy's `openclaw agent` subprocess pattern (`_run_codex`). [[../agents/lens]]
stays on Anthropic (it depends on the server-side `web_search` tool, which the
Codex path can't provide).

**Why:** Both agents are pure reasoning + structured-JSON with **no tool
dependencies**, so they port cleanly to the free Codex quota and stop drawing
on the paid `ANTHROPIC_API_KEY` balance. Investigated/approved 2026-07-21;
implemented 07-24.

**Key calls:**
- **Model override string is `openai/gpt-5.5`, not `openai/gpt-5.5-codex`.**
  Empirically confirmed: the `-codex` suffixed ids are agent-runtime-bound and
  the gateway rejects them as `--model` overrides ("Unknown model … served by
  an agent runtime"). Plain `openai/gpt-5.5` resolves and routes through Codex.
- **Persona prepended into the user message** — the gateway agent has no
  `system` slot. Voice verified intact on test runs (Victoria's gothic-queen
  and Norman's cold register both survived).
- **Large payloads via `--message-file`**, not `-m`, to dodge the ~128KB
  single CLI-arg limit (Victoria stuffs a lot of data).
- **Cost logged as $0** (Codex free tier); `_save_cost(0, 0)` keeps the log
  cadence without fabricating Anthropic spend.
- **NOT un-held in cron yet** — Jase reviews test output before go-live.

**See:** [[../sessions/2026-07-24]].

---

## HQ Dashboard v3 rebuild · 2026-07-17
**Decision:** Rebuild `hq-app/` from scratch as a 6-route glassmorphism
command center (React 18 + TypeScript + Vite + framer-motion/recharts/
react-router). Clean-delete the old JSX pages; keep all data files. See
[[../infrastructure/hq-dashboard]] and [[../sessions/2026-07-17]].

**Why:** The roadmap's deferred "HQ React dashboard redesign" — the old UI
predated the Oracle/Kalshi removal and current agent roster. Goal: one app
that replaces checking ~10 tabs each morning.

**Key calls:**
- **Same-origin relative fetches**, not hardcoded `:8900`. Most endpoints are
  static `dashboard/*.json` served by `serve_hq` (:8899); only `/hq/*` proxies
  to Flask (:8900). App degrades gracefully if `:8900` is down.
- **Prefer live data, spec numbers only as fallback** (e.g. net worth override
  → else $958k).
- **Blade per-trade R computed client-side** — learning log has no P&L field.
- **Agent Hub runs off crafted in-character seed threads**, not live `/hq/hub`
  status logs (which would clutter the voice).
- `openclaw-hq.service` **enabled** (was disabled) so serve_hq survives reboot.

---

## Vault build · 2026-06-01
Created `Vault/` second-brain. Single source of truth stays the repo-root
[[../00-START-HERE|CLAUDE.md]]; vault expands it for navigation. Standing
maintenance rule added to [[../00-START-HERE|CLAUDE.md]]: any session that
changes an agent / strategy / infra must update the matching vault note
AND drop a dated entry in the relevant `sessions/` note. See
[[../sessions/2026-06-01]].

---

## Skills baked into prompts · 2026-06-01
**Decision:** Option A — extract methodology from `~/.claude/skills/*/SKILL.md`
and bake into agent system prompts. Reject Option B (port the Python).

**Why:** Faster, cheaper, no parallel code to maintain, no latency hit at
trade time. Methodology survives skill-script changes; agents stay stable.

Baked methodology:
- [[../agents/jarvis]] — `macro-regime-detector`, `market-breadth-analyzer`, `sector-analyst`
- [[../agents/norman]] — `backtest-expert`, `position-sizer`
- [[../agents/lens]] — `market-news-analyst`, `market-environment-analysis`
- chart_analysis.py — `technical-analyst`

See [[../infrastructure/model-routing#skills-integration-approach-option-a]].

---

## H4 chart reads automated · 2026-06-01
**Decision:** Build `scripts/h4_read.py` — text-based H4 technical read
from OANDA candles + Codex narrative. Cached 30 min per instrument.
Delivered via Telegram session prep ping (Huncho) AND stamped on every
Blade / Edge trade. **Observation only. No gating.**

**Why:** Previous design relied on Jase sending a chart image manually.
Now every session and every trade has an automated 4H read riding along
without effort. Adds context to the learning logs for the Phase 2 review.

See [[../infrastructure/system-architecture#h4-read-pipeline]].

---

## Strategist renamed to JARVIS · 2026-06-01
**Decision:** Display alias only — internal id `strategist` unchanged.

**Why:** Jase's preference. Rename the user-facing name; don't break
backward compat of code paths / JSON keys / cron entries / log queries.
Added `AGENT_DISPLAY` map in `telegram_personalities.py` — surgical change,
single line wraps the display.

Voice: calm, precise right-hand-man. Composed. Subtly confident. Signs
`— Jarvis`. Full identity in `agents/strategist/CLAUDE.md`.

See [[../agents/jarvis]] · [[../infrastructure/personalities]].

---

## Jarvis (Strategist) engine trim · 2026-06-01
**Decision:** Trim `strategy_engine.py` from 1042 → 446 lines. Remove the
0-100 convergence score, strategy-selection logic, FVG detection,
liquidity-level detector, all TRADE/SKIP recommendation. Keep regime
detection, Lens bias, Monte Carlo, narrative.

**Why:** No trading agent consumed the deleted outputs. Blade v5
explicitly ignored the score; Crisp was parked. The strategy-variant
selector picked between 5 strategies but Blade only ever ran pure ORB.
Dead code. Edge-map helpers retained because `deep_backtest.py` (Saturday
weekly) uses them.

See [[../agents/jarvis#what-was-removed-2026-06-01]] ·
[[../strategies/orb-strategy#variants-we-explored-and-rejected]].

---

## Centralized agent_strategies.json · 2026-06-01
**Decision:** Move per-agent risk knobs into a single
`dashboard/agent_strategies.json`. Shared loader `scripts/agent_config.py`.
Non-breaking — defaults preserved as fallbacks.

**Why:** Norman's "tighten X" recommendations were unactionable when every
threshold required a code edit + redeploy. One file = one tunable surface =
seconds to ship a change.

See [[../infrastructure/config]].

---

## Cross-agent comms layer (Phase 1) · 2026-06-01
**Decision:** Wire Blade / Edge / Jerry to SEE Lens bias + Jarvis regime +
Norman verdict + H4 read. Stamp on every trade record. Write to dedicated
learning logs. **No gating yet.**

**Why:** Build the wires; prove the value with logged data; gate later.
Avoids the trap of acting on assumed-true patterns before they're
statistically real. Phase 2 (Norman-validated buckets) and Phase 3
(explicit per-pattern PR) follow.

See [[../infrastructure/system-architecture#cross-agent-comms-phase-1-3]].

---

## Blade D3 redesign · 2026-06-01
**Decision:** Replace Blade's broken sizing + TP structure with D3:
- Real stop distance (was: 3pt buffer used as divisor — 4× understatement)
- Weighted sizing 20/30/50 across pos1/2/3
- TPs as R-multiples: 1R / 2R / trailing (trail 1R below high-water)
- 2% per cluster (≤1% per single trade)
- -4% daily DD circuit breaker
- Compounding off current balance via `blade_balance.json`

**Why:** Norman flagged Blade as FAIL — 53% WR but PF=1.114, max DD=72.9%.
Root cause analysis on the 287-trade backup showed pos1 R:R was 0.26:1 and
pos2 was 0.44:1 against the typical 11.4pt stop. Two of three positions
were sub-1R — losing reward-to-risk by design. Plus the sizing bug. MC
backtest of D3: PF 0.92 → 1.54, max DD 25%, 0% ruin.

See [[../strategies/blade-d3-sizing]].

---

## Forge / Naomi / Advisor benched · 2026-06-01
**Decision:** Three agents benched — cron entries removed, code preserved.

- **Forge** (HTML/Excel builder) — idle 1.5 mo, non-trading
- **Naomi** (Etsy copywriter) — idle 1.5 mo, tied to Forge
- **Advisor** (session prep) — replaced by Victoria 2026-04-15; cron lines
  were commented; fully deleted 2026-06-01

**Why:** Non-trading focus. JCF HQ is consolidating around the trading
system. Revivable on demand.

See [[../agents/_benched/forge]] · [[../agents/_benched/naomi]] ·
[[../agents/_benched/advisor]].

---

## Portfolio syncs slowed to 1st + 15th · 2026-06-01
**Decision:** Robinhood / Trustwallet / Kraken / Plaid syncs from daily/
multiple-times-daily to `0 6 1,15 * *` (bi-monthly).

**Why:** Robinhood was 429ing daily; the data doesn't move fast enough to
justify the spam. Plaid transactions rarely material between syncs.

See [[../infrastructure/cron-schedule#portfolio-syncs-1st-15th-of-month-only]].

---

## Kalshi deleted · 2026-06-01
**Decision:** Full removal of Kalshi bot. systemd service stopped + disabled;
`/root/kalshi-bot/` deleted; all references stripped from
`victoria_brain.py`, `norman_brain.py`, `hq_storage_server.py`,
`daily_briefing.py`, `enrichment_tracker.py`. Backups in
`/tmp/kalshi_deleted_backup/`.

**Why:** CSV logged order placement but not settlement — P&L was
unknowable. API-key rotation and 429s were noisy. Settlement pipeline never
finished. Dead weight.

---

## Oracle deleted · 2026-06-01
**Decision:** Full removal of Oracle agent + sports betting pipeline +
React dashboard tab. Cron entries removed; code/data deleted; Victoria /
Norman / hq_storage_server / daily_briefing stripped of Oracle refs.
Backups in `/tmp/oracle_deleted_backup/`.

**Why:** Sports betting bankroll ran -69% ROI. Resolver was firing
quota-exhaustion alerts hourly. Strategist's pre-trade scoring fed nobody
(Blade v5 ignored it, Crisp was parked). Dead weight.

---

## Telegram formatting cleanup · 2026-06-01
**Decision:** Remove `━━━━━━━━━━━━━━━━━━━━━━` separator bars from every
Telegram message. Replace `reported to H` footer with `— via H`.

**Why:** Cleaner conversational format. The bars were ASCII noise.

See [[../infrastructure/personalities]].

---

## Norman .env auth fix · 2026-06-01
**Decision:** Add `set -a / source /root/.openclaw/.env / set +a` block to
`agents/norman/run_norman.sh`.

**Why:** Norman was throwing `TypeError: Could not resolve authentication
method` for ~24 hours. Same fix as Lens and Victoria had earlier — cron's
minimal env doesn't inherit Anthropic keys.

Standing rule: every Anthropic-using agent run script needs this block.
See [[../infrastructure/model-routing#env-auth-fix]].

---

## chart_analysis billing fallback · 2026-06-01
**Decision:** Add model fallback list to `chart_analysis.py`:
`codex/gpt-5.4` → `codex/gpt-5.5`. Fix JSON output parsing
(`outputs[0].text` shape).

**Why:** Default image model `moonshot/kimi-k2.5` is **suspended for
billing**. Chart reads were silently failing with "Chart analysis failed
(exit unknown)". Now reads fall through to working models.

See [[../agents/huncho]].

---

## sync_robinhood silent backoff · 2026-06-01
**Decision:** Add exponential backoff + silent exit-0 to
`sync_robinhood.py`. Strip all Telegram error notifications.

**Why:** Robinhood 429s were spamming Telegram daily. Sync isn't critical
for trading — silent retry, silent failure.

---

## HQ Round 2 — Blade wiped + gold accent kept · 2026-07-17
**Decision:** In the HQ dashboard Round 2 pass, (1) **reset Blade to a clean
slate** — `blade_balance.json` balance → 0 and `blade_learning_log.json`
records → `[]` — and drive the Trading page's Blade stats from an editable
`blade_manual.json`; (2) **keep the gold accent** rather than the
steel/slate an earlier UI question had selected.

**Why:** (1) Jase asked for a fresh start he sets himself via the new in-UI
edit mode; the old paper history + D3 cluster table were cleared with it.
Note this discards the paper trade history that fed Norman's 100-cluster D3
validation checkpoint — that counter restarts from zero. (2) The Round 2 spec
(newer, more specific) repeatedly relies on gold (Huncho glow, group-chat
accent, agent-modal ring), so gold wins over the earlier answer. Both flagged
to Jase in the final report.

**See:** [[../infrastructure/hq-dashboard]] · [[../sessions/2026-07-17]]

---

## Earlier history
For decisions made before 2026-06-01, see git log on the repo and the
prior `CLAUDE.md` history. Not all earlier decisions are documented here —
the vault was built 2026-06-01.

## Related
- [[../sessions/2026-06-01]] — the session where most of these happened
- [[../00-START-HERE]]
