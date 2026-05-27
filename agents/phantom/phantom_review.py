"""
phantom_review.py — Performance review and strategy adaptation engine.

Runs after trades close (or every 6 hours) to analyse Phantom's own
performance, decide which strategies to retire, and feed insights
into the next Discovery cycle.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, '/root/.openclaw/agents/norman')

from phantom_config import (
    REVIEW_MODEL, TRADE_HISTORY_PATH, STRATEGIES_PATH, PERFORMANCE_PATH,
    get_logger, send_telegram, save_api_cost, load_json, save_json,
    extract_json,
)
from norman_brain import calculate_stats, monte_carlo_simulation

log = get_logger('review')

MAX_TOKENS_REVIEW = 4096

SYSTEM_PROMPT_REVIEW = """\
You are Phantom's self-assessment module. Your job is to analyse Phantom's \
own trading performance and adapt its strategies.

Be brutally honest. Kill losing strategies fast. Double down on what's working. \
Adapt to changing market conditions without hesitation.

FRAMEWORK:
- A strategy with < 10 trades is too new to judge — give it time but watch closely
- If win rate drops below 40% over last 10 trades → DEGRADE confidence
- If win rate below 35% over 20+ trades → RETIRE
- If profit factor < 1.0 over 15+ trades → RETIRE
- If a strategy has 3 consecutive losses → FLAG for review
- If a strategy shows signs of regime change → MODIFY or RETIRE
- If a strategy is consistently profitable → INCREASE confidence, consider scaling

OUTPUT FORMAT (valid JSON only, no markdown):
{
  "review_summary": "2-3 sentence assessment of overall performance",
  "strategy_updates": [
    {
      "name": "strategy name",
      "action": "keep/modify/retire/scale",
      "confidence_change": "+1/-1/0",
      "reason": "why",
      "modifications": "what to change if action=modify"
    }
  ],
  "insights_for_discovery": [
    "observation that should inform next strategy generation"
  ],
  "regime_assessment": "what market regime has been in play recently",
  "alerts": ["any urgent issues"]
}"""


def _format_review_prompt(trade_history: list, active_strategies: list,
                           per_strategy_stats: dict) -> str:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    parts = [f"PERFORMANCE REVIEW — {now}", ""]

    # Overall stats
    closed = [t for t in trade_history if t.get('status') == 'closed']
    if closed:
        wins     = sum(1 for t in closed if (t.get('pnl') or 0) > 0)
        total_pnl = sum(t.get('pnl', 0) or 0 for t in closed)
        parts.append(
            f"OVERALL: {len(closed)} trades  "
            f"WR={wins/len(closed)*100:.0f}%  "
            f"Total PnL=${total_pnl:+.2f}"
        )
        parts.append("")

    # Per-strategy stats
    if per_strategy_stats:
        parts.append("PER-STRATEGY STATISTICS:")
        for name, stats in per_strategy_stats.items():
            parts.append(
                f"  [{name}]  n={stats.get('n')}  "
                f"WR={stats.get('win_rate')}%  "
                f"PF={stats.get('profit_factor')}  "
                f"Sharpe={stats.get('sharpe')}  "
                f"PnL=${stats.get('total_pnl'):+.2f}  "
                f"MaxDD={stats.get('max_drawdown_pct')}%"
            )
        parts.append("")

    # Recent trades (last 20)
    recent = [t for t in closed[-20:] if t.get('pnl') is not None]
    if recent:
        parts.append(f"RECENT {len(recent)} TRADES:")
        for t in recent:
            pnl = t.get('pnl', 0) or 0
            parts.append(
                f"  [{t.get('strategy_name', '?')}] "
                f"{t.get('symbol')} {t.get('side', '?').upper()}  "
                f"PnL=${pnl:+.2f}  "
                f"reason={t.get('close_reason', '?')}  "
                f"lev={t.get('leverage')}x"
            )
        parts.append("")

    # Active strategies summary
    if active_strategies:
        parts.append("ACTIVE STRATEGIES:")
        for s in active_strategies:
            parts.append(
                f"  [{s.get('name')}]  tf={s.get('timeframe')}  "
                f"instruments={s.get('instruments')}  "
                f"confidence={s.get('confidence', '?')}  "
                f"trades={s.get('performance', {}).get('trades', 0)}"
            )
        parts.append("")

    parts.append(
        "Analyse this performance data and provide your assessment. "
        "Output ONLY valid JSON."
    )
    return '\n'.join(parts)


def review_performance(
    trade_history: list = None,
    active_strategies: list = None,
) -> dict:
    """
    Analyse Phantom's trade history and update strategy confidence/status.

    Args:
        trade_history:    List of trade dicts (loads from file if None).
        active_strategies: List of strategy dicts (loads from file if None).

    Returns:
        Review dict with strategy_updates, insights_for_discovery, etc.
    """
    if trade_history is None:
        trade_history = load_json(TRADE_HISTORY_PATH, [])
    if active_strategies is None:
        active_strategies = load_json(STRATEGIES_PATH, [])

    closed = [t for t in trade_history if t.get('status') == 'closed']
    log.info('Review: %d total trades (%d closed), %d active strategies',
             len(trade_history), len(closed), len(active_strategies))

    # Calculate per-strategy stats
    per_strategy_stats = {}
    strategy_names = {t.get('strategy_name') for t in closed if t.get('strategy_name')}
    for name in strategy_names:
        strat_trades = [t for t in closed if t.get('strategy_name') == name]
        if strat_trades:
            per_strategy_stats[name] = calculate_stats(strat_trades, name)

    if not closed:
        result = {
            'review_summary': 'No closed trades yet — nothing to review.',
            'strategy_updates': [],
            'insights_for_discovery': ['No trade history — generate diverse initial strategies'],
            'regime_assessment': 'unknown',
            'alerts': [],
            '_meta': {'skipped': True},
        }
        _apply_strategy_updates(result, active_strategies)
        return result

    # Call Claude
    prompt   = _format_review_prompt(closed, active_strategies, per_strategy_stats)
    client   = anthropic.Anthropic()
    response = client.messages.create(
        model=REVIEW_MODEL,
        max_tokens=MAX_TOKENS_REVIEW,
        system=SYSTEM_PROMPT_REVIEW,
        messages=[{'role': 'user', 'content': prompt}],
    )

    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_usd      = save_api_cost('review', input_tokens, output_tokens)

    log.info('Review: %d in + %d out | $%.4f', input_tokens, output_tokens, cost_usd)

    result_text = next(
        (b.text for b in response.content if getattr(b, 'type', '') == 'text'),
        ''
    )
    result = extract_json(result_text)

    if result is None:
        log.error('Review returned no JSON')
        result = {
            'review_summary': 'Review failed to parse.',
            'strategy_updates': [],
            'insights_for_discovery': [],
            'regime_assessment': 'unknown',
            'alerts': ['Review module failed to return JSON'],
        }

    result['_meta'] = {
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'cost_usd':      cost_usd,
        'trades_reviewed': len(closed),
    }
    result['per_strategy_stats'] = per_strategy_stats

    # Apply updates to strategies.json
    _apply_strategy_updates(result, active_strategies)

    # Save performance snapshot
    _save_performance(result, per_strategy_stats, closed)

    # Notify Telegram if any retirements/alerts
    _notify_review(result)

    return result


def _apply_strategy_updates(review: dict, active_strategies: list) -> None:
    """Apply Claude's strategy_updates to the strategies.json file."""
    updates = review.get('strategy_updates', [])
    if not updates:
        return

    strategies = load_json(STRATEGIES_PATH, [])
    if not isinstance(strategies, list):
        strategies = []

    changed = []
    for upd in updates:
        name   = upd.get('name', '')
        action = upd.get('action', 'keep').lower()
        for s in strategies:
            if s.get('name') == name:
                if action == 'retire':
                    s['status']     = 'retired'
                    s['retired_at'] = datetime.now(timezone.utc).isoformat()
                    s['retire_reason'] = upd.get('reason', '')
                    changed.append(f"RETIRED: {name}")
                    log.info('Strategy retired: %s — %s', name, upd.get('reason'))
                elif action == 'scale':
                    s['confidence']      = min(10, (s.get('confidence_score', 5) + 1))
                    s['scale_up']        = True
                    changed.append(f"SCALED: {name}")
                elif action == 'modify':
                    s['pending_modification'] = upd.get('modifications', '')
                    changed.append(f"MODIFIED: {name}")
                elif action == 'degrade':
                    s['confidence_score'] = max(1, (s.get('confidence_score', 5) - 1))

    if changed:
        save_json(STRATEGIES_PATH, strategies)
        log.info('Strategy updates applied: %s', ', '.join(changed))


def _save_performance(review: dict, per_strategy_stats: dict, closed: list) -> None:
    """Append performance snapshot to performance.json."""
    snapshot = {
        'timestamp':          datetime.now(timezone.utc).isoformat(),
        'total_closed_trades': len(closed),
        'total_pnl':          round(sum(t.get('pnl', 0) or 0 for t in closed), 2),
        'per_strategy_stats': per_strategy_stats,
        'review_summary':     review.get('review_summary', ''),
        'regime':             review.get('regime_assessment', ''),
    }
    history = load_json(PERFORMANCE_PATH, [])
    if not isinstance(history, list):
        history = []
    history.append(snapshot)
    # Keep last 52 snapshots (≈ 1 year of weekly reviews)
    save_json(PERFORMANCE_PATH, history[-52:])


def _notify_review(review: dict) -> None:
    updates = review.get('strategy_updates', [])
    alerts  = review.get('alerts', [])

    retirements = [u for u in updates if u.get('action') == 'retire']
    scales      = [u for u in updates if u.get('action') == 'scale']

    if not retirements and not scales and not alerts:
        return

    lines = ['PHANTOM — STRATEGY REVIEW COMPLETE', '']
    lines.append(f"Summary: {review.get('review_summary', '')[:120]}")

    if retirements:
        lines.append('')
        lines.append('Retired strategies:')
        for r in retirements:
            lines.append(f"  • {r.get('name')} — {r.get('reason', '')[:80]}")

    if scales:
        lines.append('')
        lines.append('Scaled up:')
        for s in scales:
            lines.append(f"  • {s.get('name')} — {s.get('reason', '')[:80]}")

    if alerts:
        lines.append('')
        lines.append('Alerts:')
        for a in alerts:
            lines.append(f"  ⚡ {a}")

    send_telegram('\n'.join(lines))
