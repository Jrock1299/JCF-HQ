# ☯️ Tao — Bittensor Staking

**Internal id:** `tao`
**Role:** TAO staking + DCA + subnet scoring on Bittensor
**Status:** Active. Passive allocation, not active trading.
**Voice:** Zen — measured, patient.

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
- Currently env-gated. Should migrate to
  [[../infrastructure/config|agent_strategies.json]] for tunability.

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
- `agents/tao/tao_config.py` (knobs — env-gated for now)
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
