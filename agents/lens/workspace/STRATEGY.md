# Lens Analysis Strategy

## Pairs Covered
- BTC/USDT
- XAU/USD (Gold)
- US100/NAS100
- SPX500
- US OIL (WTI Crude)

## Process — run this exactly every time Lens is triggered
1. Use the Tavily skill at ~/.openclaw/workspace/skills/tavily-search/SKILL.md for latest news on each pair:
 - "BTC Bitcoin market analysis today"
 - "Gold XAU market outlook today"
 - "US100 Nasdaq market analysis today"
 - "SPX500 S&P 500 market analysis today"
 - "WTI crude oil price market analysis today"
   (Use Tavily search with --topic news and a recent days window.)
2. Read /root/.openclaw/dashboard/agent_trades.json — check recent Crisp/Blade results for directional context
3. Read /root/.openclaw/dashboard/market_bias.json — compare previous bias to current, note any shifts
4. Read /root/.openclaw/dashboard/sentinel_data.json — check watchlist_signals, top_discoveries, analyst_recommendations, earnings_calendar
5. For each pair assign:
 - bias: Bullish / Bearish / Neutral
 - confidence: 0-100% (be honest, never inflate)
 - analysis: 2-3 sentences max, grounded in what you actually found
6. Generate all calculation fields (see Output Schema below)
7. Write updated market_bias.json
8. Send Telegram report to Jase (ID: 797062420)

## Confidence Guidelines
- 75%+: Strong conviction, clear directional signals across news + price
- 50-74%: Moderate conviction, mixed signals
- Below 50%: Use Neutral bias, flag conflicting data in analysis

## Output Schema
/root/.openclaw/dashboard/market_bias.json:
```json
{
  "last_updated": "<ISO timestamp>",
  "summary": "<1-3 sentence top-level macro summary>",
  "morning_report": "<3-5 sentence morning briefing, more detailed>",
  "priorities": "1. ...<br>2. ...<br>3. ...<br>4. ...<br>5. ...",
  "pairs": [
    {"symbol": "BTC/USDT", "bias": "bullish", "confidence": 72, "note": "..."},
    {"symbol": "XAU/USD",  "bias": "bullish", "confidence": 68, "note": "..."},
    {"symbol": "US100",    "bias": "neutral",  "confidence": 54, "note": "..."},
    {"symbol": "US OIL",   "bias": "neutral",  "confidence": 60, "note": "..."}
  ],
  "forex_news": [
    {"headline": "...", "source": "Reuters", "time": "38m ago", "impact": "high"}
  ],
  "market_impact": [
    {"asset": "BTC",     "direction": "BULLISH",  "reasoning": "one sentence"},
    {"asset": "XAU/USD", "direction": "BULLISH",  "reasoning": "one sentence"},
    {"asset": "SPX500",  "direction": "NEUTRAL",  "reasoning": "one sentence"},
    {"asset": "DE30",    "direction": "BEARISH",  "reasoning": "one sentence"},
    {"asset": "USOIL",   "direction": "NEUTRAL",  "reasoning": "one sentence"}
  ],
  "watchlist_calculations": {
    "AAPL": {
      "significant": true,
      "direction": "BULLISH",
      "reasoning": "2-3 sentences on why this insider activity matters"
    }
  },
  "discovery_calculations": {
    "NVDA": {
      "signal_type_explanation": "what CLUSTER_BUY means in context",
      "company_context": "brief company description and why this matters",
      "worth_attention": true,
      "reasoning": "brief analysis"
    }
  },
  "consensus_top3": [
    {"ticker": "MSFT", "action": "BUY", "reasoning": "brief take on why"},
    {"ticker": "AMZN", "action": "HOLD", "reasoning": "brief take on why"},
    {"ticker": "GOOGL", "action": "BUY", "reasoning": "brief take on why"}
  ],
  "earnings_calculations": {
    "AAPL": {
      "direction": "UP",
      "beat_scenario": "what happens if earnings beat — likely price action",
      "miss_scenario": "what happens if earnings miss — likely price action"
    }
  }
}
```

## Calculation Instructions

### market_impact
For each of: BTC, XAU/USD, SPX500, DE30, USOIL
- One sentence directional call based on today's news and macro context
- Direction: BULLISH / BEARISH / NEUTRAL

### watchlist_calculations  
For each ticker in sentinel_data.watchlist_signals:
- significant: Is the insider activity notable given the amount and pattern? (bool)
- direction: BULLISH / BEARISH based on whether insiders are buying or selling
- reasoning: 2-3 sentences. Is it a lone buy or coordinated? What's the context?

### discovery_calculations
For each ticker in sentinel_data.top_discoveries:
- signal_type_explanation: Plain English explanation of what CLUSTER_BUY / MULTI_BUY / INSIDER_BUY means
- company_context: 1 sentence on what the company does
- worth_attention: Should we investigate further? (bool)
- reasoning: Brief analysis of whether this is actionable

### consensus_top3
From sentinel_data.analyst_recommendations, pick the 3 most notable tickers:
- Strong buy conviction (high bullish % or meaningful shift)
- Include brief reasoning for each

### earnings_calculations
For each ticker in sentinel_data.earnings_calendar (next 7 days):
- direction: UP / DOWN / NEUTRAL into earnings based on sector trends + recent performance
- beat_scenario: 1 sentence on likely price action if beats
- miss_scenario: 1 sentence on likely price action if misses

## Telegram Report Format
🧠 LENS — MACRO DESK
🕐 <time> UTC | <date>

📈 BTC/USDT Bullish 72%
<2-3 sentence analysis>

📈 XAU/USD Bullish 68%
<2-3 sentence analysis>

📉 US100 Neutral 54%
<2-3 sentence analysis>

📉 US OIL Neutral 60%
<2-3 sentence analysis>
