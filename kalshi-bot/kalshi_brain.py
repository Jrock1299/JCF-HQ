"""
kalshi_brain.py — Claude API analysis brain for the Kalshi bot.

Analyzes Kalshi prediction markets across ALL categories using Claude Sonnet 4.6
with web search to identify mispriced contracts and recommend trades.

Usage:
    from kalshi_brain import analyze_markets
    result = analyze_markets(markets_data, recent_trades, bankroll)
    # result = {
    #   "analyzed_count": N,
    #   "recommendations": [{"ticker": ..., "direction": "yes"|"no",
    #                         "limit_price": 38, "position_size_usd": 3.00, ...}],
    #   "skipped_reason": "...",
    #   "_meta": {...}
    # }
"""

import anthropic
import json
import re
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH   = '/root/.openclaw/logs/kalshi_api_costs.json'
MODEL      = 'claude-sonnet-4-6'
MAX_TOKENS = 4096

# Maximum markets to include in the prompt (sort by volume desc, take top N)
MAX_MARKETS_IN_PROMPT = 60

SYSTEM_PROMPT = """\
You are the Kalshi trading brain for JCF HQ. You analyze prediction market \
contracts on Kalshi and identify mispriced opportunities.

You receive a list of active markets with current prices. Your job is to \
determine which contracts are mispriced by comparing the market price to the \
true probability of the event occurring.

MARKET CATEGORIES TO ANALYZE:
- Crypto price markets (BTC, ETH, SOL above/below X)
- Economics (Fed rate decisions, CPI, GDP, unemployment)
- Weather (temperature records, hurricane landfalls)
- Politics (approval ratings, policy decisions)
- Finance (stock price milestones, IPO timing)
- Sports (game outcomes, player performances)

PROCESS:
1. For each market, assess the current yes/no prices
2. Use web search to find relevant information that affects the probability
3. Estimate true probability based on your research
4. If market price diverges from true probability by more than 8%, flag as \
a trade opportunity
5. Determine direction (buy YES or buy NO)
6. Size the position using Kelly criterion capped at 5% of bankroll

RULES:
- Minimum edge required: 8% (market at 40¢, you think true prob is 48%+ or 32%-)
- Maximum position: 5% of bankroll per trade
- Maximum 10 trades per day
- Maximum 3 open positions at once
- Prefer markets closing in 1-24 hours (enough time for edge, not too much \
uncertainty)
- Avoid markets with very thin orderbooks (< $50 depth)
- "No trade" is valid — don't force positions

OUTPUT FORMAT (respond in valid JSON only, no markdown):
{
  "analyzed_count": 15,
  "recommendations": [
    {
      "ticker": "KXBTC-26APR15-T85000",
      "title": "BTC above $85,000 by end of day",
      "current_yes_price": 35,
      "current_no_price": 65,
      "estimated_true_prob": 45,
      "edge_pct": 10,
      "direction": "yes",
      "confidence": "medium",
      "key_factor": "BTC momentum + ETF inflows suggest push toward 85k",
      "position_size_usd": 3.00,
      "limit_price": 38
    }
  ],
  "skipped_reason": "Economics markets all efficiently priced today"
}"""


# ─── Market formatter ──────────────────────────────────────────────────────────

def _format_markets_compact(markets_data: list) -> str:
    """Format market list as compact text grouped by category."""
    if not markets_data:
        return "(no markets provided)"

    # Sort by volume descending, take top N
    def _vol(m):
        try:
            return float(m.get('volume_24h_fp') or m.get('volume_24h') or 0)
        except (TypeError, ValueError):
            return 0.0

    top = sorted(markets_data, key=_vol, reverse=True)[:MAX_MARKETS_IN_PROMPT]

    # Group by category
    by_cat: dict[str, list] = {}
    for m in top:
        cat = (m.get('category') or m.get('event_category') or 'other').lower()
        by_cat.setdefault(cat, []).append(m)

    lines = [f"MARKETS ({len(top)} of {len(markets_data)} total, sorted by 24h volume):"]

    for cat, mlist in sorted(by_cat.items()):
        lines.append(f"\n[{cat.upper()}]")
        for m in mlist:
            ticker   = m.get('ticker', '?')
            title    = (m.get('title') or m.get('subtitle') or '')[:70]
            mins     = m.get('minutes_to_close', 0)
            if mins >= 60:
                time_str = f"{mins/60:.1f}h"
            else:
                time_str = f"{mins:.0f}m"
            bid_raw  = m.get('yes_bid_dollars') or '?'
            ask_raw  = m.get('yes_ask_dollars') or '?'
            try:
                bid_c = round(float(bid_raw) * 100)
                ask_c = round(float(ask_raw) * 100)
                price_str = f"YES {bid_c}¢/{ask_c}¢  NO {100-ask_c}¢/{100-bid_c}¢"
            except (TypeError, ValueError):
                price_str = f"bid={bid_raw} ask={ask_raw}"
            vol = _vol(m)
            vol_str = f"${vol:,.0f}" if vol > 0 else "?"
            lines.append(
                f"  {ticker}  |  {title}  |  closes {time_str}  |  "
                f"{price_str}  |  vol {vol_str}"
            )

    return '\n'.join(lines)


# ─── Cost tracking ─────────────────────────────────────────────────────────────

def _load_costs() -> list:
    try:
        with open(LOG_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _save_cost(input_tokens: int, output_tokens: int, web_searches: int) -> float:
    """Append run cost to kalshi_api_costs.json and return cost_usd."""
    cost_usd = round(
        (input_tokens  * 3  / 1_000_000) +
        (output_tokens * 15 / 1_000_000),
        6,
    )
    entry = {
        "date":          datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "web_searches":  web_searches,
        "cost_usd":      cost_usd,
    }
    costs = _load_costs()
    costs.append(entry)
    try:
        Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, 'w') as f:
            json.dump(costs, f, indent=2)
    except Exception as e:
        print(f'[brain] cost log write error: {e}')
    return cost_usd


# ─── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    """
    Try multiple strategies to extract a JSON object from Claude's response text.
    Handles: raw JSON, markdown code blocks, or JSON embedded in prose.
    """
    if not text or not text.strip():
        return None

    # Strategy 1: direct parse
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Strategy 2: markdown ```json``` or ``` block
    code_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 3: find the last top-level {...} block
    brace_depth   = 0
    json_start    = -1
    last_complete = None
    for i, ch in enumerate(text):
        if ch == '{':
            if brace_depth == 0:
                json_start = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and json_start != -1:
                candidate = text[json_start:i + 1]
                try:
                    last_complete = json.loads(candidate)
                except json.JSONDecodeError:
                    pass

    return last_complete


# ─── Main analysis function ────────────────────────────────────────────────────

def analyze_markets(markets_data: list, recent_trades: list, bankroll: float) -> dict:
    """
    Analyze Kalshi markets using Claude with web search.

    Args:
        markets_data:   List of market dicts from Kalshi API (all categories).
                        Each should have: ticker, title, category, close_time,
                        minutes_to_close, yes_bid_dollars, yes_ask_dollars, volume_24h_fp.
        recent_trades:  Recent trade history for context (may be empty list).
        bankroll:       Current Kalshi balance in dollars.

    Returns:
        Dict with keys: analyzed_count, recommendations, skipped_reason, _meta.
    """
    client = anthropic.Anthropic()
    today  = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    markets_text = _format_markets_compact(markets_data)

    user_message = (
        f"Time: {today} | Bankroll: ${bankroll:.2f}\n\n"
        f"{markets_text}\n\n"
        "Use web_search to research current prices, news, and data for the most "
        "promising markets above. Focus on markets where you can form a strong "
        "probability estimate. After researching, output ONLY valid JSON — "
        "no markdown, no prose outside the JSON object."
    )

    print(f'[kalshi_brain] Calling {MODEL} — {len(markets_data)} markets, '
          f'bankroll ${bankroll:.2f}...')

    messages = [{"role": "user", "content": user_message}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=messages,
    )

    # Count web search calls
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

    print(f'[kalshi_brain] Turn 1 — {total_input} in + {total_output} out | '
          f'{web_searches} web searches')

    # Extract text from first response
    result_text = ''
    for block in response.content:
        if getattr(block, 'type', '') == 'text' and block.text:
            result_text = block.text

    result = _extract_json(result_text)

    # ── Fallback turn if no JSON ───────────────────────────────────────────────
    if result is None and result_text:
        print('[kalshi_brain] No JSON in turn 1 — requesting JSON-only follow-up...')

        turn1_content = response.content
        follow_up_messages = messages + [
            {"role": "assistant", "content": turn1_content},
            {
                "role": "user",
                "content": (
                    "Your research is complete. Now output ONLY the final JSON object "
                    "with your recommendations — no prose, no markdown, no explanation. "
                    "Start your response with { and end with }."
                ),
            },
        ]

        response2 = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=follow_up_messages,
        )

        total_input  += response2.usage.input_tokens
        total_output += response2.usage.output_tokens

        result_text2 = ''
        for block in response2.content:
            if getattr(block, 'type', '') == 'text' and block.text:
                result_text2 = block.text

        print(f'[kalshi_brain] Turn 2 — {response2.usage.input_tokens} in + '
              f'{response2.usage.output_tokens} out')

        result = _extract_json(result_text2)
        if result is None:
            print(f'[kalshi_brain] Turn 2 snippet:\n{result_text2[:400]}')

    # ── Cost tracking ──────────────────────────────────────────────────────────
    cost_usd = _save_cost(total_input, total_output, web_searches)

    print(f'[kalshi_brain] Total — {total_input} in + {total_output} out | '
          f'{web_searches} web searches | ${cost_usd:.4f}')

    if result is None:
        print('[kalshi_brain] No valid JSON after 2 turns — returning empty result')
        result = {
            "analyzed_count": len(markets_data),
            "recommendations": [],
            "skipped_reason":  "Brain returned no parseable JSON.",
        }

    # Normalise: ensure recommendations is a list
    if "recommendations" not in result:
        result["recommendations"] = []

    recs_n = len(result.get("recommendations", []))
    print(f'[kalshi_brain] {recs_n} recommendation(s) | '
          f'{result.get("skipped_reason", "")[:80]}')

    result["_meta"] = {
        "input_tokens":    total_input,
        "output_tokens":   total_output,
        "web_searches":    web_searches,
        "cost_usd":        cost_usd,
        "model":           MODEL,
        "markets_analyzed": len(markets_data),
        "called_at":       datetime.now(timezone.utc).isoformat(),
    }

    return result
