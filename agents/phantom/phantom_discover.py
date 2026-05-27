"""
phantom_discover.py — Strategy discovery engine for Phantom.

Calls Claude API with web search to research current market conditions,
discover what strategies are working, and generate new strategy hypotheses
for backtesting and deployment.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from phantom_config import (
    INSTRUMENTS, DISCOVER_MODEL, DISCOVERY_LOG_PATH, API_COSTS_PATH,
    get_logger, send_telegram, save_api_cost, load_json, save_json,
    extract_json,
)

log = get_logger('discover')

MAX_TOKENS = 8192

# Build instrument ticker list from the authoritative INSTRUMENTS config.
# Format: "BTC, ETH, XRP, SOL, LINK" (ticker symbols only, no suffix)
_TICKERS = ', '.join(s.split('/')[0] for s in INSTRUMENTS)
_SYMBOLS = ', '.join(INSTRUMENTS)

SYSTEM_PROMPT = f"""\
You are Phantom, an autonomous self-evolving crypto futures trader. \
You have COMPLETE FREEDOM to design any trading strategy you believe will be profitable.

You trade perpetual futures on Phemex. Your ONLY allowed instruments are: {_TICKERS}.
In strategy JSON, use the full symbol format: {_SYMBOLS}.
Do NOT propose strategies on any other instrument — they will be rejected.

You can go long or short with any leverage up to 100x.

Your job right now is DISCOVERY — generating new strategy hypotheses based on \
current market conditions.

CONTEXT YOU RECEIVE:
- Current prices and recent price action for all instruments
- Your active strategies and their recent performance
- Your full trade history and what's been working/failing

WHAT TO SEARCH FOR:
- Current crypto market narrative (risk-on? risk-off? rotation? accumulation?)
- Which coins are showing relative strength/weakness
- Funding rates (positive = crowded longs, negative = crowded shorts)
- Open interest changes (rising OI + price up = strong trend, \
rising OI + price down = distribution)
- Liquidation levels and clusters
- On-chain data signals (whale movements, exchange flows)
- Macro catalysts (Fed, CPI, geopolitical events)
- Technical patterns forming on multiple timeframes
- What strategies are working for top crypto traders right now

STRATEGY DESIGN PRINCIPLES:
- Every strategy needs a clear edge — why does this work?
- Risk/reward must be defined before entry
- Adapt to current regime — don't use a trend strategy in a range and vice versa
- Diversify across instruments when possible
- Consider correlation — don't be 3x long on BTC, ETH, SOL simultaneously \
(they move together)
- Funding rate harvesting is a valid strategy
- Mean reversion, momentum, breakout, sentiment — all valid
- You can create strategies on any timeframe from 1-minute scalps \
to multi-day swings

BACKTESTING COMPATIBILITY — IMPORTANT:
The backtester evaluates entry conditions mathematically against OHLCV candle data.
Conditions it CAN evaluate: RSI thresholds ("RSI(14) < 30"), EMA relationships \
("EMA9 above EMA21", "price above EMA50"), Bollinger Bands ("close below lower \
Bollinger Band"), volume ("volume above 20-period average"), price levels \
("close above 80000"), candle direction ("bullish candle").
Conditions it SKIPS (not failed, just ignored in backtesting): funding rates, \
open interest, on-chain signals, sentiment, support/resistance "confirmation", \
dominance, liquidation clusters.
Each strategy MUST include at least 2 purely numeric/technical conditions \
(RSI, EMA, SMA, ATR, Bollinger Bands, volume, price levels) so the backtester \
can validate historical edge. Qualitative conditions are fine as supplementary \
context but cannot be the only entry filter.

STRICT OUTPUT RULES — violations will cause the strategy to be discarded:
1. position_size_pct MUST be a single number representing percentage of account \
(e.g., 5 for 5%). Never a string, never a ratio, never a description.
2. Each strategy trades exactly ONE instrument. Pair trades are NOT allowed. \
If a thesis requires two sides, write two separate single-instrument strategies.
3. The "instruments" array must contain exactly ONE symbol from the allowed list.
4. Output valid JSON only — no markdown, no prose before or after the JSON block.

OUTPUT FORMAT (valid JSON only, no markdown):
{{
  "market_assessment": {{
    "regime": "trending/ranging/volatile/compressed",
    "narrative": "2-3 sentence market summary",
    "key_levels": {{
      "BTC": {{"support": 0, "resistance": 0}},
      "ETH": {{"support": 0, "resistance": 0}}
    }},
    "funding_rates": {{"BTC": 0.0, "ETH": 0.0, "SOL": 0.0}},
    "catalysts": ["upcoming event 1", "event 2"]
  }},
  "new_strategies": [
    {{
      "name": "Strategy Name",
      "description": "what it does in 1-2 sentences",
      "instruments": ["BTC/USDT:USDT"],
      "timeframe": "4h",
      "entry_conditions": [
        "condition 1",
        "condition 2"
      ],
      "exit_conditions": {{
        "take_profit": "description",
        "stop_loss": "description",
        "time_stop": "description"
      }},
      "leverage": 5,
      "position_size_pct": 5,
      "edge_explanation": "why this works right now with statistical reasoning",
      "invalidation": "what market conditions would kill this edge",
      "confidence": "low/medium/high",
      "backtest_priority": "low/medium/high"
    }}
  ],
  "retired_strategies": [
    {{
      "name": "strategy name",
      "reason": "why it stopped working"
    }}
  ]
}}"""


def _format_market_context(market_data: dict, active_strategies: list,
                            performance_history: list,
                            norman_context: str | None = None) -> str:
    """Build the user message with all context for Claude."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    parts = [f"CURRENT TIME: {now}", ""]

    if norman_context:
        parts.append(
            "NORMAN'S LATEST WEEKLY REPORT (cross-agent macro/market read — "
            "use as prior context for what's working this week):"
        )
        parts.append(norman_context)
        parts.append("")

    # Market data
    if market_data:
        parts.append("CURRENT MARKET DATA:")
        for symbol, data in market_data.items():
            price    = data.get('last', data.get('close', '?'))
            pct_24h  = data.get('percentage') or data.get('change_pct') or 0
            volume   = data.get('quoteVolume') or data.get('volume') or 0
            parts.append(
                f"  {symbol}: ${price:,.2f}  24h: {pct_24h:+.2f}%  "
                f"Vol: ${volume:,.0f}"
                if isinstance(price, (int, float)) else
                f"  {symbol}: {price}"
            )
        parts.append("")
    else:
        parts.append("MARKET DATA: Not available — search for current prices")
        parts.append("")

    # Active strategies
    if active_strategies:
        parts.append(f"ACTIVE STRATEGIES ({len(active_strategies)}):")
        for s in active_strategies:
            perf = s.get('performance', {})
            parts.append(
                f"  [{s.get('name')}] tf={s.get('timeframe')}  "
                f"instruments={s.get('instruments')}  "
                f"trades={perf.get('trades', 0)}  "
                f"wr={perf.get('win_rate', 0):.0f}%  "
                f"pf={perf.get('profit_factor', 0):.2f}  "
                f"status={s.get('status', 'active')}"
            )
        parts.append("")
    else:
        parts.append("ACTIVE STRATEGIES: None — this is the first discovery run")
        parts.append("")

    # Recent performance
    if performance_history:
        recent = performance_history[-20:]
        wins   = sum(1 for t in recent if t.get('pnl', 0) > 0)
        total  = len(recent)
        pnl    = sum(t.get('pnl', 0) for t in recent)
        parts.append(f"RECENT PERFORMANCE (last {total} trades):")
        parts.append(f"  Win rate: {wins/total*100:.0f}%  Total PnL: ${pnl:+.2f}")
        # Show last 5 trades
        parts.append("  Recent trades:")
        for t in recent[-5:]:
            parts.append(
                f"    [{t.get('strategy_name', '?')}] "
                f"{t.get('symbol', '?')} {t.get('side', '?')} "
                f"PnL: ${t.get('pnl', 0):+.2f}  "
                f"reason: {t.get('close_reason', '?')}"
            )
        parts.append("")
    else:
        parts.append("TRADE HISTORY: Empty — no trades taken yet")
        parts.append("")

    parts.append(
        "Use web_search to research current crypto market conditions, funding rates, "
        "on-chain data, and successful trading strategies. Then output ONLY the JSON "
        "with your market assessment and strategy hypotheses."
    )

    return '\n'.join(parts)


def discover_strategies(
    market_data: dict,
    active_strategies: list,
    performance_history: list,
    norman_context: str | None = None,
) -> dict:
    """
    Call Claude with web search to discover new strategy hypotheses.

    Args:
        market_data:         Dict of symbol → price/volume data (may be empty).
        active_strategies:   List of currently deployed strategy dicts.
        performance_history: List of historical trade dicts.
        norman_context:      Optional JSON-dumped Norman report to use as a
                             prior for what's working this week.

    Returns:
        Dict with market_assessment, new_strategies, retired_strategies, _meta.
    """
    log.info('Discovery starting — %d active strategies, %d trades in history%s',
             len(active_strategies), len(performance_history),
             ' (+Norman context)' if norman_context else '')

    client  = anthropic.Anthropic()
    prompt  = _format_market_context(
        market_data, active_strategies, performance_history,
        norman_context=norman_context,
    )

    print(f'[discover] Calling {DISCOVER_MODEL} with web search...')

    messages = [{'role': 'user', 'content': prompt}]

    response = client.messages.create(
        model=DISCOVER_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
        messages=messages,
    )

    web_searches = sum(
        1 for block in response.content
        if getattr(block, 'type', '') in ('tool_use', 'server_tool_use')
        and 'web_search' in getattr(block, 'name', '')
    ) or sum(
        1 for block in response.content
        if 'web_search' in getattr(block, 'type', '')
    )

    total_input  = response.usage.input_tokens
    total_output = response.usage.output_tokens

    print(f'[discover] Turn 1: {total_input} in + {total_output} out | '
          f'{web_searches} web searches')

    result_text = ''
    for block in response.content:
        if getattr(block, 'type', '') == 'text' and block.text:
            result_text = block.text

    result = extract_json(result_text)

    # Fallback turn if no JSON
    if result is None and result_text:
        print('[discover] No JSON in turn 1 — requesting JSON-only follow-up...')
        response2 = client.messages.create(
            model=DISCOVER_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            messages=messages + [
                {'role': 'assistant', 'content': response.content},
                {'role': 'user', 'content':
                 'Output ONLY the JSON now — no prose, no markdown. '
                 'Start with { and end with }.'},
            ],
        )
        total_input  += response2.usage.input_tokens
        total_output += response2.usage.output_tokens
        for block in response2.content:
            if getattr(block, 'type', '') == 'text' and block.text:
                result_text = block.text
        result = extract_json(result_text)

    cost_usd = save_api_cost('discover', total_input, total_output, web_searches)
    print(f'[discover] Total: {total_input}in + {total_output}out | '
          f'{web_searches} searches | ${cost_usd:.4f}')

    if result is None:
        log.error('Discovery returned no parseable JSON')
        result = {
            'market_assessment': {
                'regime': 'unknown',
                'narrative': 'Discovery failed to return JSON.',
                'key_levels': {}, 'funding_rates': {}, 'catalysts': [],
            },
            'new_strategies': [],
            'retired_strategies': [],
        }

    # Normalise
    result.setdefault('new_strategies', [])
    result.setdefault('retired_strategies', [])
    result.setdefault('market_assessment', {})

    n_strats = len(result['new_strategies'])
    log.info('Discovery complete: %d new strategies | regime=%s | cost=$%.4f',
             n_strats,
             result['market_assessment'].get('regime', '?'),
             cost_usd)

    result['_meta'] = {
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'input_tokens':  total_input,
        'output_tokens': total_output,
        'web_searches':  web_searches,
        'cost_usd':      cost_usd,
        'model':         DISCOVER_MODEL,
    }

    # Save to discovery log
    discovery_log = load_json(DISCOVERY_LOG_PATH, [])
    if not isinstance(discovery_log, list):
        discovery_log = []
    discovery_log.append(result)
    save_json(DISCOVERY_LOG_PATH, discovery_log)

    # Telegram: announce new strategies
    _notify_discovery(result)

    return result


def _notify_discovery(result: dict) -> None:
    strats = result.get('new_strategies', [])
    assess = result.get('market_assessment', {})
    if not strats:
        return

    lines = [
        f"PHANTOM — DISCOVERY COMPLETE",
        f"Regime: {assess.get('regime', '?').upper()}",
        f"{assess.get('narrative', '')}",
        "",
        f"New strategy hypotheses ({len(strats)}):",
    ]
    for s in strats:
        lines.append(
            f"  • {s.get('name')} [{s.get('timeframe')}] "
            f"{s.get('confidence', '?')} confidence — "
            f"{s.get('edge_explanation', '')[:80]}"
        )
    retired = result.get('retired_strategies', [])
    if retired:
        lines.append(f"\nRetired: {', '.join(r.get('name','?') for r in retired)}")

    send_telegram('\n'.join(lines))
