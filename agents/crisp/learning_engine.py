#!/usr/bin/env python3
"""
learning_engine.py — Layer 5: Weekly Learning Engine

Analyses all logged signals (traded + untaken) to identify which signal
combinations produce winners. Adjusts weights and threshold accordingly.
Runs weekly on Saturday (called from crisp_main.py or a cron job).
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from crisp_config import (
    SIGNAL_LOG_PATH, SIGNAL_WEIGHTS_PATH, LEARNING_REPORTS_DIR,
    INITIAL_WEIGHTS, TRADE_THRESHOLD_BASE, AGENT_NAME,
    send_telegram, hub_post,
)

# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL LOG HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def load_signal_log() -> list:
    try:
        with open(SIGNAL_LOG_PATH) as f:
            return json.load(f).get('signals', [])
    except Exception:
        return []


def append_signal_log(signal: dict, traded: bool, outcome: dict = None):
    """
    Log every detected signal (traded or not) with its outcome (if known).
    For untaken signals, outcome is populated later by the learning engine
    by checking candle history at the signal's price levels.
    """
    try:
        with open(SIGNAL_LOG_PATH) as f:
            data = json.load(f)
    except Exception:
        data = {'signals': []}

    entry = {
        'signal_id':    signal.get('signal_id'),
        'timestamp':    signal.get('timestamp'),
        'type':         signal.get('type'),
        'direction':    signal.get('direction'),
        'confluence_score': signal.get('raw_score', 0),
        'traded':       traded,
        'entry_price':  signal.get('entry_price'),
        'sl_price':     signal.get('sl_price'),
        'tp1_price':    signal['tp_targets'][0] if signal.get('tp_targets') else None,
        'tp2_price':    signal['tp_targets'][1] if len(signal.get('tp_targets', [])) > 1 else None,
        'outcome':      outcome,  # filled in later for untaken; filled immediately for traded
        'contributing_factors': list(signal.get('factors', {}).keys()),
    }
    data['signals'].append(entry)
    with open(SIGNAL_LOG_PATH, 'w') as f:
        json.dump(data, f, indent=2)


def update_signal_outcome(signal_id: str, outcome: dict):
    """Update a previously logged signal with its outcome."""
    try:
        with open(SIGNAL_LOG_PATH) as f:
            data = json.load(f)
        for sig in data['signals']:
            if sig['signal_id'] == signal_id:
                sig['outcome'] = outcome
                break
        with open(SIGNAL_LOG_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.warning(f"update_signal_outcome failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def _is_winner(outcome: dict) -> bool | None:
    """Returns True/False/None (None = outcome unknown)."""
    if not outcome:
        return None
    result = outcome.get('result', '')
    if result in ('TP1_HIT', 'TP2_HIT', 'TRAIL_STOP') and outcome.get('pnl_usd', 0) > 0:
        return True
    if result in ('SL_HIT',):
        return False
    if outcome.get('pnl_usd', 0) > 0:
        return True
    if outcome.get('pnl_usd', 0) < 0:
        return False
    return None


def analyze_performance() -> dict:
    """
    Main analysis function. Returns a report dict.
    Requires minimum 20 signals with known outcomes before making adjustments.
    """
    signals = load_signal_log()

    # Only consider signals with known outcomes
    resolved = [s for s in signals if _is_winner(s.get('outcome')) is not None]

    if len(resolved) < 20:
        return {
            'status': 'insufficient_data',
            'resolved_signals': len(resolved),
            'total_signals': len(signals),
            'message': f"Need 20+ resolved signals, have {len(resolved)}",
        }

    traded    = [s for s in resolved if s.get('traded')]
    untaken   = [s for s in resolved if not s.get('traded')]

    # 1. Win rate by signal type
    type_stats = defaultdict(lambda: {'wins': 0, 'total': 0, 'pnls': []})
    for s in resolved:
        t = s['type']
        w = _is_winner(s['outcome'])
        type_stats[t]['total'] += 1
        if w:
            type_stats[t]['wins'] += 1
        pnl = s.get('outcome', {}).get('pnl_usd')
        if pnl is not None:
            type_stats[t]['pnls'].append(pnl)

    type_wr = {}
    for t, stats in type_stats.items():
        wr = stats['wins'] / stats['total'] if stats['total'] > 0 else 0
        avg_pnl = mean(stats['pnls']) if stats['pnls'] else 0
        type_wr[t] = {
            'win_rate': round(wr, 3),
            'total': stats['total'],
            'wins': stats['wins'],
            'avg_pnl': round(avg_pnl, 2),
        }

    # 2. Confluence factor effectiveness
    factor_stats = defaultdict(lambda: {'in_wins': 0, 'in_losses': 0})
    for s in resolved:
        w = _is_winner(s['outcome'])
        for f in s.get('contributing_factors', []):
            if w:
                factor_stats[f]['in_wins'] += 1
            else:
                factor_stats[f]['in_losses'] += 1

    factor_effectiveness = {}
    for f, stats in factor_stats.items():
        total = stats['in_wins'] + stats['in_losses']
        if total > 0:
            factor_effectiveness[f] = {
                'win_rate_when_present': round(stats['in_wins'] / total, 3),
                'occurrences': total,
            }

    # 3. Weight adjustments
    current_weights = _load_current_weights()
    proposed_weights = {}
    for sig_type, stats in type_wr.items():
        current_w = current_weights.get(sig_type, {}).get('base_weight', 20)
        wr = stats['win_rate']
        # Adjust: strong performers +2, weak performers -2, neutral unchanged
        if wr >= 0.65 and stats['total'] >= 5:
            adjustment = +2
            reason = f"+2 from {wr*100:.0f}% WR over {stats['total']} trades"
        elif wr <= 0.40 and stats['total'] >= 5:
            adjustment = -2
            reason = f"-2 from {wr*100:.0f}% WR over {stats['total']} trades"
        else:
            adjustment = 0
            reason = f"No change — {wr*100:.0f}% WR ({stats['total']} trades)"

        # Cap: max ±20% of initial base weight
        initial_w = INITIAL_WEIGHTS['weights'].get(sig_type, {}).get('base_weight', 20)
        cap_max = initial_w * 1.20
        cap_min = initial_w * 0.80
        new_w = max(cap_min, min(cap_max, current_w + adjustment))
        proposed_weights[sig_type] = {
            'base_weight': int(new_w),
            'adjusted_from': current_w,
            'reason': reason,
        }

    # 4. Threshold optimization
    current_threshold = _load_current_threshold()
    # Check: untaken signals that scored 55-65 — what WR would they have had?
    near_threshold = [s for s in untaken
                      if 55 <= s.get('confluence_score', 0) <= current_threshold]
    if len(near_threshold) >= 5:
        near_wr = sum(1 for s in near_threshold if _is_winner(s['outcome'])) / len(near_threshold)
        if near_wr >= 0.65:
            new_threshold = max(current_threshold - 5, 55)
            threshold_reason = (
                f"Untaken signals {current_threshold-10}-{current_threshold} "
                f"had {near_wr*100:.0f}% theoretical WR — lowering to {new_threshold}"
            )
        elif near_wr < 0.40:
            new_threshold = min(current_threshold + 5, 80)
            threshold_reason = (
                f"Near-threshold signals had low {near_wr*100:.0f}% WR — "
                f"raising to {new_threshold}"
            )
        else:
            new_threshold = current_threshold
            threshold_reason = f"Threshold unchanged — near-threshold WR neutral ({near_wr*100:.0f}%)"
    else:
        new_threshold = current_threshold
        threshold_reason = "Threshold unchanged — insufficient near-threshold data"

    # Overall performance stats
    traded_wins = sum(1 for s in traded if _is_winner(s['outcome']))
    traded_pnls = [s['outcome']['pnl_usd'] for s in traded
                   if s.get('outcome') and s['outcome'].get('pnl_usd') is not None]
    total_pnl = sum(traded_pnls)
    overall_wr = traded_wins / len(traded) if traded else 0

    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'signals_total': len(signals),
        'signals_resolved': len(resolved),
        'trades_taken': len(traded),
        'trades_won': traded_wins,
        'win_rate': round(overall_wr, 3),
        'total_pnl_usd': round(total_pnl, 2),
        'type_performance': type_wr,
        'factor_effectiveness': factor_effectiveness,
        'proposed_weight_adjustments': proposed_weights,
        'proposed_threshold': new_threshold,
        'threshold_reason': threshold_reason,
        'untaken_that_would_have_won': sum(1 for s in untaken if _is_winner(s['outcome'])),
        'untaken_that_would_have_lost': sum(1 for s in untaken if not _is_winner(s['outcome'])),
        'status': 'ready_to_apply',
    }

    # Safeguard: if 2-week WR < 30%, revert to initial weights
    if overall_wr < 0.30 and len(traded) >= 10:
        report['warning'] = 'WIN_RATE_CRITICALLY_LOW — reverting to initial weights'
        report['proposed_weight_adjustments'] = {
            k: {'base_weight': v['base_weight'], 'adjusted_from': v['base_weight'], 'reason': 'Reverted'}
            for k, v in INITIAL_WEIGHTS['weights'].items()
        }
        report['proposed_threshold'] = TRADE_THRESHOLD_BASE

    return report


# ─────────────────────────────────────────────────────────────────────────────
# WEIGHT APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

def apply_adjustments(report: dict):
    """
    Apply the proposed weight adjustments from an analysis report.
    Updates signal_weights.json and saves a learning report.
    """
    if report.get('status') not in ('ready_to_apply',):
        logging.info(f"Learning: not applying — {report.get('status')}")
        return

    current = _load_weights_full()
    new_version = current.get('version', 1) + 1
    now_str = datetime.now(timezone.utc).isoformat()

    # Merge proposed adjustments
    new_weights = dict(current.get('weights', {}))
    for sig_type, adj in report.get('proposed_weight_adjustments', {}).items():
        if sig_type in new_weights:
            new_weights[sig_type] = {
                **new_weights[sig_type],
                'base_weight': adj['base_weight'],
            }
        else:
            new_weights[sig_type] = adj

    history = current.get('history', [])
    changes = ', '.join(
        f"{k}: {v['adjusted_from']}→{v['base_weight']}"
        for k, v in report.get('proposed_weight_adjustments', {}).items()
        if v['base_weight'] != v.get('adjusted_from', v['base_weight'])
    ) or 'No changes'

    updated = {
        'version': new_version,
        'updated_at': now_str,
        'weights': new_weights,
        'threshold': report.get('proposed_threshold', TRADE_THRESHOLD_BASE),
        'threshold_adjusted_from': current.get('threshold', TRADE_THRESHOLD_BASE),
        'threshold_reason': report.get('threshold_reason', ''),
        'history': history + [{
            'version': new_version,
            'date': now_str[:10],
            'changes': changes,
        }],
    }

    with open(SIGNAL_WEIGHTS_PATH, 'w') as f:
        json.dump(updated, f, indent=2)

    # Save report
    week_label = datetime.now(timezone.utc).strftime('%Y_W%W')
    report_path = os.path.join(LEARNING_REPORTS_DIR, f'report_{week_label}.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    logging.info(f"Learning engine applied v{new_version}: {changes}")
    _send_learning_report(report)


def _send_learning_report(report: dict):
    """Send the weekly learning report to Telegram."""
    wr = report.get('win_rate', 0)
    total_pnl = report.get('total_pnl_usd', 0)
    trades = report.get('trades_taken', 0)
    won = report.get('trades_won', 0)
    threshold = report.get('proposed_threshold', TRADE_THRESHOLD_BASE)
    sign = '+' if total_pnl >= 0 else ''

    # Top signal type
    type_perf = report.get('type_performance', {})
    type_lines = ''
    for t, stats in sorted(type_perf.items(), key=lambda x: -x[1].get('win_rate', 0)):
        type_lines += f"\n  {t.replace('_',' ')}: {stats['wins']}/{stats['total']} ({stats['win_rate']*100:.0f}%)"

    weight_lines = ''
    for t, adj in report.get('proposed_weight_adjustments', {}).items():
        delta = adj['base_weight'] - adj.get('adjusted_from', adj['base_weight'])
        if delta != 0:
            weight_lines += f"\n  {t}: {adj.get('adjusted_from','?')} → {adj['base_weight']} ({'+' if delta>0 else ''}{delta})"

    msg = (
        f"📊 CRISP v5 WEEKLY LEARNING\n\n"
        f"Signals: {report['signals_resolved']} resolved | Trades: {trades} taken\n"
        f"Win rate: {wr*100:.1f}% ({won}W-{trades-won}L)\n"
        f"Total P&L: {sign}${total_pnl:.2f}\n"
        f"\nSignal Performance:{type_lines or ' (no data)'}"
        f"\nWeight Changes:{weight_lines or ' none'}"
        f"\nThreshold: → {threshold} ({report.get('threshold_reason','')})"
        f"\nUntaken winners: {report.get('untaken_that_would_have_won',0)}"
        f"\nUntaken losers: {report.get('untaken_that_would_have_lost',0)}"
    )
    if report.get('warning'):
        msg += f"\n\n⚠️ {report['warning']}"

    send_telegram(msg)
    hub_post(AGENT_NAME, 'learning_report', msg, tags=['crisp_v5', 'learning'])


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load_weights_full() -> dict:
    try:
        with open(SIGNAL_WEIGHTS_PATH) as f:
            return json.load(f)
    except Exception:
        return dict(INITIAL_WEIGHTS)


def _load_current_weights() -> dict:
    return _load_weights_full().get('weights', INITIAL_WEIGHTS['weights'])


def _load_current_threshold() -> int:
    return _load_weights_full().get('threshold', TRADE_THRESHOLD_BASE)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT (when called directly for Saturday run)
# ─────────────────────────────────────────────────────────────────────────────

def run_weekly_learning():
    """Main entry point. Called by crisp_main.py on Saturdays."""
    logging.info("Learning engine: starting weekly analysis")
    report = analyze_performance()
    logging.info(f"Learning engine: {report.get('status')} — "
                 f"{report.get('trades_taken',0)} trades, "
                 f"{report.get('win_rate',0)*100:.1f}% WR")

    if report.get('status') == 'insufficient_data':
        send_telegram(
            f"📊 CRISP v5 Weekly Learning\n"
            f"Insufficient data: {report.get('resolved_signals',0)} signals "
            f"(need 20+). Collecting more data."
        )
        return report

    apply_adjustments(report)
    return report


if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/root/.openclaw/agents/crisp')
    run_weekly_learning()
