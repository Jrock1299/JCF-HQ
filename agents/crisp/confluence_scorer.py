#!/usr/bin/env python3
"""
confluence_scorer.py — Layer 3: Confluence Scoring

Takes all detected signals for a given scan cycle, applies learned weights,
and decides whether to trade or wait.
"""

import json
import logging
import time
from datetime import datetime, timezone

from crisp_config import (
    SIGNAL_WEIGHTS_PATH,
    INITIAL_WEIGHTS,
    TRADE_THRESHOLD_BASE,
    TRADE_THRESHOLD_HIGH,
    TRADE_THRESHOLD_LOW,
    TRADE_THRESHOLD_LOSS_BOOST,
    MAX_SL_ATR_MULT,
)
from market_data import get_atr_h1

# ─────────────────────────────────────────────────────────────────────────────
# WEIGHT LOADING
# ─────────────────────────────────────────────────────────────────────────────

def load_weights() -> dict:
    """Load signal weights from file, falling back to initial defaults."""
    try:
        with open(SIGNAL_WEIGHTS_PATH) as f:
            data = json.load(f)
        return data.get('weights', INITIAL_WEIGHTS['weights'])
    except Exception:
        return INITIAL_WEIGHTS['weights']


def load_threshold() -> int:
    """Load the current trade threshold from the weights file."""
    try:
        with open(SIGNAL_WEIGHTS_PATH) as f:
            data = json.load(f)
        return data.get('threshold', TRADE_THRESHOLD_BASE)
    except Exception:
        return TRADE_THRESHOLD_BASE


# ─────────────────────────────────────────────────────────────────────────────
# SESSION DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def get_current_session() -> str:
    """Returns the current session name: 'london', 'ny', 'ny_pm', 'asia', 'offpeak'."""
    hour = datetime.now(timezone.utc).hour
    if 6 <= hour < 8:
        return 'london'
    if 13 <= hour < 16:
        return 'ny'
    if 17 <= hour < 20:
        return 'ny_pm'
    if hour >= 23 or hour < 1:
        return 'asia'
    return 'offpeak'


def get_session_threshold(base_threshold: int, session: str,
                           last_loss_ts: float = None) -> int:
    """
    Adjust the threshold based on session quality and recent losses.

    - High-volume sessions: -5 (easier to enter)
    - Off-peak: +7 (higher bar)
    - After a loss: +5 for 2 hours
    """
    threshold = base_threshold

    if session in ('ny', 'london'):
        threshold = max(threshold - 5, TRADE_THRESHOLD_LOW)
    elif session == 'offpeak':
        threshold = min(threshold + 7, TRADE_THRESHOLD_HIGH)

    # Post-loss penalty: raise threshold for 2 hours after a loss
    if last_loss_ts and (time.time() - last_loss_ts) < 7200:
        threshold += TRADE_THRESHOLD_LOSS_BOOST

    return threshold


# ─────────────────────────────────────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────────────────────────────────────

def calculate_confluence_score(signals: list) -> dict:
    """
    Score all signals for a single scan cycle.

    Rules:
    1. Signals in the same direction stack (additively, up to max_contribution)
    2. Signals in opposing directions reduce the total
    3. Score range: 0-100
    4. Returns the best-scoring direction with full breakdown
    """
    if not signals:
        return {
            'total_score': 0,
            'direction': None,
            'primary_signal': None,
            'confluence_factors': [],
            'conflicting_signals': [],
            'recommendation': 'WAIT',
        }

    weights = load_weights()

    # Separate by direction
    long_signals  = [s for s in signals if s['direction'] == 'long']
    short_signals = [s for s in signals if s['direction'] == 'short']

    def score_group(group: list) -> tuple:
        """Returns (total_score, primary_signal_type, factor_list)"""
        if not group:
            return 0, None, []
        total = 0
        factors = []
        # Sort by raw_score descending so primary is the strongest
        group_sorted = sorted(group, key=lambda s: s['raw_score'], reverse=True)
        primary = group_sorted[0]['type']

        for sig in group_sorted:
            sig_type = sig['type']
            w = weights.get(sig_type, {})
            max_contrib = w.get('max_contribution', sig['raw_score'])
            contribution = min(sig['raw_score'], max_contrib)
            total += contribution
            factors.append(sig_type)

        # Cap at 100
        total = min(total, 100)
        return total, primary, factors

    long_score,  long_primary,  long_factors  = score_group(long_signals)
    short_score, short_primary, short_factors = score_group(short_signals)

    # Pick best direction
    if long_score > short_score:
        direction  = 'long'
        score      = long_score
        primary    = long_primary
        factors    = long_factors
        conflicting = short_factors
        best_signal = sorted(long_signals, key=lambda s: s['raw_score'], reverse=True)[0]
    elif short_score > long_score:
        direction  = 'short'
        score      = short_score
        primary    = short_primary
        factors    = short_factors
        conflicting = long_factors
        best_signal = sorted(short_signals, key=lambda s: s['raw_score'], reverse=True)[0]
    else:
        return {
            'total_score': 0,
            'direction': None,
            'primary_signal': None,
            'confluence_factors': [],
            'conflicting_signals': long_factors + short_factors,
            'recommendation': 'WAIT',
        }

    return {
        'total_score': score,
        'direction': direction,
        'primary_signal': primary,
        'confluence_factors': factors,
        'conflicting_signals': conflicting,
        'best_signal': best_signal,
        'recommendation': 'WATCH',  # overridden below
    }


def evaluate_trade_decision(signals: list, session: str = None,
                             last_loss_ts: float = None,
                             atr_h1: float = None) -> dict:
    """
    Full evaluation: score signals, check threshold, validate SL width.

    Returns a decision dict with recommendation: 'TRADE' | 'WATCH' | 'WAIT'
    and the specific signal to trade (if TRADE).
    """
    if session is None:
        session = get_current_session()

    base_threshold = load_threshold()
    threshold = get_session_threshold(base_threshold, session, last_loss_ts)

    result = calculate_confluence_score(signals)
    result['session'] = session
    result['threshold'] = threshold

    if result['total_score'] == 0:
        result['recommendation'] = 'WAIT'
        return result

    score = result['total_score']
    best_sig = result.get('best_signal')

    if score >= threshold and best_sig:
        # Validate SL is not too wide
        if atr_h1 is None:
            try:
                atr_h1 = get_atr_h1()
            except Exception:
                atr_h1 = 0

        sl_dist = abs(best_sig['entry_price'] - best_sig['sl_price'])

        if atr_h1 > 0 and sl_dist > atr_h1 * MAX_SL_ATR_MULT:
            result['recommendation'] = 'WAIT'
            result['skip_reason'] = (
                f"SL too wide: ${sl_dist:.0f} > {MAX_SL_ATR_MULT}x ATR "
                f"(${atr_h1 * MAX_SL_ATR_MULT:.0f})"
            )
            logging.info(f"Signal skipped — SL too wide: {result['skip_reason']}")
            return result

        result['recommendation'] = 'TRADE'

    elif score >= threshold - 10:
        result['recommendation'] = 'WATCH'
    else:
        result['recommendation'] = 'WAIT'

    return result
