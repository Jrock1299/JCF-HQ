# ☯️ Tao — Bittensor Staking

**Internal id:** `tao`
**Role:** TAO staking + DCA + subnet scoring on Bittensor
**Status:** 🛑 **PARKED 2026-07-25.** All 5 cron jobs `#HOLD`'d. Nothing was
ever staked. Reactivates only when TAO > **$393** *and* the gate below is met.
**Voice:** Zen — measured, patient.

---

## 🛑 PARKED — read before touching anything

**Ground truth (taostats, coldkey `5FPP7TKkkY4Jpoobg…`, verified 2026-07-25):**
balance **3.288560861 τ** · Root **0** · Alpha **0** · Delegated **0** · subnet
table shows one row: *"Unstaked TAO."* Account created 03 Apr 2026.

The DCA engine reported 5 successful entries (3.344971 τ across root + 8
subnets) Apr 3–15 2026. **None of it landed on-chain.** The extrinsics were
submitted — 0.001446 τ fee each, 39 total = **0.056408 τ burned** — but
produced no stake. See [[../sessions/2026-07-25]] for the full root cause.

**Real position:** 3.2886 τ, entirely unstaked, ~$625 at $190.11 against a
~$944 cost basis ≈ **−34%** (price drawdown). The **−87.4%** previously
reported was arithmetic over positions that never existed.

**Jase's decision (2026-07-25):** Tao does nothing until TAO crosses **$393**.
Bear market; no staking into declining subnets; stake with momentum on the way
back up.

### Source-of-truth reversal

| Source | Status |
|---|---|
| `tao_wallet_state.json` (Apr 15) | ✅ **ACCURATE** — `total_staked_tao: 0.0`, `free_tao: 3.288560861`, matches taostats exactly |
| `tao_dca_state.json` | ❌ **FABRICATED** — flagged `_status: UNRELIABLE_DO_NOT_TRUST`, retained as evidence only |
| On-chain / taostats | ✅ **The only truth for positions** |

This **reverses** the earlier 2026-07-25 conclusion, which treated the empty
chain response as suspect and the DCA history as corroborating. The chain was
right.

### ⛔ Hard gate on reactivation

**Crossing $393 does NOT authorize staking.** The price watcher's alert says so
in its own body. All three must be true before any real stake executes:

1. **The DCA silent-failure bug is fixed** — the path that logged 5 successful
   entries while zero extrinsics landed.
2. **The bittensor 10.2.0 SDK migration is done** — `Balance()` rejects a
   tuple; `Swap.AlphaSqrtPrice` storage function is gone.
3. **A SMALL test stake is verified ON-CHAIN via taostats** before any larger
   amount follows.

Also reset `entries_executed` to **0** — the recorded 5 are fiction.

### What still runs

`scripts/tao_price_watch.py` — daily 08:00 ET, ET-guarded. One CoinGecko GET.
No LLM, no bittensor import, no chain connection, no wallet access. Alerts
**once** if TAO > $393, silent otherwise (no log, no Telegram, no churn).
**It cannot stake — there is no code path in it that could.**

```
python3 scripts/tao_price_watch.py --status   # inspect, send nothing
python3 scripts/tao_price_watch.py --reset    # re-arm the one-shot alert
```

---

## What Tao does
A 5-phase pipeline running on cron:
1. **Data collection** — pulls TAO price from CoinGecko, subnet metrics
   from the Bittensor subtensor RPC
2. **Subnet scoring** — ranks subnets daily
3. **DCA engine** — staggered entries based on price-vs-MA + cooldown rules
4. **Profit monitor** — checks unrealized gains every 6 hours
5. **Weekly compounder** — Saturday roll-up and report

## DCA rules
- Total DCA entries: 5
- Entry 1: executes immediately on first run (get capital working)
- Entries 2-5: require price 2%+ below 7-day MA AND 48h cooldown since last entry
- Knobs: `TOTAL_DCA_ENTRIES`, `ROOT_STAKE_PCT`, `SUBNET_STAKE_PCT`,
  `DCA_COOLDOWN_HOURS`, `DCA_DIP_THRESHOLD_PCT`, `MIN_SUBNET_SCORE`
- **Sourced from [[../infrastructure/config|agent_strategies.json]]**
  under the `"tao"` block as of 2026-06-01. Tao reads via
  `load_strategy('tao', defaults)`; `.env` overrides are still honored if set
  (none currently); hardcoded defaults are the final fallback. Secrets
  (wallet mnemonics, CoinGecko key, Telegram tokens) remain in `agents/tao/.env`.

## Schedule (UTC)
| Job | Cron |
|---|---|
| Data collection | `0 3,11,19 * * *` (3×/day) |
| Subnet scoring | `0 6 * * *` (daily) |
| DCA engine | `0 9,21 * * *` (2×/day) |
| Profit monitor | `0 0,6,12,18 * * *` (every 6 hours) |
| Weekly compounder + report | `0 8 * * 6` (Saturday) |

## Key files
- `agents/tao/tao_data_collector.py`
- `agents/tao/tao_subnet_scorer.py`
- `agents/tao/tao_dca_engine.py`
- `agents/tao/tao_profit_monitor.py`
- `agents/tao/tao_compounder.py`
- `agents/tao/tao_config.py` (knobs — sourced from `agent_strategies.json`)
- `dashboard/tao_portfolio.json`

## Cross-agent connections
- Reports to: [[victoria]] (daily P&L breakdown), Telegram via [[huncho]]
- Reads: none from other JCF agents (independent)

## Notes
- Tao is the only "non-trading" agent that stays active by design. It's a
  passive allocation track that runs alongside the trading agents and shows
  up in the daily P&L breakdown.
- Could read [[lens]] `market_bias.json` for TAO macro context — currently
  doesn't (flagged in the 2026-06-01 isolation audit). Pending decision.
