# Unusual Whales API — Assessment
*Researched: 2026-03-26*

## What's Available

### 100+ REST Endpoints across 20+ categories

**Base URL:** `https://api.unusualwhales.com`
**Auth:** `Authorization: Bearer YOUR_API_TOKEN` header
**Required anti-hallucination header:** `UW-CLIENT-API-ID: 100001`
**OpenAPI spec:** `https://api.unusualwhales.com/api/openapi`
**All endpoints are GET-only.**

---

### Core Endpoints for Our Operation

#### Options Flow (Unusual Activity)
- `GET /api/option-trades/flow-alerts` — **the core endpoint**; 50+ filter params
  - Filters: `ticker_symbol`, `min_premium`, `is_call`/`is_put`, `is_otm`, `is_floor`, `is_sweep`, `is_multi_leg`, `size_greater_oi`, `vol_greater_oi`, `min_dte`/`max_dte`, `min_volume_oi_ratio`, `min_iv_change`, `newer_than`, `older_than`, `limit` (max 200)
  - Fields returned: `alert_rule`, `expiry`, `has_floor`, `has_multileg`, `has_sweep`, `open_interest`, `strike`, `ticker`, `total_premium`, `total_size`, `trade_count`, `type`, `underlying_price`, `volume`, `volume_oi_ratio`
- `GET /api/stock/{ticker}/flow-alerts` — per-ticker version
- `GET /api/option-trades/full-tape/{date}` — full tape for a date ($250/mo addon)
- WebSocket `flow-alerts` channel — live streaming flow alerts
- WebSocket `option_trades` / `option_trades:TICKER` — raw tape (~6-10M records/day)

#### Dark Pool Flow
- `GET /api/darkpool/recent` — market-wide, last 200, filterable by premium/size/volume/date
- `GET /api/darkpool/{ticker}` — per-ticker
- Fields: `canceled`, `executed_at`, `market_center`, `nbbo_ask`, `nbbo_bid`, `premium`, `price`, `size`, `ticker`, `tracking_id`, `trade_code`, `volume`
- WebSocket `off_lit_trades` channel — live dark pool streaming

#### Market-Wide Flow Indicators
- `GET /api/market/market-tide` — **proprietary Market Tide** (net call/put premium at 1m/5m intervals, back to 2022-09-28); fields: `net_call_premium`, `net_put_premium`, `net_volume`, `timestamp`
- `GET /api/market/total-options-volume` — total market options volume
- `GET /api/market/oi-change` — market-wide OI change
- `GET /api/net-flow/expiry` — net flow grouped by expiry
- `GET /api/market/top-net-impact` — top net premium impact tickers
- `GET /api/market/sector-etfs` — sector ETF flow
- `GET /api/market/{sector}/sector-tide` — sector-level tide
- `GET /api/group-flow/{flow_group}/greek-flow` — Greek flow for groups (mag7, semis, banks, etc.)

#### Congressional / Senate Trading
- `GET /api/congress/recent-trades` — filterable by ticker, date
- `GET /api/congress/congress-trader` — by individual member
- `GET /api/congress/late-reports` — late filings
- `GET /api/politician-portfolios/recent_trades` — same data, different schema
- `GET /api/politician-portfolios/holders/{ticker}` — who in congress holds a ticker
- Fields: `amounts`, `filed_at_date`, `member_type` (house/senate), `name`, `ticker`, `transaction_date`, `txn_type` (Buy/Sell)

#### Institutional Holdings (13F)
- `GET /api/institutions` — ~9,000 institutions tracked
- `GET /api/institutions/latest_filings` — latest 13F filings
- `GET /api/institution/{cik}/activity/v2` — activity (use CIK, not name)
- `GET /api/institution/{cik}/holdings` — full holdings
- `GET /api/institution/{ticker}/ownership` — who owns a given ticker
- Fields: `avg_price`, `first_buy`, `historical_units`, `perc_of_share_value`, `sector`, `ticker`, `units`, `units_change`, `value`

#### GEX / Greeks (High Value for Our Pinning/Gamma Analysis)
- `GET /api/stock/{ticker}/greek-exposure` — total GEX
- `GET /api/stock/{ticker}/greek-exposure/strike` — GEX by strike (key for pin analysis)
- `GET /api/stock/{ticker}/greek-exposure/expiry` — GEX by expiry
- `GET /api/stock/{ticker}/spot-exposures` — spot GEX per 1-minute
- `GET /api/stock/{ticker}/nope` — NOPE metric (net options pricing effect)
- `GET /api/stock/{ticker}/iv-rank` — IV rank / percentile
- `GET /api/stock/{ticker}/volatility/term-structure` — IV term structure
- WebSocket `gex:TICKER` and `gex_strike:TICKER` — live GEX streaming

#### Additional Useful Endpoints
- `GET /api/short_screener` / `GET /api/shorts/{ticker}/interest-float/v2` — short data
- `GET /api/screener/stocks` — stock screener
- `GET /api/market/economic-calendar` — macro calendar
- `GET /api/earnings/{ticker}` — earnings history + pre/post market reactions
- `GET /api/stock/{ticker}/max-pain` — max pain by expiry
- `GET /api/stock/{ticker}/net-prem-ticks` — call/put net premium tick history

---

## WebSocket Streaming

**Endpoint:** `wss://api.unusualwhales.com/socket?token=YOUR_API_TOKEN`

**Protocol:** Join with `{"channel":"channel_name","msg_type":"join"}`, receive `[channel_name, payload]` arrays.

| Channel | Use Case |
|---|---|
| `flow-alerts` | Live unusual options flow |
| `option_trades` | Full raw tape (very high volume) |
| `option_trades:TICKER` | Single-ticker tape |
| `off_lit_trades` | Live dark pool |
| `lit_trades` | Live lit equity trades |
| `price:TICKER` | Live price ticks |
| `gex:TICKER` | Live GEX updates |
| `news` | Live headlines |

---

## Pricing

| Tier | Price |
|---|---|
| Trial | $50/week |
| Basic | $150/month |
| Advanced | $375/month |
| Full Tape Addon | $250/month (historical options tape) |
| Kafka Streaming | Enterprise — price not public |

**No free tier for API access.** The "free tier" on the pricing page refers to the platform dashboard only.

Rate limits are returned in response headers (`x-uw-token-req-limit`, `x-uw-daily-req-count`, `x-uw-req-per-minute-remaining`). Daily limit resets at 8 PM Eastern. Specific tier limits not publicly documented.

---

## MCP Server

Official remote MCP (works with Claude Code):
```bash
claude mcp add unusualwhales --transport http https://api.unusualwhales.com/api/mcp \
  -H "Authorization: Bearer YOUR_KEY"
```

Official npm local MCP:
```bash
npx -y @unusualwhales/mcp  # env: UW_API_KEY=your_key
```

Ships with 18+ tools, 123+ actions, and 30+ named analysis prompts including:
`daily-summary`, `morning-briefing`, `unusual-flow`, `dark-pool-scanner`, `congress-tracker`, `ticker-analysis`, `pre-earnings`, `greek-exposure`

---

## Integration Assessment

### How It Fits Our System

Our strategy engine already uses session routing and ORB/pip-based frameworks. UW fills the **conviction layer** — confirming whether institutional/smart money supports a setup before entry, and providing real-time flow context during a trade.

**Highest-value integrations:**

1. **Pre-session morning brief** (daily, before open)
   - `market-tide` for overnight/premarket net premium direction
   - `darkpool/recent` filtered for large prints (>$500K premium) in our watchlist
   - `flow-alerts` from prior session close to current premarket for accumulation signals
   - `group-flow/mag7/greek-flow` for sector context

2. **ORB confirmation layer** (15m after open)
   - On a breakout signal: hit `stock/{ticker}/flow-alerts` for 0DTE/1DTE sweep activity
   - Check `stock/{ticker}/greek-exposure/strike` to see if breakout level has GEX wall or vacuum
   - `stock/{ticker}/net-prem-ticks` intraday to confirm call premium leading

3. **Dark pool alert filter** (continuous during session)
   - Stream `off_lit_trades` WebSocket, filter for: `premium > 250000` AND `size > 50000` AND `price < nbbo_ask * 0.98` (below-ask dark = distribution signal)
   - Cross-reference with `stock/{ticker}/flow-alerts` for corroborating sweeps

4. **GEX pin/magnet analysis**
   - `stock/{ticker}/greek-exposure/strike` for current expiry — identify dealer hedging walls
   - Use `spot-exposures` (1m GEX) to see intraday GEX shift as price moves
   - `stock/{ticker}/max-pain` for end-of-day gravity target

5. **Congress/Insider as swing signal generator** (non-intraday)
   - `congress/recent-trades` daily scan for large buys by known active traders
   - `insider/transactions` for sector rotation signals

### Endpoints NOT Prioritized (lower signal/noise for our timeframes)
- Crypto endpoints — not part of current instrument set
- Prediction markets — not relevant
- Earnings fundamental data (balance sheets, income statements) — not our edge
- Seasonality — too slow for our session-based operation
- Analyst ratings screener — not our framework

---

## Implementation Plan

### Phase 1 — Token + Basic REST (Week 1)
- [ ] Purchase Basic tier ($150/mo) — enough for REST polling
- [ ] Build `uw_client.py` wrapper around the REST endpoints we need, respecting rate limit headers
- [ ] Add to strategist agent: morning pre-session brief using market-tide + dark pool + flow-alerts
- [ ] Test `stock/{ticker}/greek-exposure/strike` integration for ORB trade confirmation

### Phase 2 — WebSocket Streaming (Week 2)
- [ ] Connect `flow-alerts` WebSocket; filter and push to strategist in real-time
- [ ] Connect `off_lit_trades` WebSocket; filter large dark pool prints to watchlist
- [ ] Connect `gex:TICKER` for live GEX updates on active trades

### Phase 3 — MCP Integration (Week 3)
- [ ] Add UW MCP server to Claude Code for ad-hoc analysis during session
- [ ] Build named prompts for our standard workflows: ORB-check, pre-session-brief, dark-pool-scan

### Phase 4 — Upgrade Evaluation
- [ ] After 30 days, assess if Advanced tier ($375/mo) is justified based on usage
- [ ] Evaluate full tape addon ($250/mo) if we need historical tick-by-tick options replay for backtesting

---

## Cost Estimate

| Item | Cost |
|---|---|
| Basic API tier | $150/month |
| Optional full tape | $250/month |
| **Minimum viable** | **$150/month** |
| **Full build-out** | **$400/month** |

---

## Key Gotcha

**Do not use `/api/options/flow`** — this endpoint does not exist and will 404. The correct path is `/api/option-trades/flow-alerts`.

All requests require both:
1. `Authorization: Bearer YOUR_KEY`
2. `UW-CLIENT-API-ID: 100001`
