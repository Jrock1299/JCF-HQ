# Data Freshness — killing silent fallbacks

**Added:** 2026-07-25 · **Module:** `scripts/data_freshness.py`
**Consumers:** [[_retired/norman|norman]], [[tao]] · **Related:** [[cron-schedule]], [[decision-log]]

---

## The failure this exists to prevent

A data source fails or freezes. The caller catches the exception and
substitutes a last-known value. Every downstream consumer then renders that
value as current, with no indicator that it is months old.

Two live instances, both running undetected for months:

| Where | What happened |
|---|---|
| `tao_compounder.check_emissions()` | Caught the bittensor API error and returned `stored_root` bare. "Root Stake 0.000000" — an April 15 snapshot — printed in the weekly Telegram report as a live number. |
| `norman_brain._load_blade_trades()` | Graded 330 TradeLocker trades whose newest record closed 2026-05-27, on a broker Blade no longer uses. Two months of confident FAIL verdicts describing a dormant account. |

Both were *quiet*. Nothing errored. The reports looked normal.

## The rule

> A value that could not be refreshed is returned **with its provenance**,
> never bare. Renderers mark it. Graders refuse it.

Codified as **Critical Rule #9** in `CLAUDE.md`.

## Three traps the module handles

**1. File mtime is not freshness.**
`tao_portfolio.json` is rewritten every run (mtime = today) while its `updated`
field still reads 2026-04-15. `from_file()` prefers an embedded timestamp field
and only falls back to mtime when none exists — reporting which basis it used.

**2. A refreshed file is not fresh data.**
`tradelocker_trades.json` has its `last_sync` bumped every 30 minutes by a cron
job, but no new trade has arrived since May. `from_records()` judges a
collection by its **newest record**, not the container.

**3. An empty success is not a verified zero.**
The chain query for root stake *succeeds* and returns `[]`, while the wallet's
own DCA history claims 1.672485 τ staked to root. `contradicted()` reported
**UNVERIFIED** rather than picking a side.

> **Resolved 2026-07-25 — and this is the module's best case study.** taostats
> confirmed the chain was right: nothing was ever staked. The DCA history was
> fabricated by a *different* instance of the same bug — `btcli` exited 0
> without submitting an extrinsic, and the engine recorded intent as outcome
> (see [[../agents/tao]]).
>
> Two lessons. First, the module worked: it refused to publish `0.000000` as
> fact *and* refused to trust the history — flagging a real contradiction
> instead of laundering either number. Second, **freshness tooling can detect
> a contradiction but cannot adjudicate it.** Resolving this took an external
> source of truth (taostats). When two internal sources disagree, escalate to
> something outside the system; do not let code pick a winner.
>
> The compounder now treats on-chain as truth and flags the DCA history as
> unreliable, gated on `_dca_history_is_trusted()` so the trust decision is
> checked rather than assumed.

## API

```python
from data_freshness import from_file, from_records, call_failed, contradicted, banner

fr = from_file(path, stale_after_days=7, ts_fields=('updated',))
fr = from_records('source', trades, stale_after_days=14)   # newest record wins
fr = call_failed('live call', exc, fallback_as_of=stored_ts)
fr = contradicted('live call', 'returned empty; history says otherwise')

fr.stale        # bool
fr.marker()     # "⚠️ STALE — last updated Apr 15, 2026 (101d ago)"  ('' if fresh)
fr.annotate(v)  # value + marker
banner({...})   # multi-line block listing every stale source
```

Reasons: `fresh` · `stale` · `missing` · `unreadable` · `empty` ·
`no_timestamp` · `call_failed` · `contradicted`.

## Tolerances

| Consumer | Window | Why |
|---|---|---|
| Tao compounder | 7 days | Collector writes 3×/day, scorer daily — a week of silence is a broken pipeline, not a quiet week. |
| Norman | 14 days | Trading agents run weekday sessions; catches dead feeds (months) without crying wolf over a quiet fortnight. |

## Where it surfaces

- **Tao weekly report** — freshness banner above the numbers, per-field `⚠️`
  markers, and `_freshness` published into `tao_portfolio.json` for the dashboard.
- **Norman weekly report** — `━━ ⚠️ DATA QUALITY ━━` block above the verdicts;
  stale sources produce `STALE_DATA` / `NO_DATA` instead of a grade.
