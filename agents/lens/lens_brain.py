#!/usr/bin/env python3
"""
lens_brain.py — Claude API macro analyst for Lens.

Calls Claude Sonnet 4.6 with web_search to analyze macro markets,
search current news for each asset, check sentiment/earnings/insider data,
and produce a structured market_bias.json + Telegram report.

Usage:
    python3 lens_brain.py
    # Writes /root/.openclaw/dashboard/market_bias.json
    # Sends Telegram report to TELEGRAM_ALERT_CHAT_ID
"""

import anthropic
import json
import os
import re
import requests
from datetime import datetime, timezone
import sys
sys.path.insert(0, "/root/.openclaw/scripts")
from telegram_personalities import wrap_message
from pathlib import Path

LOG_PATH         = '/root/.openclaw/logs/lens_api_costs.json'
MARKET_BIAS_PATH = Path('/root/.openclaw/dashboard/market_bias.json')
SENTINEL_PATH    = Path('/root/.openclaw/dashboard/sentinel_data.json')
TRADES_PATH      = Path('/root/.openclaw/dashboard/agent_trades.json')

MODEL      = 'claude-sonnet-4-6'
MAX_TOKENS = 8192

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')

PAIRS = ['BTC/USDT', 'XAU/USD', 'US100', 'SPX500', 'US OIL']

SYSTEM_PROMPT = """You are Lens, an elite macro market analyst for JCF HQ. \
Your job is to provide accurate, research-backed directional bias for key \
trading pairs every morning.

PAIRS COVERED: BTC/USDT, XAU/USD (Gold), US100 (Nasdaq), SPX500, US OIL (WTI Crude)

PROCESS:
1. Use web search to find the latest news and analysis for each pair:
   - "BTC Bitcoin market analysis today"
   - "Gold XAU market outlook today"
   - "US100 Nasdaq market analysis today"
   - "SPX500 S&P 500 market analysis today"
   - "WTI crude oil price market analysis today"
2. Review the context data provided: previous bias, recent trades, sentinel signals
3. For each pair assign:
   - bias: bullish / bearish / neutral
   - confidence: 0-100 (be honest, never inflate)
   - note: 2-3 sentences grounded in what you found
4. Generate all fields in the output schema (pairs, market_impact, \
watchlist_calculations, discovery_calculations, consensus_top3, \
earnings_calculations)
5. Write a 1-3 sentence summary and a 3-5 sentence morning_report
6. Write numbered priorities (5 items) as HTML-style "<br>" separated string

CONFIDENCE GUIDELINES:
- 75%+: Strong conviction, clear directional signals across news + price
- 50-74%: Moderate conviction, mixed signals
- Below 50%: Use neutral bias, flag conflicting data in note

OUTPUT FORMAT (respond in valid JSON only, no markdown):
{
  "last_updated": "<ISO timestamp UTC>",
  "summary": "<1-3 sentence top-level macro summary>",
  "morning_report": "<3-5 sentence morning briefing, more detailed>",
  "priorities": "1. ...<br>2. ...<br>3. ...<br>4. ...<br>5. ...",
  "pairs": [
    {"symbol": "BTC/USDT", "bias": "bullish", "confidence": 72, "note": "..."},
    {"symbol": "XAU/USD",  "bias": "bullish", "confidence": 68, "note": "..."},
    {"symbol": "US100",    "bias": "neutral",  "confidence": 54, "note": "..."},
    {"symbol": "SPX500",   "bias": "bullish",  "confidence": 60, "note": "..."},
    {"symbol": "US OIL",   "bias": "bearish",  "confidence": 65, "note": "..."}
  ],
  "forex_news": [
    {"headline": "...", "source": "Reuters", "time": "recent", "impact": "high"}
  ],
  "markets_feed": [
    {"headline": "S&P 500 closes at record high on tech strength", "source": "Bloomberg", "time": "2h ago", "impact": "high"},
    {"headline": "...", "source": "...", "time": "...", "impact": "medium"}
  ],
  "crypto_feed": [
    {"headline": "BTC breaks above $XXk on ETF inflows", "source": "CoinDesk", "time": "1h ago", "impact": "high"},
    {"headline": "...", "source": "...", "time": "...", "impact": "medium"}
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
      "beat_scenario": "what happens if earnings beat",
      "miss_scenario": "what happens if earnings miss"
    }
  }
}"""


# ─── Context loaders ───────────────────────────────────────────────────────────

def _load_json_file(path: Path, label: str) -> dict | list | None:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f'[lens_brain] Warning: could not load {label}: {e}')
        return None


def _format_sentinel_compact(sentinel: dict) -> str:
    """Format sentinel_data.json into compact text for the prompt."""
    lines = []

    ws = sentinel.get('watchlist_signals', [])
    if ws:
        lines.append(f'WATCHLIST SIGNALS ({len(ws)} tickers):')
        for s in ws[:8]:
            lines.append(
                f"  {s['symbol']} | {s.get('signal_type','?')} | "
                f"buys:{s.get('buy_count',0)} sells:{s.get('sell_count',0)} | "
                f"${s.get('total_buy_value',0)/1e6:.1f}M bought"
            )

    td = sentinel.get('top_discoveries', [])
    if td:
        lines.append(f'TOP DISCOVERIES ({len(td)}):')
        for d in td[:5]:
            lines.append(
                f"  {d['symbol']} | {d.get('signal_type','?')} | "
                f"score:{d.get('score',0)} | ${d.get('total_value',0)/1e6:.1f}M"
            )

    ar = sentinel.get('analyst_recommendations', [])
    if ar:
        lines.append(f'ANALYST RECS ({len(ar)} tickers):')
        for r in ar[:8]:
            total = (r.get('buy', 0) + r.get('strongBuy', 0) +
                     r.get('hold', 0) + r.get('sell', 0) + r.get('strongSell', 0))
            bull = r.get('buy', 0) + r.get('strongBuy', 0)
            pct  = round(bull / total * 100) if total else 0
            lines.append(f"  {r['symbol']}: {pct}% bullish ({bull}/{total})")

    ec = sentinel.get('earnings_calendar', [])
    if ec:
        lines.append(f'EARNINGS NEXT 7 DAYS ({len(ec)} reports):')
        for e in ec[:10]:
            lines.append(
                f"  {e['symbol']} | {e.get('date','?')} | "
                f"EPS est:{e.get('epsEstimate','?')}"
            )

    return '\n'.join(lines) if lines else '(no sentinel data)'


def _format_recent_trades(trades_data: dict) -> str:
    """Format last 10 agent trades compactly."""
    trades = trades_data.get('trades', []) if isinstance(trades_data, dict) else []
    recent = trades[-10:] if len(trades) > 10 else trades
    if not recent:
        return '(no recent trades)'
    lines = []
    for t in recent:
        sym    = t.get('symbol', '?')
        dir_   = t.get('direction', t.get('side', '?'))
        result = t.get('result', t.get('pnl', '?'))
        date   = str(t.get('date', t.get('timestamp', '')))[:10]
        lines.append(f"  {date} {sym} {dir_} → {result}")
    return '\n'.join(lines)


# ─── Cost tracking ─────────────────────────────────────────────────────────────

def _load_costs() -> list:
    try:
        with open(LOG_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _save_cost(input_tokens: int, output_tokens: int, web_searches: int) -> float:
    """Append run cost to lens_api_costs.json and return cost_usd."""
    cost_usd = round(
        (input_tokens  * 3  / 1_000_000) +
        (output_tokens * 15 / 1_000_000),
        6,
    )
    entry = {
        'date':          datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'web_searches':  web_searches,
        'cost_usd':      cost_usd,
    }
    costs = _load_costs()
    costs.append(entry)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    try:
        with open(LOG_PATH, 'w') as f:
            json.dump(costs, f, indent=2)
    except Exception as e:
        print(f'[lens_brain] cost log write error: {e}')
    return cost_usd


# ─── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    """
    Try multiple strategies to extract a JSON object from Claude's response.
    Handles: raw JSON, markdown code blocks, JSON embedded in prose.
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

    # Strategy 3: character-walking brace depth tracker (last complete {...})
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


# ─── Telegram ──────────────────────────────────────────────────────────────────

def _send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print('[lens_brain] Telegram not configured — skipping send')
        return
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': text},
            timeout=15,
        )
        if not resp.ok:
            print(f'[lens_brain] Telegram error {resp.status_code}: {resp.text[:200]}')
        else:
            print('[lens_brain] Telegram report sent')
    except Exception as e:
        print(f'[lens_brain] Telegram exception: {e}')


def _build_telegram_report(result: dict) -> str:
    """Format market_bias data as Lens Telegram report."""
    now  = datetime.now(timezone.utc)
    time_str = now.strftime('%H:%M')
    date_str = now.strftime('%Y-%m-%d')

    lines = [f'🧠 LENS — MACRO DESK', f'🕐 {time_str} UTC | {date_str}', '']

    bias_icons = {
        'bullish': '📈',
        'bearish': '📉',
        'neutral': '⚖️',
    }

    for pair in result.get('pairs', []):
        symbol     = pair.get('symbol', '')
        bias       = pair.get('bias', 'neutral').lower()
        confidence = pair.get('confidence', 0)
        note       = pair.get('note', '')
        icon       = bias_icons.get(bias, '⚖️')
        lines.append(f'{icon} {symbol} {bias.capitalize()} {confidence}%')
        if note:
            lines.append(note)
        lines.append('')

    summary = result.get('summary', '')
    if summary:
        lines.append('')
        lines.append(summary)

    body = '\n'.join(lines).rstrip()
    return wrap_message('lens', body)


# ─── Main analysis function ────────────────────────────────────────────────────

def analyze_markets() -> dict:
    """
    Analyze today's macro markets using Claude with web search.

    Returns:
        Dict matching the market_bias.json schema, with _meta attached.
        Also writes market_bias.json and sends Telegram report.
    """
    client = anthropic.Anthropic()
    today  = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    now_ts = datetime.now(timezone.utc).isoformat()

    # Load context files
    prev_bias = _load_json_file(MARKET_BIAS_PATH, 'market_bias.json')
    sentinel  = _load_json_file(SENTINEL_PATH, 'sentinel_data.json')
    trades    = _load_json_file(TRADES_PATH, 'agent_trades.json')

    # Format context compactly
    prev_summary = (
        f"Previous bias ({prev_bias.get('last_updated','?')[:10]}): "
        f"{prev_bias.get('summary','')}"
        if prev_bias else '(no previous bias available)'
    )

    sentinel_text = (
        _format_sentinel_compact(sentinel) if sentinel
        else '(sentinel_data.json not available)'
    )

    trades_text = (
        _format_recent_trades(trades) if trades
        else '(agent_trades.json not available)'
    )

    user_message = (
        f"Today: {today}\n\n"
        f"PREVIOUS BIAS:\n{prev_summary}\n\n"
        f"SENTINEL DATA:\n{sentinel_text}\n\n"
        f"RECENT AGENT TRADES:\n{trades_text}\n\n"
        "Use web_search to get the latest news and price action for each pair "
        "(BTC/USDT, XAU/USD, US100, SPX500, US OIL). "
        "After researching, output ONLY valid JSON — no markdown, no prose outside "
        "the JSON object. The JSON must include: last_updated, summary, "
        "morning_report, priorities, pairs, forex_news, markets_feed, "
        "crypto_feed, market_impact, watchlist_calculations, "
        "discovery_calculations, consensus_top3, earnings_calculations. "
        "markets_feed: 5-8 recent US equity/macro news items with short headlines "
        "and timestamps. crypto_feed: 5-8 recent crypto news items (BTC, ETH, "
        "ETFs, on-chain, regulation) with short headlines and timestamps. "
        "IMPORTANT: For earnings_calculations include only the 5 most notable upcoming "
        "earnings (highest market cap or most market-moving). Do not include all 50."
    )

    print(f'[lens_brain] Calling {MODEL} — macro analysis for {today}...')

    messages = [{'role': 'user', 'content': user_message}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
        messages=messages,
    )

    # Count web search invocations
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

    print(
        f'[lens_brain] Turn 1 — {total_input} in + {total_output} out | '
        f'{web_searches} web searches'
    )

    # Extract last text block
    result_text = ''
    for block in response.content:
        if getattr(block, 'type', '') == 'text' and block.text:
            result_text = block.text

    result = _extract_json(result_text)

    # Fallback turn if no JSON in turn 1
    if result is None and result_text:
        print('[lens_brain] No JSON in turn 1 — requesting JSON-only follow-up...')

        turn1_content = response.content
        follow_up_messages = messages + [
            {'role': 'assistant', 'content': turn1_content},
            {
                'role': 'user',
                'content': (
                    'Your analysis is complete. Now output ONLY the final JSON object '
                    'with the full market_bias structure — no prose, no markdown, '
                    'no explanation. Start your response with { and end with }.'
                ),
            },
        ]

        response2 = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            messages=follow_up_messages,
        )

        total_input  += response2.usage.input_tokens
        total_output += response2.usage.output_tokens

        result_text2 = ''
        for block in response2.content:
            if getattr(block, 'type', '') == 'text' and block.text:
                result_text2 = block.text

        print(
            f'[lens_brain] Turn 2 — {response2.usage.input_tokens} in + '
            f'{response2.usage.output_tokens} out'
        )

        result = _extract_json(result_text2)
        if result is None:
            print(f'[lens_brain] Turn 2 snippet:\n{result_text2[:400]}')

    # Cost tracking
    cost_usd = _save_cost(total_input, total_output, web_searches)

    print(
        f'[lens_brain] Total — {total_input} in + {total_output} out | '
        f'{web_searches} web searches | ${cost_usd:.4f}'
    )

    if result is None:
        print('[lens_brain] No valid JSON after 2 turns — returning minimal result')
        result = {
            'last_updated': now_ts,
            'summary':      'Lens Brain returned no parseable JSON today.',
            'morning_report': '',
            'priorities':   '',
            'pairs':        [],
            'forex_news':   [],
            'markets_feed': [],
            'crypto_feed':  [],
            'market_impact': [],
            'watchlist_calculations': {},
            'discovery_calculations': {},
            'consensus_top3': [],
            'earnings_calculations': {},
        }
    else:
        # Ensure last_updated is set
        result['last_updated'] = now_ts

    # Write market_bias.json (crypto_context added by lens_crypto_enrichment.py)
    try:
        with open(MARKET_BIAS_PATH, 'w') as f:
            json.dump(result, f, indent=2)
        print(f'[lens_brain] market_bias.json written ({len(result.get("pairs", []))} pairs)')
    except Exception as e:
        print(f'[lens_brain] Error writing market_bias.json: {e}')

    # Send Telegram report
    tg_report = _build_telegram_report(result)
    _send_telegram(tg_report)

    # Attach metadata (not written to market_bias.json, only in return value)
    result['_meta'] = {
        'input_tokens':  total_input,
        'output_tokens': total_output,
        'web_searches':  web_searches,
        'cost_usd':      cost_usd,
        'model':         MODEL,
        'date':          today,
    }

    pairs_n = len(result.get('pairs', []))
    print(f'[lens_brain] Result: {pairs_n} pairs | {result.get("summary", "")[:120]}')

    return result


# ─── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    analyze_markets()
