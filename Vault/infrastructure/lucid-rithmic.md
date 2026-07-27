# Lucid Trading + Rithmic — Integration Scoping

**Status:** RESEARCH ONLY. No code, no credentials, no live connection.
Written 2026-07-27 while Jase was mid-eval on a Lucid $50K Flex account.
Do not act on any part of this doc without Jase's explicit go-ahead per
specific step.

**Related:** [[../agents/blade|Blade]] (session-based ICT — closest existing
strategy), [[../strategies/orb-strategy|ORB]], [[../decisions/decision-log|Decision log]]

---

## 1. What Lucid is (context)

Lucid Trading is a futures-prop-firm evaluation product. A "Flex" account
is a simulated $50K account with rules Jase must satisfy to pass to a
funded account. Two rules matter for automation scoping:

1. **Automation is permitted** on eval and funded accounts (Rithmic API).
2. **Intraday only** — all positions must be flat by **4:45 PM EST**. Any
   position still open is auto-liquidated by Lucid. No overnight,
   no weekends.

**Everything below assumes those two facts hold.** Jase should re-confirm
with Lucid support before we build anything — prop firm rules change and
"automation allowed" often has a footnote (session-only, no HFT patterns,
no news-event orders, etc.).

---

## 2. Rithmic — the API path

Rithmic is the trade-infrastructure provider Lucid runs on. It is not
Lucid's API; it is Lucid's *broker* backend. Any automation goes through
Rithmic's protocol, not through Lucid's website.

### What "the API" actually is

Rithmic exposes its trading platform via a proprietary protocol
(Rithmic Protocol Buffer / RProtocol) over **WebSocket + TLS**, using
Google Protocol Buffers for message framing. There is no REST API. Two
practical Python paths:

| Path | What it is | Fit for JCF HQ |
|---|---|---|
| **`async_rithmic`** (community lib) | Modern async Python wrapper over the raw protocol. Actively maintained. Supports order routing, market data, PnL. | **Preferred.** Async matches how Blade already runs (asyncio-friendly loops). |
| **`pyrithmic`** (community lib, sync) | Older sync wrapper. Simpler but blocking. | Fallback if async lib has issues. |
| **R\|API+ (official C++/C# SDK)** | Rithmic's official SDK. Not Python-native. | Skip. Adds a language boundary we don't need. |

**Neither community library is officially blessed by Rithmic.** They work
against Rithmic's Test system today but a protocol change on Rithmic's
side can break them. Design the integration so the Rithmic client is a
single replaceable module (like Blade's `blade_oanda.py`), not scattered
across strategy code.

### What Jase needs to provide (do NOT ask for yet)

When we're ready to build — not now — Jase will need:

1. **Rithmic credentials issued by Lucid**
   - Username, password
   - System name (Lucid's Rithmic system identifier, e.g. `Rithmic 01`,
     `Rithmic Paper Trading`, `Rithmic Test`) — Lucid will tell him
     which one his account routes to
   - Gateway URL (server hostname) — Rithmic runs geo-distributed
     gateways (Chicago, Frankfurt, etc.); Lucid will provide the correct
     one for his account
2. **API access enabled on his Lucid account**
   - This is an application/approval step handled by Lucid support, not
     Rithmic directly. Some prop firms require a signed automation
     addendum. Assume this takes days, not minutes.
3. **A dedicated eval account for the bot** (recommendation, not required)
   - If Jase is trading his current eval manually, a separate eval slot
     for the bot keeps the two P&Ls cleanly separated and avoids the
     scenario where an agent bug tanks his passing eval.

**Do not request any of these until a validated strategy exists and Jase
gives explicit "wire it up" approval.**

### Paper / sim environment — what "paper" means here

This is the confusing part and worth being precise about:

- **Rithmic Test / Rithmic Paper Trading** is a separate Rithmic system
  where orders go to a simulated matching engine, not the real CME. Any
  Python client can connect if it has Test-system credentials. Some
  brokers issue Test creds free on request; Lucid may or may not.
- **Lucid Flex accounts are themselves simulated** — the "$50K" isn't
  real capital; fills come from a Lucid-side simulator that mirrors CME
  prices. So Jase's live eval is already a form of paper trading, just
  with real evaluation stakes (pass/fail his prop-firm run).
- **What we want for development:** a way to run the agent against
  live-shaped data + simulated fills without touching Jase's eval
  account state.

Three practical options:

| Option | How | Risk |
|---|---|---|
| A. Rithmic Test system creds via Lucid | Ask Lucid for Test-system creds; run bot there | Cleanest — but depends on Lucid granting them |
| B. Second Lucid eval account, bot-only | Buy a $50 eval slot dedicated to the bot | Costs $50 per attempt; realistic fills; failing this eval has no consequence |
| C. Locally simulated fills against Rithmic market data | Connect to Rithmic Test for market data only, fill orders in a local simulator | We control it; but simulated fills are always optimistic vs. live |

**Recommend option A first, fall back to option B.** Option C is what
[[../agents/blade|Blade]] does today (OANDA practice + our own bookkeeping)
and it's fine for strategy R&D but is not "paper on Rithmic" in any
meaningful sense — it doesn't validate the integration layer.

### Latency notes

Rithmic's Chicago gateway sits ~1ms from CME Aurora. From a VPS in
`us-east-1` or `us-central-1`, expect 15–40ms RTT to Chicago Rithmic.
For session-based ICT trading (M1/M5 decision cadence), that's fine.
Any HFT-style pattern is out of scope for JCF HQ and Lucid probably
prohibits it anyway.

**If we ever colocate:** Rithmic supports co-lo but Lucid's automation
permission almost certainly doesn't extend to it. Not a real option.

### Instruments — what's available and what fits

Rithmic routes all CME Group products (CME, CBOT, NYMEX, COMEX) and ICE
US. For session-based ICT trading (which is where JCF HQ's edge research
is focused), the useful subset:

| Symbol | What | Why it fits ICT session trading |
|---|---|---|
| **ES** | E-mini S&P 500 | Deep liquidity, tight spreads, well-defined NY session behavior. First choice. |
| **NQ** | E-mini Nasdaq 100 | Trends more than ES; classic ICT liquidity-sweep patterns fire cleanly. |
| **MES** | Micro E-mini S&P | 1/10 the notional of ES. Perfect for eval-account sizing — a 4pt stop on a $50K eval is $200 on MES vs. $2000 on ES. |
| **MNQ** | Micro E-mini Nasdaq | Same logic as MES vs. NQ. |
| **YM / RTY** | Dow / Russell 2000 minis | Available but less-clean ICT structure. Skip for v1. |
| **6E / 6B** | Euro FX / GBP futures | Session-based FX equivalents to CHF/JPY on OANDA. Deferred — no strategy calls for them yet. |
| **CL / GC** | Crude / Gold | Different session personality, different volatility regime. Deferred. |

**v1 scope: ES + NQ (or MES + MNQ for eval sizing).** Same instruments
Blade already targets in spirit, just as futures instead of CFDs.

---

## 3. Intraday-close safety — architectural design (design only, do not build)

The 4:45 PM EST flat rule is non-negotiable. If we get this wrong, Jase
loses his eval and we've done real damage. It must be enforced
**architecturally**, not by strategy code — the strategy must not be able
to break the rule even if it has a bug.

### Design principle

**A watchdog process, separate from the trading agent, holds the cutoff.
The watchdog has flatten authority the agent does not.**

This mirrors [[../agents/blade|Blade]]'s daily-DD circuit breaker
(`/tmp/blade_dd_<UTC-date>.json`) — a piece of state outside the
strategy, checked before every action.

### Layered enforcement

Four layers, each independent, so a bug in one doesn't defeat the
whole system:

**Layer 1 — Entry cutoff (soft, strategy-level)**
- Hardcoded time gate in the agent: **no new entries after 3:30 PM EST**.
- Configurable in `agent_strategies.json` per instrument.
- Rationale: 75 minutes of runway to let winners run and losers stop
  out naturally before force-close.

**Layer 2 — Reduce-only mode (medium, strategy-level)**
- **3:30 PM – 4:30 PM EST:** agent may only *reduce* existing positions
  (take profit, tighten stops), never open new ones or add to existing.
- Enforced at the order-router boundary: any `side` that would grow
  net exposure is rejected before hitting Rithmic.

**Layer 3 — Force-close (hard, watchdog-level)**
- Separate systemd unit `lucid_watchdog.service` running independently
  of the trading agent.
- At **4:35 PM EST** (10-minute safety margin before Lucid's 4:45 hard
  auto-liquidate): watchdog queries Rithmic account state for open
  positions; if any exist, sends market-close orders for the full size.
- Watchdog has its own Rithmic connection. If the trading agent is
  hung, crashed, or looping, the watchdog still fires.
- Retries with exponential backoff for 3 minutes; if it can't flatten
  by 4:38 PM EST, escalates to Telegram + sends a `pkill -9` to the
  trading agent so its OCO stops fire on their own timeout.

**Layer 4 — Kill switch on Rithmic side (hard, external)**
- Rithmic supports bracket orders + OCO. Every entry the agent sends
  MUST include a stop-loss that expires (`TIF: DAY`) with a `stop_price`
  and a `time_in_force` that Rithmic itself will enforce at session close.
- This is the last-resort layer: even if our watchdog crashes AND the
  agent hangs, Rithmic's session-end order handling flattens the DAY
  orders. Lucid's 4:45 auto-liquidate is the belt-and-suspenders behind
  that.

### State + observability

- `dashboard/lucid_watchdog_state.json` — last heartbeat, next-cutoff
  time, current open positions snapshot
- Telegram alert on: entry-cutoff crossed, reduce-only mode entered,
  force-close initiated, force-close failed
- Post-cutoff daily report: how many force-closes fired vs. how many
  clean session-end flats — a high force-close rate means the strategy
  is holding losers past their expected timeframe and needs review

### DST handling — do this right the first time

**4:45 PM EST is Lucid's rule as posted, but "EST" in trader parlance
usually means "New York wall-clock time" which is EDT half the year.**
Get explicit confirmation from Lucid whether the cutoff is:
- Fixed 21:45 UTC (true EST year-round)
- Fixed 20:45 UTC (true EDT year-round)
- New-York local time (switches with DST — 21:45 UTC winter, 20:45 UTC
  summer)

Bet on option 3 (New-York local) but confirm. Compute the cutoff via
`pytz.timezone('America/New_York').localize(...)`, not by a hardcoded
UTC offset.

### What NOT to do

- Do not put the cutoff logic inside the strategy file. Strategies get
  edited; the cutoff must be immovable.
- Do not rely on the trading agent's main loop being alive to enforce
  the cutoff. That's the failure mode we're guarding against.
- Do not trust wall-clock `time.sleep(...)` for scheduling the force-close.
  Use an absolute timestamp check on every watchdog tick.

---

## 4. Honest readiness assessment

### Do we have anything to trade Lucid autonomously? No.

Current state of validated strategies in JCF HQ:

| Strategy | Norman verdict | Ready for autonomous Lucid? |
|---|---|---|
| [[../agents/blade\|Blade]] D3 ORB | Awaiting 100-cluster D3 validation (per CLAUDE.md §8) | No — still in paper on OANDA CFDs |
| [[../agents/edge\|Edge]] SMA 8/21 | INSUFFICIENT_DATA post-rebuild | No — practice OANDA only |
| Turtle Soup / other ICT variants | **No code exists in this repo** | No — not built |

Zero strategies have crossed Norman's PASS threshold. The prompt that
came in alongside this doc referenced Turtle Soup walk-forward results
and a 28-strategy evaluation — neither exists in the codebase. That work
hasn't been done. See task list for the honest flag on that.

**So the answer to "what should trade Jase's Lucid eval autonomously
today" is: nothing. Nothing is ready.**

### Recommended sequence

1. **Jase trades his current eval manually.** Full stop. No experimental
   agent goes near a real evaluation.
2. **Build the Rithmic connector** (single module, mirror of
   `blade_oanda.py`) against Rithmic Test system. Prove: connect,
   subscribe to ES/NQ M1 bars, place a bracket order, receive fills,
   query account state, disconnect cleanly. **Do not wire it into any
   agent yet.**
3. **Build the watchdog service** (per §3). Test it in isolation with a
   fake position generator — confirm it flattens, retries, alerts,
   escalates. Never test it against a live eval.
4. **Validate a strategy on futures data** — either port Blade to ES/NQ
   or build a fresh ICT session strategy. Run 6+ months of paper on
   Rithmic Test until Norman gives PASS on the futures dataset
   (not the CFD dataset — instrument-specific behavior matters).
5. **Small live allocation only after Jase is funded.** Not on the eval.
   Even then: start with 1 MES contract (~$5 per point), not ES.
   Prove the connector + watchdog on real fills before scaling.

### What to build in the next session (if approved)

- The scoping doc you're reading now
- Nothing else in code

The next code step is item 2 above (Rithmic connector), and it should
be its own explicit conversation — not something bundled into a
"while we're at it."

---

## 5. Open questions for Jase / Lucid support

Batch these when convenient — no rush, since we're not building yet:

1. Which Rithmic system name does a Lucid Flex account route to?
2. Does Lucid issue Rithmic Test-system credentials on request?
3. Is the 4:45 PM EST cutoff a wall-clock NY time or fixed UTC?
4. Is there a written policy on automation strategy types (any
   prohibitions — news trading, HFT, martingale, correlated-pair
   overexposure)?
5. Does the automation approval require a signed addendum, and how long
   does it typically take?
6. Are there per-symbol contract limits on a $50K Flex account?

---

## Change log

- **2026-07-27** — Initial scoping doc created. Research + design only.
  No code, no credentials. Written alongside the honest flag that the
  Turtle Soup / 28-strategy work described in the same session prompt
  does not exist in this repo.
