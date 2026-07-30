# Decision Log

Chronological. The *why* of every major call. Newest first.

---

## Debug-output filtering belongs at the DESTINATION, not in each parser · 2026-07-30
**Decision:** the guarantee that machine debug output never reaches Telegram is
enforced in `telegram_personalities.wrap_message()` via a new
`scripts/output_sanitizer.py` — not by fixing the parser that leaked.

**Why:** the proximate bug was one header-strip loop in `run_lens_regime.sh`
that `break`d on the first unrecognised line, so OpenRouter's
`[provider-transport-fetch]` lines (which arrive *before* the metadata block)
stopped the strip dead and the entire stdout became "the narrative". That
parser is fixed too — but ~20 scripts shell out to a model CLI, the same defect
can grow in any of them, and the failure mode is silent: nothing errors, Jase
just gets a garbage message. A destination-layer guard covers every current and
future sender for free. Jase's brief asked for exactly this framing: "that's a
logging-destination bug, filter it at the notification layer regardless of what
else goes wrong."

**Conservative by construction:** a false positive silently deletes a line of a
real report, which is worse than the leak it prevents. Every rule requires
either a known machine-log shape or ≥4 `key=value` tokens on one line. Prose
never matches. A body that is *entirely* noise becomes an explicit "no usable
output" notice — never an empty bubble, never a dump (Rule #9).

---

## One daily-drawdown rail per BOOK, keyed on account id · 2026-07-30
**Decision:** the turtle executor's DD state and balance files are keyed on the
**OANDA account id**, not the UTC date alone and not the agent name.

**Why:** Blade and Edge run the same executor on the same `*/15` cron minute
against different practice books ($2,000 and $5,000). With state keyed only by
date, whichever ticked first wrote its own balance as `day_start_balance` and
the other read `(2000-5000)/5000 = -60%` against that foreign anchor, tripping
the -4% rail. The halt is a day-scoped latch, so one crossed wire stopped
**both** agents for the rest of every UTC day. Result: **203 decisions, 0
orders** across two days, 83% of them `DAILY_DD_HALTED`. Blade and Edge were
reported as "not trading"; the cause was this, not an absence of setups.

Account id is the right key rather than agent name because it encodes the
correct invariant: two agents sharing one account *should* share a rail (it is
the same money); two agents on separate accounts must not. The rail can no
longer be anchored to a balance that isn't its own.

**Note for the record:** the 2026-07-28 activation entry below lists
`/tmp/live_turtle_dd_YYYYMMDD.json per-UTC-day` among the rails "verified in
cron context". It was verified — for one agent. The defect only appears when a
second agent shares the minute, which is precisely what the same commit
enabled. Verifying a rail on a single executor does not verify it under
concurrency.

---

## Net worth is computed in code; the model may only quote it · 2026-07-30
**Decision:** `victoria_brain.compute_net_worth()` sums the real-money feeds in
Python; the model is handed the total to quote, and the value is **overwritten
in the result after the model returns**.

**Why:** `net_worth` was a field in the JSON output *template* — there was no
computation anywhere, so the figure drifted with whichever model answered:
$36,578 (correct), $38,578 (+$2,000, invented), $41,578 (+$5,000 — **Edge's
paper balance counted as net worth**). Arithmetic is not a job for a language
model, and net worth in particular must be reproducible: same inputs, same
number, every run.

The override is code-side and not merely a prompt instruction, per Critical
Rule #10 — a prompt instruction is not a gate. This is the same pattern already
used for API costs. Paper books are excluded by construction and *listed*, and
a feed that fails to load is named in `missing` so a partial total cannot pass
as a complete one (Rule #9).

---

## Blade + Edge live-paper crons ACTIVATED, first-fire monitor armed · 2026-07-28
**Decision:** `*/15 7-9,12-14 * * 1-5` cron for both Blade + Edge live
turtle executors on their respective OANDA practice accounts. Every 15 min
during London + NY killzones on weekdays. `*/5 7-9,12-14 * * 1-5` for the
first-fire Telegram monitor (fires once per agent on the first real
`SIGNAL_FIRED`, no-op after).

**Why:** two watched dry-runs at 14:20 and 14:43 UTC confirmed the exec
loop end-to-end — library read (`status=ok validated=3`), killzone check,
idempotency via `openTrades` + `clientExtensions.id` filter, balance rail,
detection on `close[1]`, fill-relative SL (`stopLossOnFill.distance`) +
post-fill TP via `TradeCRCDO` preserving the exact validated R:R. Rails
verified in cron context: 0.75% risk sizing, $100 balance floor, -4%
daily-DD halt via `/tmp/live_turtle_dd_YYYYMMDD.json` per-UTC-day.

**Not shipped:** anything trading live capital. OANDA practice accounts
only (Blade `-001` @ $2k, Edge `-002` @ $5k). Old Blade ORB `#HOLD` lines
untouched — the new executor is the deploy path, ORB stays parked.

**Links:** commits `1e569be`, `ab009e9`, `649c3ce` · [[../sessions/2026-07-28]]

---

## Futures (ES/NQ/GC): edge visible, same-basis validation deferred · 2026-07-28
**Decision:** No Pine indicator ships for ES/NQ/GC. Sweep-fade tested
against yfinance futures data — same gate as OANDA turtle_soup, same 100-
trade floor, same annualised-Sharpe basis, same fixed-size MC ruin.

**Results, honestly:**
- **M15 (validated basis):** ES/NQ/GC all **MARGINAL**. PF 1.22-1.28
  under the 1.5 PASS floor. Sh_ann 2.4-3.1, MaxDD <10%, ruin 0 — edge
  is visible. 60d/71d sample is too short to clear PF 1.5 confidently
  (OANDA turtle_soup needed 8yr / ~190k bars to hit PF 1.5+).
- **H1 (timeframe-shifted, 2yr):** ES/NQ/GC all **PASS** cleanly
  (PF 1.64-1.71, Sh_ann 3.37-3.65). Strong evidence the mechanism
  transfers, but wrong basis — the strategy was validated on M15.

**Why no Pine:** the deploy brief was explicit: "do NOT generate an
indicator for an instrument that failed validation." MARGINAL is not PASS
at the strategy's validated timeframe; the H1 PASS is at wrong timeframe.
A signal indicator for an unvalidated edge in front of Jase's live eval is
worse than no indicator.

**Path forward:** M15 futures history beyond 60d needs a paid feed
(Databento ~$100/mo, Polygon.io, or Rithmic once the Lucid API integration
scoped in `Vault/infrastructure/lucid-rithmic.md` is built). Until then
the futures edge remains "likely real, not confirmed at same basis."

**Links:** commits `676dd27`, `8d437a0` · `dashboard/futures_validation.json`

---

## Turtle Soup deployable, and it's MEAN REVERSION not ICT · 2026-07-28
**Decision:** `turtle_soup` on SPX500 / DE30 / XAU is promoted to
`dashboard/strategy_library.json` as `deployable=true`, labelled
**MEAN REVERSION (post-sweep fade)** — not ICT structure. CHF/JPY held out
(MARGINAL: PF 1.451 < 1.5 floor).

**Why deployable:**
- Walk-forward: **7/7 out-of-sample windows** across all four instruments
  meet PF ≥ 1.2 AND Sharpe_ann ≥ 0.5. OOS numbers as strong as or stronger
  than IS on most windows. No regime dependence, no fitting artefact.
- Corrected ruin (MC on `r_multiple × $75`, not compounded pnl) drops from
  68-74 % to 0.00 % on the three PASSing instruments — that was the
  compounding artefact the previous session flagged, now fixed.
- Parameter sensitivity is robust on DE30 / XAU / CHF/JPY across every knob
  variant; on SPX the *default* parameters PASS cleanly (PF 1.58) but one
  variant collapses to PF 0.58 — flagged as a real fragility, not fatal
  at defaults.

**Why MEAN REVERSION, not ICT:**
The mean-reversion baseline (strips H4 bias + London/NY killzones, fades
the sweep 24/7) **out-performs turtle_soup on 3 of 4 instruments** —
higher PF, higher Sharpe, double the trade count, double the expectancy
per trade. The ICT-inspired filters are filtering out winners, not adding
edge. Only CHF/JPY genuinely benefits from the filters (Sharpe 2.55 vs
1.24 baseline) and CHF/JPY does not PASS. Every library entry carries a
`mechanism_label` reading this plainly, so nobody deploying the strategy
downstream thinks they are running ICT structure.

**Not the same as promoting the plain baseline.** The baseline is a
separate strategy that has not been through the full gate + walk-forward
process. Documented in the session note as future work, not slipped into
the library.

**No other criterion moved.** Every gate threshold — 100-trade floor,
PF ≥ 1.5 for PASS, MaxDD < 25 %, multi-regime, ruin ≤ 10 %, annualised
Sharpe — held exactly as it was 2026-07-27. Only the ruin *input*
changed (compounded → fixed-size), which is a correctness fix on the
same math principle as the drawdown-denominator fix on 2026-07-25.

**Not deployed live.** Blade / Edge / Jerry / Chad cron untouched. The
library entry is the record; live deployment is a separate explicit call.

**Links:** [[../sessions/2026-07-28]] · [[../strategies/orb-strategy]] ·
`dashboard/ict_research.json` · `dashboard/strategy_library.json` ·
`dashboard/ict_turtle_validation.json`

---

## Deployment gate: annualised Sharpe, not per-trade · 2026-07-27
**Decision:** The strategy-deployment gate reads **annualised Sharpe**, not
per-trade Sharpe. Threshold and every other criterion (trade floor, PF, MaxDD,
multi-regime, ruin ≤ 10%) unchanged.

**Why:** Per-trade Sharpe demands a mean P&L half a standard deviation *per
trade* — a bar essentially no strategy meets and one that structurally
penalises high-frequency systems. It's not what the industry gates deployments
on. Turtle_soup illustrates the mismatch: per-trade 0.11-0.14 (fails), but
annualised 2.4-2.8 across 3,232-3,678 trades over ~8 years on four
instruments. The prior 2026-07-27 ICT/ICC session flagged the frequency bias
as a finding and refused to change the gate to a threshold seen after the
results — that was correct. The change was Jase's rule, made *knowing* what
turtle_soup produces, on the methodology and not the number. That is the
distinction between a principled recalibration and a fitted one.

**Also confirmed:** no other criterion loosened, so a strategy that fails PF,
MaxDD, ruin, sample size or multi-regime still fails the gate under the new
Sharpe basis. The 28-strategy regrade produced **0 PASS**, one MARGINAL
uptier (ifvg/DE30 from FAIL). Turtle_soup PASSED the annualised Sharpe check
on all four instruments but still FAILs on ruin (68-74%) — that is the
compounding artifact previously flagged as "reported but not applied":
Monte Carlo bootstraps compounded P&L against a fixed $10k start, so
million-dollar swings from a $10M peak equity are resampled against a $10k
account. Applying `fixed_size_pnl` to MC ruin is a separate methodology
call and was not made in this change.

**Also confirmed:** deep-validation infrastructure for turtle_soup added
(walk-forward, parameter sensitivity, mean-reversion baseline vs.
sweep-fade-no-ICT-filters) but not yet *run* — requires the OANDA candle
cache on the VPS. Nothing promoted to the shared strategy library.

**Result:** `scripts/risk_validation.py::calculate_stats` now emits
`sharpe_annualised` and `annualisation_factor`. `agents/lens/ict_research.py::_verdict`
grades on annualised. `scripts/regrade_ict_research.py` regraded the existing
28-row output in place without re-running the backtest — a pure recompute
that would drift from a re-run only if the trade set itself changed.

**Links:** [[../infrastructure/lucid-rithmic|Lucid/Rithmic scoping]] ·
[[../sessions/2026-07-27]]

---

## Jerry's P&L: record the broker's fill, never a fabricated zero · 2026-07-27
**Decision:** Source both entry and exit prices from Alpaca's own fill record,
and write `pnl=None` + `pnl_status=UNVERIFIED_*` whenever a fill can't be
established — never `0.0`.

**Why:** The reported bug was "all 90 closed trades record `pnl: 0.0`". It was
actually three defects stacked. The close path computed P&L only inside
`if symbol not in positions:`, checked microseconds after submitting a market
close order — Alpaca still lists the position until it fills, so it never ran.
Bracket SL/TP orders fill server-side and never called the close path at all.
And entry price was the pre-trade *snapshot* rather than the fill, wrong on 119
of 126 records and understating cost basis ~$5.1k — meaning even a correct
close computation would have produced wrong numbers. Fixing only the reported
symptom would have produced confident, wrong P&L, which is worse than the
obvious zeros: a visibly broken feed gets refused by the validator, a subtly
wrong one gets graded.

The `None`-not-`0.0` choice is the same principle as the 2026-07-25 NO_DATA
call, moved upstream. An unverified close counted as a $0 trade is a phantom
breakeven — it drags win rate, expectancy and Sharpe toward zero while looking
like real data. Rule #9 belongs at the write side, not only at the grading side.

**Also settled:** options are ×100 (per-share premium × 100 shares/contract),
verified against Alpaca's `cost_basis` and against implied starting equity,
which resolves to the documented $100k start only with the multiplier applied.

**Result:** History backfilled from the FILL activity feed — entries corrected
exactly by order id, exits matched lot-level FIFO, reconciling to broker cash
flows within **$0.04**. Victoria grades Jerry for the first time: FAIL, 116
trades, WR 35.3%, PF 0.972, net -$599.29. A real verdict on real data.

**Links:** [[../agents/jerry]] · [[../agents/victoria]] · [[../sessions/2026-07-27]]

---

## Consolidation cron lines approved and activated · 2026-07-27
**Decision:** Activated the four `#HOLD PENDING-APPROVAL` lines from the
2026-07-25 consolidation at Jase's sign-off — 2× Lens regime brief, Lens
validates Blade+Edge, Victoria validates Jerry+Chad.

**Why:** They were built and manually tested on 07-25 but deliberately left
unscheduled pending review, so that nothing started running on a schedule
without an explicit decision. Scripts were re-checked (shell syntax + Python
targets present) and the crontab backed up before the edit. Active non-comment
lines 18 → 22. Lucy's scouting desk stays default OFF — unchanged by this.

**Links:** [[../sessions/2026-07-27]] · [[../sessions/2026-07-25]]

---

## Reporting layer consolidated: Jarvis, Norman, Lucy retired · 2026-07-25
**Decision:** Retired three reporting agents and split their functions across the
two that already run. **Lens** absorbed Jarvis's regime engine plus risk
validation for Blade and Edge. **Victoria** absorbed Lucy's scouting desk plus
risk validation for Jerry and Chad. Trading infrastructure (Blade, Edge, Jerry,
Chad, Tao) **untouched**. Nothing activated in cron — 4 new lines built, tested,
and `#HOLD PENDING-APPROVAL`'d pending Jase's review.
**Why:** three agents, three cron slots and three voices for functions that map
cleanly onto two agents already on schedule. Fewer moving parts, same outputs.
**Two premises in the brief were wrong and are corrected in the build:**
- Blade has **no "strategy mode selector."** It reads `strategy_recommendation.json`
  for observation only (Critical Rule #6). And **five** consumers read that file —
  Blade, Edge, Jerry, Crisp, hq-app — not one. Contract frozen and verified for all
  five; new keys are additive only. See CLAUDE.md §4h.
- The **Multi-Timeframe Convergence Score had already been deleted** in the
  2026-06-01 trim. There was no code to move. Rebuilt from the four components
  Jarvis's own brief documents; **the weights are new and stated openly** in
  `lens_regime.py` rather than passed off as the recovered original.
**Also decided:** the two regime briefings did **not** fold into Lens's 04:55
thesis run. The thesis is a daily research product; the regime read is
session-scoped, and a 04:55 read is ~7h stale by the NY open — when Blade's NY_PM
session consumes it. Merging would serve a stale regime or triple Anthropic spend.
See [[../sessions/2026-07-25]].

---

## Norman's sample-size gate: one implementation, imported twice · 2026-07-25
**Decision:** The brief called for duplicating Norman's full pipeline into both
Lens and Victoria. Instead the pipeline was extracted **once** to
`scripts/risk_validation.py` and imported by both validators; each owns its own
roster, loaders, prompt, report and delivery.
**Why:** duplicating a *safety rail* is how rails drift. Two hand-copied gates
means the next person to fix a bug in one has no way to know the other exists —
the same class of failure as the stale-feed bugs fixed earlier the same night.
One implementation is the strongest available guarantee the gate is identical in
both places. It is still **tested independently from each side**: `--test-gate`
runs four rogue-synthesis cases (under-sample → PASS refused, no-data → FAIL
refused, no-balance → MARGINAL refused, sufficient sample → synthesis allowed).
Both validators pass all four.

---

## All-zero P&L is NO_DATA, not a grade · 2026-07-25
**Decision:** `validate_strategy()` now refuses to grade a sample where every
trade reports exactly 0.00 P&L (n>=5), returning `NO_DATA` with the reason.
**Why:** bringing Jerry under validation for the first time exposed that all 90 of
his closed positions carry `pnl: 0.0` — `jerry_trader.py` never writes realised
P&L on close. Without this guard the sample is large enough to clear the 20-trade
gate and grades **FAIL** (0% WR, PF 0, Sharpe 0): a real-looking verdict on a feed
that reported nothing. Extends Critical Rule #9 ("an empty success is not a
verified zero") from the loaders into the validator itself. Fixing Jerry's close
path is a separate open task; until then he is correctly ungradeable.

---

## Helius wired + Chad wallet intelligence (Phase 2) · 2026-07-24
**Decision:** Added `HELIUS_API_KEY` to `.env` (gitignored, read-only data key)
and built `agents/crisp/chad_wallet_intel.py`. Authorized by Jase.
**Why:** Chad's wallet-intelligence layer — track smart-money Solana wallets,
detect swaps, simulate copies, score wallets. **Seeding:** Helius has no "top
traders" endpoint, so wallets are seeded from **real recent pump.fun SWAP
feePayers** via the Enhanced Transactions API (reported transparently).
**Tested live:** 12 wallets seeded, 32 real swaps detected + simulated.
**Sim-only, architecturally:** only HTTP GETs + local JSON writes — no signer,
keypair, or order path; execution is impossible by construction. Scoreboard is
sparse (activity counts only; performance ranking flagged pending, not
fabricated). Gotcha: Helius WAF 403s the default `Python-urllib` UA — send a
real User-Agent. See [[../sessions/2026-07-24]].

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
to what's actually live. Applies to [[../agents/victoria]], [[../agents/_retired/norman|norman]],
[[../agents/_retired/lucy|lucy]] (PRIMARY), and [[../agents/_retired/jarvis|jarvis]] (`infer` primary).

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
**Decision:** Migrate [[../agents/victoria]] and [[../agents/_retired/norman|norman]] off the
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
- [[../agents/_retired/jarvis|jarvis]] — `macro-regime-detector`, `market-breadth-analyzer`, `sector-analyst`
- [[../agents/_retired/norman|norman]] — `backtest-expert`, `position-sizer`
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

See [[../agents/_retired/jarvis|jarvis]] · [[../infrastructure/personalities]].

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

## 2026-07-25 (later) — Tao parked until TAO > $393; nothing was ever staked

**Decision:** Park the Tao agent entirely — all 5 crons `#HOLD`'d — until TAO
crosses **$393**, and gate reactivation on a verified execution path rather
than on price alone.

**Why:** taostats confirmed the coldkey has never held stake (Root 0, Alpha 0,
Delegated 0; subnet table shows only "Unstaked TAO"). The DCA engine had
reported 5 successful entries deploying 3.344971 τ. All fiction. The extrinsics
*were* submitted — 0.056408 τ burned in fees at ~0.001446 τ × 39 attempts —
but no stake resulted. Jase's rationale for the threshold: bear market, no
staking into declining subnets, stake with momentum on the way back up.

**Root cause** — three defects, all required:
1. `run_btcli_stake()` sets `success = returncode == 0`, nothing else. btcli
   exiting 0 after printing a warning banner and an empty "Staking to:" table
   is recorded as SUCCESS.
2. No post-submit verification anywhere. `get_balance()` runs once before the
   run, never after.
3. `update_state_and_portfolio()` is called unconditionally; `exec_ok` only
   selects a log status string.

**Source-of-truth reversal.** This **supersedes** the conclusion in the entry
below. The Apr 15 `tao_wallet_state.json` was **accurate**; `tao_dca_state.json`
is the fabricated record, now flagged `UNRELIABLE_DO_NOT_TRUST`. On-chain is
the only truth for positions. Real result: −34% on price, not the −87.4%
computed over phantom positions.

**Hard gate — crossing $393 does NOT authorize staking.** Written into the
alert body itself so it travels with the notification: (1) DCA bug fixed,
(2) bittensor 10.2.0 migration done, (3) a small test stake verified on-chain
via taostats. `entries_executed` must also be reset to 0.

**What still runs:** `scripts/tao_price_watch.py`, daily 08:00 ET. One
CoinGecko GET; no LLM, no bittensor import, no chain connection, no wallet
access; alert-only, fires once. It cannot stake by construction.

**Deliberately not done:** no fix to the staking path, no re-stake attempt.
Diagnosis only, per instruction.

**See:** [[../agents/tao]] · [[../sessions/2026-07-25]] · [[../infrastructure/data-freshness]]

---

## 2026-07-25 — Silent fallbacks banned; cron moved to ET wall-clock

**Decision:** (1) Any value that could not be refreshed must carry its
provenance — renderers mark it, graders refuse it (`CLAUDE.md` Critical Rule
#9, `scripts/data_freshness.py`). (2) A deterministic gate outranks an LLM's
narrative verdict, enforced in code after synthesis returns, not by prompt
alone (Rule #10). (3) ET-scheduled cron jobs use a dual-hour + ET-guard
pattern rather than a fixed UTC hour.

**Why (1):** Two silent failures ran for months. Tao's `check_emissions()`
caught the bittensor error and returned the stored value bare, so an April 15
root-stake snapshot printed as live. Norman graded 330 TradeLocker trades whose
newest close was 2026-05-27 — a broker Blade left when it moved to OANDA —
producing confident FAIL verdicts about a dormant account. Neither errored;
both looked normal. The pattern, not the instances, was the bug.

**Why (2):** `_determine_verdict()` correctly returned `INSUFFICIENT_DATA`
below 20 trades, but the merge line read `ar.get('verdict') or val.get(...)` —
the model's answer first. So Edge shipped a substantive verdict off **0
trades**. A prompt instruction is not a gate; the override is now code.

**Why (3):** The earlier standardization prompt never executed (no commit, no
crontab change, no Sunday variant in any backup). Re-doing it surfaced that the
specified mechanism does not work here: `TZ=` is inert for scheduling on
vixie-cron 3.0pl1, and `CRON_TZ=` — the documented fix — **is not supported on
this build at all** (absent from binary and man page; a live probe never
fired). Adopted the pattern `man 5 crontab` itself recommends: schedule both
candidate UTC hours, guard on ET. Verified live before adoption. Survives the
November DST shift with no edit.

**Also decided:** *not* to rename `agents/crisp/` → `agents/chad/`. Commit
`0e94cec` deliberately aliased display-name-only, matching the documented
`strategist → JARVIS` convention (Critical Rule #7). Norman now renders "Chad"
via `AGENT_DISPLAY` while internal keys stay `crisp` — fixing the reported
symptom without a 124-file migration that would orphan historical JSON keyed
`crisp` and touch live sync crons. Flagged to Jase as his call.

**Open:** Blade has **no OANDA trade record yet** — `agent_trades.json` holds
zero `agent='blade'` rows, so Norman reports `NO_DATA` rather than grading the
legacy feed. Blade's authoritative balance (`blade_balance.json`) is `0`
pending Jase's edit-mode entry, so Monte Carlo is skipped rather than run
against the old invented 10,000 notional.

**See:** [[../infrastructure/data-freshness]] · [[../infrastructure/cron-schedule]]
· [[../agents/_retired/norman|norman]] · [[../agents/tao]] · [[../sessions/2026-07-25]]

---

## Earlier history
For decisions made before 2026-06-01, see git log on the repo and the
prior `CLAUDE.md` history. Not all earlier decisions are documented here —
the vault was built 2026-06-01.

## Related
- [[../sessions/2026-06-01]] — the session where most of these happened
- [[../00-START-HERE]]
