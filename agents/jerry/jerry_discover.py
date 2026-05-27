"""
jerry_discover.py — Morning opportunity discovery engine for Jerry.

Runs at 13:00 UTC (9 AM ET) before market open.
Calls Claude with web search to find stocks and options plays for the day.
Reads Sentinel insider data as a primary signal source.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from jerry_config import (
    DISCOVER_MODEL, SENTINEL_DATA, WATCHLIST_PATH, API_COSTS_PATH,
    get_logger, send_telegram, save_api_cost, load_json, save_json,
    extract_json,
)

log = get_logger('discover')

MAX_TOKENS = 8192

SYSTEM_PROMPT = """\
You are Jerry, an autonomous stock and options trader for JCF HQ. \
You trade US equities and options on Alpaca with a $100K paper account.

You have full autonomy — choose any stocks, any strategy, any position size. \
Your goal is to generate consistent returns through intelligent stock picking \
and options strategies.

DATA YOU RECEIVE:
- Sentinel insider signals (insider buys/sells with scores)
- Your current portfolio and open positions
- Your trade history and recent performance
- Market hours: 9:30 AM - 4:00 PM ET (13:30-20:00 UTC)

STRATEGIES YOU CAN USE:

Stocks:
- Momentum: buy stocks breaking out on high volume
- Value: buy undervalued stocks with insider buying
- Swing: hold 2-10 days based on technical setups
- Day trade: intraday entries with defined risk
- Short: short overextended or deteriorating stocks
- Sentinel-driven: buy when 3+ insiders are buying

Options:
- Long calls/puts: directional bets with defined risk
- Covered calls: sell calls against stock positions for income
- Cash-secured puts: sell puts to get paid to wait for entries
- Vertical spreads: defined risk directional plays
- Iron condors: range-bound income strategies
- Earnings plays: straddles/strangles before announcements

EDGE SOURCES:
- Sentinel insider data (congressional trades, insider buys > $100K)
- Earnings calendar and estimates
- Sector rotation and relative strength
- Options unusual activity
- Technical analysis across timeframes
- Current macro environment

RISK MANAGEMENT:
- You decide position sizing (use position_size_pct, max 15% per position)
- You decide stop loss levels
- Only hard rule: if account drops below $25K, pause all trading
- Be smart about correlation — don't load up on 5 tech stocks simultaneously
- Prefer high-confidence, asymmetric setups

IMPORTANT — OPTIONS SYMBOL FORMAT:
When suggesting options plays, include the OCC symbol components:
- underlying: "SPY"
- option_type: "call" or "put"
- strike: 560 (number)
- expiry: "2026-05-16" (YYYY-MM-DD)
Jerry will construct the OCC symbol from these components.

OUTPUT FORMAT (valid JSON only, no markdown, no prose):
{
  "market_outlook": "2-3 sentence assessment of today's market environment",
  "watchlist": [
    {
      "symbol": "NVDA",
      "action": "buy",
      "type": "stock",
      "entry_zone": "850-860",
      "thesis": "Insider cluster buy + AI spending cycle acceleration",
      "position_size_pct": 5,
      "stop_loss": "825",
      "target": "920",
      "timeframe": "swing (5-10 days)",
      "confidence": "high",
      "sentinel_signal": true,
      "sentinel_score": 25
    },
    {
      "symbol": "SPY",
      "action": "sell_put",
      "type": "option",
      "underlying": "SPY",
      "option_type": "put",
      "strike": 560,
      "expiry": "2026-05-16",
      "entry_zone": "3.00-4.00",
      "premium_target": "3.50",
      "thesis": "Collect premium at key support — SPY held 560 as floor twice",
      "position_size_pct": 3,
      "max_risk": 56000,
      "confidence": "medium",
      "sentinel_signal": false,
      "sentinel_score": 0
    }
  ],
  "avoid": [
    "UUUU — heavy insider selling, 3 insider sells last 30 days",
    "Small caps in energy sector — macro headwinds from Iran uncertainty"
  ]
}"""


def _format_context(portfolio: dict, sentinel_data: dict,
                    performance_history: list) -> str:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    parts = [f"CURRENT TIME: {now}", ""]

    # ── Sentinel insider signals ──────────────────────────────────────────────
    parts.append("SENTINEL INSIDER DATA:")
    buys = sentinel_data.get('watchlist_buys', [])
    sells = sentinel_data.get('watchlist_sells', [])
    discoveries = sentinel_data.get('top_discoveries', [])

    if buys:
        parts.append(f"  STRONG BUY SIGNALS ({len(buys)}):")
        for b in buys[:5]:
            insiders = b.get('insiders', [])
            insider_names = [i.get('name', '?') for i in insiders[:3]]
            parts.append(
                f"    {b.get('symbol')} | score={b.get('score')} | "
                f"buys={b.get('buy_count')} | "
                f"value=${b.get('total_buy_value', 0):,.0f} | "
                f"type={b.get('signal_type')} | "
                f"insiders: {', '.join(insider_names)}"
            )

    if discoveries:
        parts.append(f"  FRESH DISCOVERIES (last 48h):")
        for d in discoveries[:5]:
            parts.append(
                f"    {d.get('symbol')} | ${d.get('total_value', 0):,.0f} | "
                f"date={d.get('latest_date')}"
            )

    if sells:
        parts.append(f"  SELL SIGNALS (avoid these):")
        for s in sells[:5]:
            parts.append(
                f"    {s.get('symbol')} | sells={s.get('sell_count')} | "
                f"sold=${s.get('total_sell_value', 0):,.0f}"
            )

    # Earnings calendar
    earnings = sentinel_data.get('earnings_calendar', [])
    if earnings:
        parts.append(f"\n  UPCOMING EARNINGS ({len(earnings)} events):")
        for e in earnings[:8]:
            date_str = e.get('date', '')
            parts.append(
                f"    {e.get('symbol')} | {date_str} | "
                f"hour={e.get('hour','?')} | "
                f"eps_est={e.get('epsEstimate','?')}"
            )

    # Market news headlines
    news = sentinel_data.get('market_news', [])
    if news:
        parts.append(f"\n  MARKET NEWS:")
        for n in news[:5]:
            parts.append(f"    • {n.get('headline', '')[:100]}")

    # Daily digest
    digest = sentinel_data.get('daily_digest', '')
    if digest:
        parts.append(f"\n  DAILY DIGEST: {digest}")

    parts.append("")

    # ── Portfolio ──────────────────────────────────────────────────────────────
    account = portfolio.get('account', {})
    positions = portfolio.get('positions', [])
    balance = float(account.get('portfolio_value', 100000))
    buying_power = float(account.get('buying_power', 200000))
    cash = float(account.get('cash', 100000))

    parts.append("CURRENT PORTFOLIO:")
    parts.append(f"  Balance: ${balance:,.2f}  Cash: ${cash:,.2f}  "
                 f"Buying power: ${buying_power:,.2f}")

    if positions:
        parts.append(f"  Open positions ({len(positions)}):")
        for p in positions:
            parts.append(
                f"    {p.get('symbol')} | qty={p.get('qty')} | "
                f"avg_entry=${p.get('avg_entry_price', '?')} | "
                f"current=${p.get('current_price', '?')} | "
                f"P&L=${p.get('unrealized_pl', '?')}"
            )
    else:
        parts.append("  No open positions")
    parts.append("")

    # ── Performance ───────────────────────────────────────────────────────────
    if performance_history:
        recent = performance_history[-20:]
        wins = sum(1 for t in recent if float(t.get('pnl', 0)) > 0)
        total = len(recent)
        pnl = sum(float(t.get('pnl', 0)) for t in recent)
        parts.append(f"RECENT PERFORMANCE (last {total} trades):")
        parts.append(f"  Win rate: {wins/total*100:.0f}%  Total PnL: ${pnl:+.2f}")
        parts.append("  Last 5 trades:")
        for t in recent[-5:]:
            parts.append(
                f"    {t.get('symbol','?')} {t.get('action','?')} "
                f"PnL: ${float(t.get('pnl',0)):+.2f}  "
                f"thesis: {t.get('thesis','?')[:60]}"
            )
    else:
        parts.append("TRADE HISTORY: Empty — this is Jerry's first day")
    parts.append("")

    parts.append(
        "Use web_search to research: today's pre-market movers, sector rotation, "
        "earnings plays, options unusual activity, and macro catalysts. "
        "Cross-reference with the Sentinel insider data above. "
        "Output ONLY the JSON watchlist — no prose, no markdown."
    )

    return '\n'.join(parts)


def discover_opportunities(portfolio: dict, sentinel_data: dict,
                           performance_history: list) -> dict:
    """
    Call Claude with web search to generate today's trading watchlist.

    Returns dict with market_outlook, watchlist, avoid, _meta.
    """
    log.info('Discovery starting — %d open positions, %d trades in history',
             len(portfolio.get('positions', [])), len(performance_history))

    client = anthropic.Anthropic()
    prompt = _format_context(portfolio, sentinel_data, performance_history)

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

    print(f'[discover] Turn 1: {total_input}in + {total_output}out | '
          f'{web_searches} web searches')

    result_text = ''
    for block in response.content:
        if getattr(block, 'type', '') == 'text' and block.text:
            result_text = block.text

    result = extract_json(result_text)

    # Fallback: request JSON-only follow-up if needed
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
            'market_outlook': 'Discovery failed — no JSON returned.',
            'watchlist': [],
            'avoid': [],
        }

    result.setdefault('watchlist', [])
    result.setdefault('avoid', [])
    result.setdefault('market_outlook', '')

    n_plays = len(result['watchlist'])
    log.info('Discovery complete: %d plays | cost=$%.4f', n_plays, cost_usd)

    result['_meta'] = {
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'input_tokens':  total_input,
        'output_tokens': total_output,
        'web_searches':  web_searches,
        'cost_usd':      cost_usd,
        'model':         DISCOVER_MODEL,
    }

    # Persist watchlist
    save_json(WATCHLIST_PATH, result)

    # Telegram notification
    _notify_discovery(result)

    return result


def _notify_discovery(result: dict) -> None:
    watchlist = result.get('watchlist', [])
    outlook   = result.get('market_outlook', '')
    meta      = result.get('_meta', {})
    date_str  = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    if not watchlist and not outlook:
        return

    # Count sentinel signals
    sentinel_count = sum(1 for w in watchlist if w.get('sentinel_signal'))

    lines = [
        f"🤵 JERRY — MORNING SCAN | {date_str}",
        f"Market outlook: {outlook}",
        f"Watchlist: {len(watchlist)} opportunities",
    ]

    for item in watchlist[:8]:
        sym    = item.get('symbol', '?')
        action = item.get('action', '?').upper()
        typ    = item.get('type', 'stock')
        conf   = item.get('confidence', '?')
        sentinel = " [SENTINEL]" if item.get('sentinel_signal') else ""

        if typ == 'stock':
            entry = item.get('entry_zone', '?')
            lines.append(f"  📈 {sym} — {action} ${entry} ({conf}){sentinel}")
        else:
            strike  = item.get('strike', '?')
            expiry  = item.get('expiry', '?')
            premium = item.get('premium_target', '?')
            lines.append(f"  📊 {sym} — {action} ${strike} {expiry} (~${premium} prem) ({conf}){sentinel}")

    if sentinel_count:
        lines.append(f"Sentinel signals integrated: {sentinel_count} insider buys")

    cost = meta.get('cost_usd', 0)
    lines.append(f"API cost: ${cost:.4f}")

    from jerry_config import send_telegram
    send_telegram('\n'.join(lines))
