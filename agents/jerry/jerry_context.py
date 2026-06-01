"""
jerry_context.py — Team-context loader for Jerry.

Reads three shared HQ files:
  - market_bias.json         (Lens)
  - strategy_recommendation.json (Strategist regime per instrument)
  - norman_report.json       (Norman per-agent verdict)

Refresh once per trading cycle (called from jerry_main on each tick or at
discovery time). Stamp every trade with the current snapshot.

Phase 1: observation only. Jerry does NOT skip or gate trades based on this
context. The fields land on every closed-trade record so we can later
analyze whether macro/verdict alignment correlates with outcomes.
"""

import json
import logging
import os
from datetime import datetime, timezone

LENS_PATH        = '/root/.openclaw/dashboard/market_bias.json'
STRATEGIST_PATH  = '/root/.openclaw/dashboard/strategy_recommendation.json'
NORMAN_PATH      = '/root/.openclaw/dashboard/norman_report.json'

_DEFAULT = {
    'regime_at_entry':           'unknown',   # overall Strategist regime
    'strategist_bias':           {},          # per-instrument bias
    'strategist_instruments':    {},          # full per-instrument dict
    'lens_assets':               {},          # per-asset Lens dict
    'lens_overall':              'neutral',
    'norman_verdict':            'UNKNOWN',
    'norman_ruin_prob':          None,
    'norman_dated':              None,
    'context_loaded_at':         None,
}


def _safe_load(path):
    try:
        if os.path.isfile(path):
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"jerry_context: could not read {path}: {e}")
    return None


def load_context():
    """Read all three files. Return a flat snapshot dict."""
    ctx = dict(_DEFAULT)
    ctx['context_loaded_at'] = datetime.now(timezone.utc).isoformat()

    strat = _safe_load(STRATEGIST_PATH) or {}
    ctx['regime_at_entry'] = strat.get('regime', 'unknown')
    instruments = strat.get('instruments', {}) or {}
    ctx['strategist_instruments'] = instruments
    ctx['strategist_bias'] = {
        sym: (info or {}).get('bias', 'neutral')
        for sym, info in instruments.items()
    }

    lens = _safe_load(LENS_PATH) or {}
    assets = lens.get('assets', lens) if isinstance(lens, dict) else {}
    if isinstance(assets, dict):
        ctx['lens_assets'] = {
            k: (v if isinstance(v, dict) else {'direction': 'neutral'})
            for k, v in assets.items()
        }
    # Overall lens vibe = most common direction among known assets
    dirs = [d.get('direction', 'neutral').lower()
            for d in ctx['lens_assets'].values() if isinstance(d, dict)]
    if dirs:
        ctx['lens_overall'] = max(set(dirs), key=dirs.count)

    norman = _safe_load(NORMAN_PATH) or {}
    agent_reports = norman.get('agent_reports', {}) or {}
    jerry_report = agent_reports.get('jerry', {}) or {}
    ctx['norman_verdict']   = jerry_report.get('verdict', 'UNKNOWN')
    mc = jerry_report.get('monte_carlo', {}) or {}
    ctx['norman_ruin_prob'] = mc.get('ruin_probability')
    ctx['norman_dated']     = norman.get('date')

    return ctx


def lens_bias_for_symbol(ctx, symbol):
    """Return (direction, confidence) for a ticker. Match exact symbol first, else 'SPX500/US100' as fallback for stocks."""
    assets = ctx.get('lens_assets', {}) or {}
    for key in (symbol, f'{symbol}_USD', 'US100', 'SPX500'):
        entry = assets.get(key)
        if isinstance(entry, dict):
            return (
                (entry.get('direction', 'neutral') or 'neutral').lower(),
                float(entry.get('confidence', 50)),
            )
    return 'neutral', 50.0


def strategist_aligned_for_symbol(ctx, symbol, action):
    """True iff Strategist or Lens direction matches the trade action.
    action ∈ {buy, short, buy_call, buy_put, sell_put, sell_call, ...}
    Long-ish actions: buy/buy_call/sell_put → expects up.
    Short-ish actions: short/buy_put/sell_call → expects down.
    """
    a = (action or '').lower()
    if a in ('buy', 'buy_call', 'sell_put'):
        want = 'bullish'
    elif a in ('short', 'buy_put', 'sell_call'):
        want = 'bearish'
    else:
        return False

    # Strategist per-instrument bias (only filled for SPX/DE30/XAU/BTC — likely not Jerry's tickers)
    strat = (ctx.get('strategist_bias') or {}).get(symbol, 'neutral')
    if strat == want:
        return True
    # Fall back to Lens
    lens_dir, _ = lens_bias_for_symbol(ctx, symbol)
    return lens_dir == want


def snapshot_for_trade(ctx, symbol, action):
    """Snapshot fields to stamp onto a trade record at entry time."""
    lens_dir, lens_conf = lens_bias_for_symbol(ctx, symbol)
    return {
        'regime_at_entry':           ctx.get('regime_at_entry', 'unknown'),
        'strategist_bias_at_entry':  (ctx.get('strategist_bias') or {}).get(symbol, 'neutral'),
        'lens_bias_at_entry':        lens_dir,
        'lens_confidence_at_entry':  lens_conf,
        'lens_overall_at_entry':     ctx.get('lens_overall', 'neutral'),
        'strategist_aligned':        strategist_aligned_for_symbol(ctx, symbol, action),
        'norman_verdict_at_entry':   ctx.get('norman_verdict', 'UNKNOWN'),
        'norman_ruin_prob_at_entry': ctx.get('norman_ruin_prob'),
        'norman_dated':              ctx.get('norman_dated'),
        'context_loaded_at':         ctx.get('context_loaded_at'),
    }
