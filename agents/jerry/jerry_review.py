"""
jerry_review.py — End-of-day performance review for Jerry.

Runs at 20:30 UTC (4:30 PM ET) after market close.
Calls Claude to analyze today's trades, review open positions,
and generate insights for tomorrow's discovery.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from jerry_config import (
    REVIEW_MODEL, TRADE_HISTORY_PATH, PERFORMANCE_PATH, WATCHLIST_PATH,
    get_logger, send_telegram, save_api_cost, load_json, save_json,
    extract_json, _run_codex,
)

log = get_logger('review')

MAX_TOKENS = 4096

SYSTEM_PROMPT = """\
You are Jerry, reviewing your own trading day as an autonomous stock and \
options trader for JCF HQ.

Be honest and analytical. The goal is continuous improvement.

FRAMEWORK:
- What worked today and why?
- What failed and why?
- Are open positions still valid? Should any be closed/adjusted?
- Is the current portfolio too concentrated?
- What should change in tomorrow's approach?
- Score each active strategy: STRONG / WORKING / MARGINAL / KILL IT

OUTPUT FORMAT (valid JSON only, no markdown):
{
  "date": "YYYY-MM-DD",
  "trades_today": 0,
  "pnl_today": 0.0,
  "wins": 0,
  "losses": 0,
  "assessment": "2-3 sentence honest assessment of the day",
  "open_positions_review": [
    {
      "symbol": "NVDA",
      "action": "hold",
      "reason": "thesis still intact, up 2.1%",
      "adjust_sl": null
    }
  ],
  "strategy_scores": [
    {
      "name": "Insider Momentum",
      "score": "WORKING",
      "notes": "2/3 insider plays up"
    }
  ],
  "insights_for_tomorrow": [
    "AAPL earnings after close — consider vol play",
    "Sector rotation into energy continuing — scan XLE components"
  ],
  "risk_assessment": {
    "concentration": "low/medium/high",
    "max_correlated_exposure": "30% in tech",
    "overall_risk": "acceptable/elevated/danger"
  }
}"""


def _build_review_prompt(trade_history: list, portfolio: dict) -> str:
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    parts = [f"EOD REVIEW — {today_str}", ""]

    # Today's trades
    # (guard against explicit None values — `.get(k, '')` returns None, not '',
    #  when the key is present but null; pre-existing bug surfaced 2026-07-24)
    today_trades = [
        t for t in trade_history
        if (t.get('opened_at') or '').startswith(today_str) or
           (t.get('closed_at') or '').startswith(today_str)
    ]

    parts.append(f"TODAY'S TRADES ({len(today_trades)}):")
    if today_trades:
        for t in today_trades:
            pnl    = float(t.get('pnl', 0))
            status = t.get('status', 'open')
            parts.append(
                f"  {t.get('symbol','?')} {t.get('action','?').upper()} "
                f"x{t.get('qty',0)} @ ${t.get('price',0):.2f} | "
                f"PnL: ${pnl:+.2f} | status={status} | "
                f"reason={t.get('close_reason','open')}"
            )
    else:
        parts.append("  No trades today")
    parts.append("")

    # Open positions
    positions = portfolio.get('positions', [])
    parts.append(f"OPEN POSITIONS ({len(positions)}):")
    for p in positions:
        parts.append(
            f"  {p.get('symbol')} | qty={p.get('qty')} | "
            f"entry=${p.get('avg_entry_price','?')} | "
            f"current=${p.get('current_price','?')} | "
            f"P&L=${p.get('unrealized_pl','?')}"
        )
    if not positions:
        parts.append("  No open positions")
    parts.append("")

    # Account summary
    account = portfolio.get('account', {})
    parts.append("ACCOUNT SUMMARY:")
    parts.append(
        f"  Portfolio value: ${float(account.get('portfolio_value', 0)):,.2f}  "
        f"Cash: ${float(account.get('cash', 0)):,.2f}"
    )
    parts.append("")

    # Last 10 closed trades for performance context
    closed = [t for t in trade_history if t.get('status') == 'closed']
    if closed:
        recent = closed[-10:]
        wins   = sum(1 for t in recent if float(t.get('pnl', 0)) > 0)
        total_pnl = sum(float(t.get('pnl', 0)) for t in recent)
        parts.append(f"RECENT HISTORY (last {len(recent)} closed trades):")
        parts.append(f"  Win rate: {wins/len(recent)*100:.0f}%  Total PnL: ${total_pnl:+.2f}")
        for t in recent[-5:]:
            parts.append(
                f"  {t.get('symbol','?')} {t.get('action','?')} "
                f"PnL=${float(t.get('pnl',0)):+.2f} "
                f"({t.get('close_reason','?')}) — "
                f"{t.get('thesis','')[:60]}"
            )
    else:
        parts.append("TRADE HISTORY: No closed trades yet")
    parts.append("")

    # Active watchlist strategies
    watchlist_data = load_json(WATCHLIST_PATH, {})
    wl = watchlist_data.get('watchlist', [])
    if wl:
        parts.append(f"ACTIVE WATCHLIST ({len(wl)} plays):")
        for item in wl:
            parts.append(
                f"  {item.get('symbol')} {item.get('action')} — "
                f"thesis: {item.get('thesis','')[:80]}"
            )

    parts.append("")
    parts.append(
        "Analyze the above data. Be concise and actionable. "
        "Output ONLY the JSON review — no prose, no markdown."
    )

    return '\n'.join(parts)


def review_day(trade_history: list, portfolio: dict) -> dict:
    """
    End-of-day review. Calls Claude to analyze performance and
    generate insights for tomorrow.
    """
    log.info('Review starting — %d total trades, %d open positions',
             len(trade_history), len(portfolio.get('positions', [])))

    prompt = _build_review_prompt(trade_history, portfolio)

    print(f'[review] Calling {REVIEW_MODEL} (Codex via gateway)...')

    # Codex has no separate system slot — persona prepended into the message.
    result_text   = _run_codex(SYSTEM_PROMPT, prompt, model=REVIEW_MODEL)
    input_tokens  = 0   # Codex free tier — no Anthropic token billing
    output_tokens = 0
    cost_usd      = save_api_cost('review', input_tokens, output_tokens)

    print(f'[review] {len(result_text or "")} chars returned | ${cost_usd:.4f}')

    result = extract_json(result_text) if result_text else None

    if result is None:
        log.error('Review returned no parseable JSON')
        result = {
            'date':           datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'assessment':     'Review failed to parse.',
            'trades_today':   0,
            'pnl_today':      0.0,
            'insights_for_tomorrow': [],
        }

    result['_meta'] = {
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'cost_usd':      cost_usd,
        'model':         REVIEW_MODEL,
    }

    # Update performance log
    perf = load_json(PERFORMANCE_PATH, [])
    if not isinstance(perf, list):
        perf = []
    perf.append(result)
    save_json(PERFORMANCE_PATH, perf)

    log.info('Review complete | cost=$%.4f', cost_usd)
    _notify_review(result, trade_history, portfolio)
    return result


def _notify_review(result: dict, trade_history: list, portfolio: dict) -> None:
    account    = portfolio.get('account', {})
    balance    = float(account.get('portfolio_value', 0))
    date_str   = result.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    pnl_today  = float(result.get('pnl_today', 0))
    trades_n   = result.get('trades_today', 0)
    wins       = result.get('wins', 0)
    losses     = result.get('losses', 0)
    assessment = result.get('assessment', '')
    positions  = portfolio.get('positions', [])
    insights   = result.get('insights_for_tomorrow', [])

    # Best mover among today's closed trades
    today_str     = date_str
    today_closed  = [
        t for t in trade_history
        if (t.get('closed_at') or '').startswith(today_str) and
           t.get('pnl') is not None
    ]
    best_trade = max(today_closed, key=lambda t: float(t.get('pnl', 0)),
                     default=None) if today_closed else None

    lines = [
        f"🤵 JERRY — DAILY SUMMARY",
        f"Today: {trades_n} trades | {wins}W / {losses}L | {'+' if pnl_today >= 0 else ''}"
        f"${pnl_today:,.2f}",
        f"Open positions: {len(positions)}",
        f"Portfolio: ${balance:,.0f}",
    ]

    if best_trade:
        sym_b = best_trade.get('symbol', '?')
        pnl_b = float(best_trade.get('pnl', 0))
        lines.append(f"Best trade: {sym_b} {'+' if pnl_b >= 0 else ''}${pnl_b:.2f}")

    if assessment:
        lines.append(f"Assessment: {assessment}")

    if insights:
        lines.append("Tomorrow's watch:")
        for ins in insights[:3]:
            lines.append(f"  • {ins}")

    send_telegram('\n'.join(lines))
