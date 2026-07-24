# Decision Log

Chronological. The *why* of every major call. Newest first.

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
