#!/usr/bin/env python3
"""
lens_regime.py — Pre-session market regime briefing. (Absorbed from Jarvis.)

Jarvis (internal id `strategist`) was retired 2026-07-25; this is his regime
engine, moved into Lens's codebase unchanged in contract and extended with the
Multi-Timeframe Convergence read his own brief documented.

Outputs (per instrument):
  - regime: TRENDING / RANGING / COMPRESSED / VOLATILE
  - EMA-derived bias direction
  - Lens macro bias (from market_bias.json — Lens now reads her own output)
  - ADR(10d) and current price
  - Multi-Timeframe Convergence: 0-100 + per-component breakdown
  - Time-Based Edge Map: top time-of-day windows by directional win rate
  - Optional Monte Carlo summary over recent agent trade P&L

⚠️  CONTRACT — DO NOT BREAK.
    This writes dashboard/strategy_recommendation.json. FIVE consumers read it:
      • agents/blade/bot/blade_bot.py     — load_session_context()
      • agents/edge/edge_main.py          — trade-time context snapshot
      • agents/jerry/jerry_context.py     — strategist_instruments / bias
      • agents/crisp/bot/crisp_bot.py     — parked, but still reads it
      • hq-app/src/pages/Intelligence.tsx — strat.instruments / strat.regime
    The keys they read are `updated`, `regime`, `instruments`, `monte_carlo`,
    and per-instrument {regime, bias, lens_bias, lens_confidence, adr,
    current_price}. Every one is still produced, unchanged. New keys
    (`convergence`, `edge_map`) are ADDITIVE — no consumer sees a difference.

⚠️  OBSERVATION ONLY. This briefs; it does not gate. CLAUDE.md Critical Rule #6:
    Blade/Edge/Jerry SEE this context and DO NOT GATE on it. The convergence
    score is a read, not a filter — the 0-100 score deleted in the 2026-06-01
    trim was removed for being dead weight, and this one must not become a
    trade filter without an explicit Phase-3 PR.

Usage:
  python3 lens_regime.py                    # all instruments
  python3 lens_regime.py SPX500_USD         # single instrument
  python3 lens_regime.py --monte-carlo      # include Monte Carlo on recent trades
"""

import json
import logging
import os
import random
import sys
from datetime import datetime, timezone, timedelta
from statistics import mean, stdev

import oandapyV20
from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles

sys.path.insert(0, "/root/.openclaw/scripts")
from hub_post import add_hub_message as hub_post

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

AGENT_NAME    = "lens"
DASHBOARD_DIR = "/root/.openclaw/dashboard"
STRATEGY_REC  = f"{DASHBOARD_DIR}/strategy_recommendation.json"
MARKET_BIAS   = f"{DASHBOARD_DIR}/market_bias.json"
TRADES_JSON   = f"{DASHBOARD_DIR}/agent_trades.json"

logging.basicConfig(
    filename='/root/.openclaw/logs/lens_regime.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

with open('/root/.openclaw/agents/main/agent/auth-profiles.json') as f:
    _auth = json.load(f)
_creds = _auth['profiles']['oanda:default']
client = API(access_token=_creds['key'], environment='practice')

OANDA_INSTRUMENTS = ['SPX500_USD', 'DE30_EUR', 'XAU_USD']
ALL_INSTRUMENTS   = ['SPX500_USD', 'DE30_EUR', 'XAU_USD', 'BTC_USD']

GRANULARITY = {'M15': 'M15', 'H1': 'H1', 'H4': 'H4', 'D': 'D'}

# Time-Based Edge Map depth. OANDA caps a single candles request at 5000.
EDGE_MAP_CANDLES     = 5000   # ~52 trading days of M15 → ~50 samples per slot
EDGE_MAP_MIN_CANDLES = 1000   # below this the map is skipped, not guessed at

# ADR normal ranges per instrument (points / price units)
ADR_NORMAL = {
    'SPX500_USD': {'min': 15,  'max': 120,  'extreme': 180},
    'DE30_EUR':   {'min': 50,  'max': 400,  'extreme': 600},
    'XAU_USD':    {'min': 8,   'max': 80,   'extreme': 120},
    'BTC_USD':    {'min': 500, 'max': 5000, 'extreme': 7500},
}

LENS_KEYS = {
    'SPX500_USD': ['SPX500_USD', 'US100'],
    'DE30_EUR':   ['DE30_EUR', 'DE40_EUR', 'DE40'],
    'XAU_USD':    ['XAU/USD', 'XAU_USD'],
    'BTC_USD':    ['BTC/USDT', 'BTC_USDT', 'BTC/USD'],
}

# ─────────────────────────────────────────────────────────────────────────────
# DATA INGESTION
# ─────────────────────────────────────────────────────────────────────────────

def fetch_oanda_candles(instrument, granularity, count=200):
    try:
        r = InstrumentsCandles(instrument, params={
            'granularity': granularity, 'count': count, 'price': 'M',
        })
        client.request(r)
        raw = r.response.get('candles', [])
        out = []
        for c in raw:
            if not c.get('complete', True):
                continue
            m = c['mid']
            out.append({
                'time':   c['time'],
                'open':   float(m['o']), 'high': float(m['h']),
                'low':    float(m['l']), 'close': float(m['c']),
                'volume': int(c.get('volume', 0)),
            })
        return out
    except Exception as e:
        logging.error(f"fetch_oanda_candles({instrument},{granularity}): {e}")
        return []


def fetch_btc_candles(timeframe_str, count=200):
    try:
        import ccxt
        binance = ccxt.binance({'enableRateLimit': True})
        tf = {'M15': '15m', 'H1': '1h', 'H4': '4h', 'D': '1d'}.get(timeframe_str, '1h')
        raw = binance.fetch_ohlcv('BTC/USDT', tf, limit=count)
        return [{
            'time':   datetime.fromtimestamp(ts/1000, tz=timezone.utc).isoformat(),
            'open':   float(o), 'high': float(h),
            'low':    float(l), 'close': float(c), 'volume': float(v),
        } for (ts, o, h, l, c, v) in raw]
    except Exception as e:
        logging.error(f"fetch_btc_candles({timeframe_str}): {e}")
        return []


def fetch_candles(instrument, timeframe, count=200):
    if instrument == 'BTC_USD':
        return fetch_btc_candles(timeframe, count)
    return fetch_oanda_candles(instrument, GRANULARITY[timeframe], count)


# ─────────────────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────────────────

def ema(prices, period):
    if len(prices) < period:
        return [None] * len(prices)
    k = 2.0 / (period + 1)
    result = [None] * len(prices)
    result[period - 1] = mean(prices[:period])
    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1 - k)
    return result


def bollinger_bands(closes, period=20, std_dev=2.0):
    upper = [None] * len(closes)
    middle = [None] * len(closes)
    lower = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        mu = mean(window)
        sd = stdev(window) if len(window) > 1 else 0
        middle[i] = mu
        upper[i] = mu + std_dev * sd
        lower[i] = mu - std_dev * sd
    return upper, middle, lower


def atr(candles, period=14):
    trs = [None]
    for i in range(1, len(candles)):
        h, l, pc = candles[i]['high'], candles[i]['low'], candles[i - 1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    result = [None] * len(candles)
    if len(trs) < period + 1:
        return result
    result[period] = mean([t for t in trs[1:period + 1] if t is not None])
    for i in range(period + 1, len(candles)):
        if trs[i] is not None and result[i - 1] is not None:
            result[i] = (result[i - 1] * (period - 1) + trs[i]) / period
    return result


def calc_adr(daily_candles, period=10):
    completed = [c for c in daily_candles if c]
    if len(completed) < period:
        return None
    return mean(c['high'] - c['low'] for c in completed[-period:])


def calc_indicators(candles):
    closes = [c['close'] for c in candles]
    ind = {
        'ema9':  ema(closes, 9),
        'ema20': ema(closes, 20),
        'ema21': ema(closes, 21),
        'ema50': ema(closes, 50),
        'atr14': atr(candles, 14),
    }
    ind['bb_upper'], ind['bb_middle'], ind['bb_lower'] = bollinger_bands(closes)
    return ind


# ─────────────────────────────────────────────────────────────────────────────
# EMA ALIGNMENT
# ─────────────────────────────────────────────────────────────────────────────

def ema_alignment(indicators, idx=-1):
    e9, e20, e21, e50 = (indicators['ema9'][idx], indicators['ema20'][idx],
                         indicators['ema21'][idx], indicators['ema50'][idx])
    if None in (e9, e20, e21, e50):
        return 'neutral'
    if e9 > e20 > e21 > e50:
        return 'bullish'
    if e9 < e20 < e21 < e50:
        return 'bearish'
    return 'neutral'


def ema_slope_direction(ema_values, lookback=3):
    vals = [v for v in ema_values[-lookback:] if v is not None]
    if len(vals) < 2:
        return 'neutral'
    if vals[-1] > vals[0]:
        return 'bullish'
    if vals[-1] < vals[0]:
        return 'bearish'
    return 'neutral'


# ─────────────────────────────────────────────────────────────────────────────
# BB SQUEEZE (compression detector for regime)
# ─────────────────────────────────────────────────────────────────────────────

def bb_squeeze_ratio(indicators, idx=-1):
    upper, lower, mid = indicators['bb_upper'], indicators['bb_lower'], indicators['bb_middle']
    if upper[idx] is None or lower[idx] is None or mid[idx] is None:
        return 1.0
    cur_bw = upper[idx] - lower[idx]
    widths = [upper[i] - lower[i] for i in range(max(-40, -len(upper)), 0)
              if upper[i] is not None and lower[i] is not None]
    if not widths or mean(widths) == 0:
        return 1.0
    return cur_bw / mean(widths)


# ─────────────────────────────────────────────────────────────────────────────
# REGIME DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_regime(candles_h4, candles_d, indicators_h4, adr_current, instrument):
    adr_ref = ADR_NORMAL.get(instrument, {})
    adr_extreme = adr_ref.get('extreme', 99999)

    if adr_current and adr_current > adr_extreme:
        return 'volatile'

    h4_align = ema_alignment(indicators_h4)
    squeeze = bb_squeeze_ratio(indicators_h4)
    atr_vals = [v for v in indicators_h4['atr14'][-10:] if v is not None]
    atr_expanding = (atr_vals[-1] > atr_vals[0] * 1.1) if len(atr_vals) >= 2 else False

    if len(candles_h4) >= 10:
        recent = candles_h4[-10:]
        highs = [c['high'] for c in recent]
        lows = [c['low'] for c in recent]
        hh = highs[-1] > highs[0] * 1.003
        ll = lows[-1] < lows[0] * 0.997
        trending_structure = (h4_align == 'bullish' and hh) or (h4_align == 'bearish' and ll)
    else:
        trending_structure = False

    if squeeze < 0.65 and not atr_expanding:
        return 'compressed'
    if h4_align != 'neutral' and trending_structure and atr_expanding:
        return 'trending'
    return 'ranging'


# ─────────────────────────────────────────────────────────────────────────────
# LENS BIAS (from market_bias.json)
# ─────────────────────────────────────────────────────────────────────────────

def read_lens_bias(instrument):
    """Read the macro bias out of market_bias.json.

    Note this file is now Lens reading her own morning output — lens_brain.py
    writes it at 04:55 UTC, this engine consumes it at 06:00 and 12:00. Kept as
    a file read rather than an in-process call so a failed/absent thesis
    degrades to ('neutral', 50) exactly as it did under Jarvis, instead of
    taking the regime briefing down with it.
    """
    try:
        with open(MARKET_BIAS, 'r') as f:
            bias_data = json.load(f)
        assets = bias_data.get('assets', bias_data)
        for key in LENS_KEYS.get(instrument, [instrument]):
            if key in assets:
                entry = assets[key]
                if isinstance(entry, dict):
                    return entry.get('direction', 'neutral').lower(), float(entry.get('confidence', 50))
        # market_bias.json's live schema is a `pairs` LIST, not an asset map.
        for p in bias_data.get('pairs', []) or []:
            if not isinstance(p, dict):
                continue
            if p.get('symbol') in LENS_KEYS.get(instrument, [instrument]):
                return (p.get('bias', 'neutral') or 'neutral').lower(), float(p.get('confidence', 50))
    except Exception as e:
        logging.warning(f"read_lens_bias({instrument}): {e}")
    return 'neutral', 50.0


# ─────────────────────────────────────────────────────────────────────────────
# TIME-BASED EDGE MAPPING
# ─────────────────────────────────────────────────────────────────────────────
# Retained verbatim from Jarvis's strategy_engine.py. deep_backtest.py imported
# build_edge_map from there; it now imports from here (see deep_backtest.py).

def build_edge_map(candles_m15_90d, instrument):
    """Time-of-day win-rate map. Top 3 M15 windows with >52% directional bias."""
    slot_stats = {}
    for candle in candles_m15_90d:
        try:
            ts = datetime.fromisoformat(candle['time'].replace('Z', '+00:00'))
            slot = (ts.hour, ts.minute)
            if slot not in slot_stats:
                slot_stats[slot] = {'bullish': 0, 'bearish': 0, 'total': 0}
            slot_stats[slot]['total'] += 1
            if candle['close'] > candle['open']:
                slot_stats[slot]['bullish'] += 1
            else:
                slot_stats[slot]['bearish'] += 1
        except Exception:
            continue
    results = []
    for (hour, minute), stats in slot_stats.items():
        total = stats['total']
        if total < 10:
            continue
        bull_rate = stats['bullish'] / total
        bear_rate = stats['bearish'] / total
        if bull_rate >= bear_rate:
            edge, win_rate = 'bullish', bull_rate
        else:
            edge, win_rate = 'bearish', bear_rate
        if win_rate > 0.52:
            end_hour = hour + (minute + 15) // 60
            end_minute = (minute + 15) % 60
            results.append({
                'window':   f"{hour:02d}:{minute:02d}-{end_hour:02d}:{end_minute:02d}",
                'edge':     edge,
                'win_rate': round(win_rate * 100, 1),
                'samples':  total,
                'slot':     (hour, minute),
            })
    results.sort(key=lambda x: x['win_rate'], reverse=True)
    return results[:3]


def is_in_top_window(top_windows, now_utc=None):
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    for entry in top_windows:
        try:
            start_str, end_str = entry['window'].split('-')
            sh, sm = int(start_str[:2]), int(start_str[3:])
            eh, em = int(end_str[:2]), int(end_str[3:])
            window_start = now_utc.replace(hour=sh, minute=sm, second=0, microsecond=0)
            window_end = now_utc.replace(hour=eh, minute=em, second=0, microsecond=0)
            if window_start <= now_utc < window_end:
                return True, entry
        except Exception:
            continue
    return False, None


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-TIMEFRAME CONVERGENCE
# ─────────────────────────────────────────────────────────────────────────────
# Jarvis's brief (agents/strategist/CLAUDE.md, "Multi-Timeframe Convergence")
# defined this as four components:
#     1. EMA alignment H4 + Daily (all same direction)
#     2. Price vs 50 EMA on H4
#     3. ADR regime (normal vs extreme)
#     4. Lens macro bias alignment
#
# The ORIGINAL 0-100 implementation was DELETED in the 2026-06-01 engine trim —
# CLAUDE.md decision log: "Removed 0-100 convergence score ... nothing
# downstream consumed them. Blade v5 explicitly ignored the score." So there was
# no code left to move. This is a reconstruction from the four documented
# components above, using functions that survived the trim (ema_alignment,
# calc_adr, read_lens_bias). It is NOT the deleted formula recovered — the
# weights below are new, and are stated openly rather than implied.
#
# It is reported, never enforced. See the OBSERVATION ONLY note at module top.

CONVERGENCE_WEIGHTS = {
    'h4_ema_alignment':   30,   # tactical trend structure
    'daily_ema_alignment': 30,  # higher-timeframe agreement
    'price_vs_h4_ema50':  20,   # location relative to the H4 mean
    'lens_macro_bias':    20,   # macro agreement, scaled by Lens confidence
}


def multi_timeframe_convergence(ind_h4, ind_d, current_price, adr_val,
                                instrument, lens_dir, lens_conf):
    """Score 0-100 for how much the timeframes agree, plus the breakdown.

    Direction is taken from the H4 EMA stack; each other component scores full
    weight when it agrees, zero when it disagrees, half when neutral. ADR is not
    a direction — an extreme reading applies a confidence HAIRCUT instead,
    because a violent tape makes any directional read less reliable.
    """
    h4_align    = ema_alignment(ind_h4)
    daily_align = ema_alignment(ind_d)
    direction   = h4_align if h4_align != 'neutral' else daily_align

    components = {}

    def agree(tag, value):
        if direction == 'neutral' or value == 'neutral':
            return 0.5
        return 1.0 if value == direction else 0.0

    components['h4_ema_alignment'] = {
        'value': h4_align, 'agrees': agree('h4', h4_align),
    }
    components['daily_ema_alignment'] = {
        'value': daily_align, 'agrees': agree('d', daily_align),
    }

    # Price vs H4 EMA50 — above = bullish location, below = bearish location.
    ema50_h4 = ind_h4['ema50'][-1] if ind_h4['ema50'] else None
    if ema50_h4 is None or current_price is None:
        loc = 'neutral'
    else:
        loc = 'bullish' if current_price > ema50_h4 else 'bearish'
    components['price_vs_h4_ema50'] = {
        'value': loc, 'agrees': agree('loc', loc),
        'ema50_h4': round(ema50_h4, 4) if ema50_h4 else None,
    }

    # Lens macro bias — weighted by her own stated confidence, so a 55%-
    # confidence call does not carry the same vote as an 85% one.
    lens_agree = agree('lens', lens_dir)
    conf_scale = max(0.0, min(1.0, (lens_conf or 50) / 100.0))
    components['lens_macro_bias'] = {
        'value': lens_dir, 'confidence': lens_conf,
        'agrees': lens_agree, 'conf_scale': round(conf_scale, 2),
    }

    score = 0.0
    for key, weight in CONVERGENCE_WEIGHTS.items():
        a = components[key]['agrees']
        if key == 'lens_macro_bias':
            # neutral stays at half weight; a directional call is scaled by confidence
            a = 0.5 if lens_dir == 'neutral' else a * conf_scale
        score += weight * a

    # ADR haircut: an extreme-range tape cuts conviction, it does not flip it.
    adr_ref     = ADR_NORMAL.get(instrument, {})
    adr_extreme = adr_ref.get('extreme')
    adr_state   = 'unknown'
    if adr_val is not None and adr_extreme:
        if adr_val > adr_extreme:
            adr_state = 'extreme'
            score *= 0.75
        elif adr_val < adr_ref.get('min', 0):
            adr_state = 'compressed'
            score *= 0.90
        else:
            adr_state = 'normal'
    components['adr_regime'] = {'value': adr_state, 'adr': adr_val}

    score = round(max(0.0, min(100.0, score)), 1)

    if score >= 75:
        label = 'strong'
    elif score >= 55:
        label = 'moderate'
    elif score >= 35:
        label = 'weak'
    else:
        label = 'conflicted'

    return {
        'score':      score,
        'label':      label,
        'direction':  direction,
        'components': components,
        'note':       'Observation only — never gates a trade (CLAUDE.md Rule #6).',
    }


# ─────────────────────────────────────────────────────────────────────────────
# MONTE CARLO (post-hoc on recent agent trades)
# ─────────────────────────────────────────────────────────────────────────────

def monte_carlo(trade_results, n_simulations=10000, initial_balance=2000.0):
    if len(trade_results) < 5:
        return {
            'error': 'insufficient trade history (need ≥5 trades)',
            'n_trades': len(trade_results),
            'median_pnl': '$0', 'worst_case_5pct': 'N/A', 'best_case_95pct': 'N/A',
            'ruin_probability': 'N/A', 'drawdown_20pct_prob': 'N/A',
            'max_consecutive_losses': 0,
        }
    final_pnls, max_drawdowns, max_consec_loss = [], [], []
    for _ in range(n_simulations):
        sim_trades = random.sample(trade_results, len(trade_results))
        balance = peak = initial_balance
        max_dd = 0.0
        consec_loss = max_consec = 0
        for pnl in sim_trades:
            balance += pnl
            peak = max(peak, balance)
            dd = (peak - balance) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
            if pnl < 0:
                consec_loss += 1
                max_consec = max(max_consec, consec_loss)
            else:
                consec_loss = 0
        final_pnls.append(balance - initial_balance)
        max_drawdowns.append(max_dd)
        max_consec_loss.append(max_consec)
    final_pnls.sort()
    max_drawdowns.sort()
    p5_pnl = final_pnls[int(0.05 * n_simulations)]
    p50_pnl = final_pnls[int(0.50 * n_simulations)]
    p95_pnl = final_pnls[int(0.95 * n_simulations)]
    ruin_prob = sum(1 for dd in max_drawdowns if dd > 0.50) / n_simulations * 100
    dd20_prob = sum(1 for dd in max_drawdowns if dd > 0.20) / n_simulations * 100
    fmt = lambda v: f"+${v:.0f}" if v >= 0 else f"-${abs(v):.0f}"
    return {
        'n_trades': len(trade_results),
        'n_simulations': n_simulations,
        'median_pnl': fmt(p50_pnl),
        'worst_case_5pct': fmt(p5_pnl),
        'best_case_95pct': fmt(p95_pnl),
        'ruin_probability': f"{ruin_prob:.1f}%",
        'drawdown_20pct_prob': f"{dd20_prob:.1f}%",
        'max_consecutive_losses': round(mean(max_consec_loss)),
    }


def load_recent_trades(lookback_days=30):
    try:
        with open(TRADES_JSON) as f:
            trades = json.load(f)
        if isinstance(trades, dict):
            trades = trades.get('trades', [])
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        results = []
        for t in trades:
            if t.get('result') in ('no_trade', 'Pending'):
                continue
            try:
                ts = datetime.fromisoformat(t['timestamp'].replace('Z', '+00:00'))
                if ts < cutoff:
                    continue
            except Exception:
                pass
            pnl = t.get('pnl_usd', t.get('pnl', 0))
            if pnl is not None:
                results.append(float(pnl))
        return results
    except Exception as e:
        logging.warning(f"load_recent_trades: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# INSTRUMENT ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyse_instrument(instrument, with_edge_map=True):
    logging.info(f"Analysing {instrument}...")
    print(f"\n  ── {instrument} ──")

    data = {}
    for tf in ['M15', 'H1', 'H4', 'D']:
        count = 500 if tf == 'M15' else 200
        candles = fetch_candles(instrument, tf, count)
        if not candles:
            print(f"    [{tf}] No data — skipping {instrument}")
            return {'regime': 'unknown', 'notes': f'Data unavailable for {tf}'}
        data[tf] = {'candles': candles, 'indicators': calc_indicators(candles)}
        print(f"    [{tf}] {len(candles)} candles loaded")

    adr_val = calc_adr(data['D']['candles'], period=10)
    print(f"    ADR(10d): {adr_val:.1f}" if adr_val else "    ADR: unavailable")

    regime = detect_regime(
        data['H4']['candles'], data['D']['candles'],
        data['H4']['indicators'], adr_val, instrument,
    )

    bias = ema_alignment(data['H4']['indicators'])
    lens_dir, lens_conf = read_lens_bias(instrument)
    current_price = data['M15']['candles'][-1]['close'] if data['M15']['candles'] else None

    convergence = multi_timeframe_convergence(
        data['H4']['indicators'], data['D']['indicators'],
        current_price, adr_val, instrument, lens_dir, lens_conf,
    )

    # The edge map needs a DEEP M15 series, not the 500 bars the regime read
    # uses. build_edge_map discards any time slot with <10 samples, and 500 M15
    # bars is ~5 days — roughly 5 samples per slot, so every slot is discarded
    # and the map comes back empty. Jarvis passed it a 90-day series (that is
    # what the `candles_m15_90d` parameter name means); deep_backtest.py fetches
    # its own. 5000 bars ≈ 52 trading days ≈ 50 samples per slot.
    edge_map = []
    if with_edge_map:
        deep_m15 = fetch_candles(instrument, 'M15', EDGE_MAP_CANDLES)
        if len(deep_m15) < EDGE_MAP_MIN_CANDLES:
            print(f"    Edge map: skipped — only {len(deep_m15)} M15 bars "
                  f"(need ≥{EDGE_MAP_MIN_CANDLES} for ≥10 samples/slot)")
        else:
            edge_map = build_edge_map(deep_m15, instrument)
    in_window, active_window = is_in_top_window(edge_map)

    print(f"    Regime: {regime.upper()} | Bias: {bias} | Lens: {lens_dir} {lens_conf:.0f}%")
    print(f"    Convergence: {convergence['score']}/100 ({convergence['label']}, "
          f"{convergence['direction']})")
    if edge_map:
        print(f"    Edge map: " + ", ".join(
            f"{w['window']} {w['edge'][:4]} {w['win_rate']}%" for w in edge_map))
        if in_window:
            print(f"    ⏱  Currently inside top window {active_window['window']}")

    # ⚠️  The first six keys are the frozen contract. Do not rename or remove.
    return {
        'regime':          regime,
        'bias':            bias,
        'lens_bias':       lens_dir,
        'lens_confidence': lens_conf,
        'adr':             round(adr_val, 1) if adr_val else None,
        'current_price':   round(current_price, 4) if current_price else None,
        # ── additive (absorbed from Jarvis) ──
        'convergence':     convergence,
        'edge_map':        edge_map,
        'in_top_window':   in_window,
        'active_window':   active_window,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_analysis(instruments=None, run_monte_carlo=True, with_edge_map=True):
    if instruments is None:
        instruments = ALL_INSTRUMENTS

    now = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"LENS — Pre-Session Regime Briefing  (absorbed from Jarvis)")
    print(f"UTC: {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"Instruments: {instruments}")
    print(f"{'='*60}")

    hub_post(AGENT_NAME, "status",
             f"Regime briefing starting: {', '.join(instruments)}",
             tags=["briefing", "regime"])

    instrument_results = {}
    for inst in instruments:
        try:
            instrument_results[inst] = analyse_instrument(inst, with_edge_map=with_edge_map)
        except Exception as e:
            logging.error(f"analyse_instrument({inst}): {e}")
            instrument_results[inst] = {'regime': 'unknown', 'notes': f'failed: {e}'}

    mc_result = {}
    if run_monte_carlo:
        print(f"\n  Running Monte Carlo (10,000 simulations) on recent trade P&L...")
        recent_trades = load_recent_trades(lookback_days=30)
        if recent_trades:
            mc_result = monte_carlo(recent_trades, n_simulations=10000)
            print(f"    Median P&L: {mc_result['median_pnl']} | 5th%: {mc_result['worst_case_5pct']} | Ruin: {mc_result['ruin_probability']}")
        else:
            mc_result = {'note': 'No recent trades for Monte Carlo'}

    regimes = [r.get('regime', 'ranging') for r in instrument_results.values()
               if r.get('regime') and r.get('regime') != 'unknown']
    overall_regime = max(set(regimes), key=regimes.count) if regimes else 'ranging'

    conv_scores = [r['convergence']['score'] for r in instrument_results.values()
                   if isinstance(r.get('convergence'), dict)]
    overall_conv = round(mean(conv_scores), 1) if conv_scores else None

    output = {
        'updated':     now.isoformat(),
        'regime':      overall_regime,
        'instruments': instrument_results,
        'monte_carlo': mc_result,
        # ── additive ──
        'convergence_avg': overall_conv,
        'produced_by':     'lens/lens_regime.py (absorbed from strategist/Jarvis 2026-07-25)',
    }

    os.makedirs(DASHBOARD_DIR, exist_ok=True)
    with open(STRATEGY_REC, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\n  Written → {STRATEGY_REC}")

    lines = [f"Regime briefing | Overall: {overall_regime.upper()}"]
    for inst, r in instrument_results.items():
        if r.get('regime', 'unknown') != 'unknown':
            conv = r.get('convergence', {})
            lines.append(
                f"  {inst}: {r['regime'].upper()} | bias={r.get('bias','neutral')} | "
                f"lens={r.get('lens_bias','neutral')} {r.get('lens_confidence',50):.0f}% | "
                f"conv={conv.get('score','-')}/100 {conv.get('label','')}"
            )
    if mc_result.get('median_pnl'):
        lines.append(f"MC: median={mc_result['median_pnl']} ruin={mc_result['ruin_probability']}")
    hub_post(AGENT_NAME, "briefing", "\n".join(lines), tags=["briefing", "regime"])

    print(f"\n{'='*60}")
    print(f"Briefing complete. Overall regime: {overall_regime.upper()}"
          + (f" | convergence {overall_conv}/100" if overall_conv is not None else ""))
    print(f"{'='*60}\n")
    return output


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    run_mc = '--monte-carlo' in sys.argv or '--mc' in sys.argv
    no_edge = '--no-edge-map' in sys.argv
    inst_arg = [a for a in sys.argv[1:] if not a.startswith('--')]
    instruments = [i.upper() for i in inst_arg] if inst_arg else ALL_INSTRUMENTS
    run_analysis(instruments, run_monte_carlo=run_mc, with_edge_map=not no_edge)
