#!/usr/bin/env python3
"""
Strategy Engine — JCF HQ Strategist
2026-03-20

Runs pre-session analysis for all instruments:
  1. Pull 200 candles across M15, H1, H4, D from OANDA (+ BTC from Binance)
  2. Calculate indicators: EMA 9/20/21/50, Bollinger Bands, ATR, ADR
  3. Build time-based edge map (best 15m windows per instrument)
  4. Score each instrument 0–100 via multi-timeframe convergence
  5. Detect market regime (trending / ranging / compressed / volatile)
  6. Run Monte Carlo on recent trade history
  7. Write strategy_recommendation.json

Usage:
  python3 strategy_engine.py                 # all instruments
  python3 strategy_engine.py SPX500_USD      # single instrument
  python3 strategy_engine.py --monte-carlo   # include full Monte Carlo pass
"""

import json
import logging
import math
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

AGENT_NAME    = "strategist"
DASHBOARD_DIR = "/root/.openclaw/dashboard"
STRATEGY_REC  = f"{DASHBOARD_DIR}/strategy_recommendation.json"
MARKET_BIAS   = f"{DASHBOARD_DIR}/market_bias.json"
TRADES_JSON   = f"{DASHBOARD_DIR}/agent_trades.json"

logging.basicConfig(
    filename='/root/.openclaw/agents/strategist/strategist.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

with open('/root/.openclaw/agents/main/agent/auth-profiles.json') as f:
    _auth = json.load(f)
_creds = _auth['profiles']['oanda:default']
client = API(access_token=_creds['key'], environment='practice')

# Instruments: OANDA instruments + BTC (handled separately via Binance)
OANDA_INSTRUMENTS = ['SPX500_USD', 'DE30_EUR', 'XAU_USD']
ALL_INSTRUMENTS   = ['SPX500_USD', 'DE30_EUR', 'XAU_USD', 'BTC_USD']

# Granularity map: human label → OANDA granularity code
GRANULARITY = {
    'M15': 'M15',
    'H1':  'H1',
    'H4':  'H4',
    'D':   'D',
}

# ADR normal ranges per instrument (points / price units)
ADR_NORMAL = {
    'SPX500_USD': {'min': 15,  'max': 120,  'extreme': 180},
    'DE30_EUR':   {'min': 50,  'max': 400,  'extreme': 600},
    'XAU_USD':    {'min': 8,   'max': 80,   'extreme': 120},
    'BTC_USD':    {'min': 500, 'max': 5000, 'extreme': 7500},
}

# Round-number proximity thresholds (price units)
ROUND_NUMBER_PROXIMITY = {
    'SPX500_USD': 50,
    'DE30_EUR':   100,
    'XAU_USD':    25,
    'BTC_USD':    1000,
}

# Lens bias keys per instrument
LENS_KEYS = {
    'SPX500_USD': ['SPX500_USD', 'US100'],
    'DE30_EUR':   ['DE30_EUR', 'DE40_EUR', 'DE40'],
    'XAU_USD':    ['XAU/USD', 'XAU_USD'],
    'BTC_USD':    ['BTC/USDT', 'BTC_USDT', 'BTC/USD'],
}

# Minimum convergence score to recommend TRADE
TRADE_THRESHOLD = 70

# ─────────────────────────────────────────────────────────────────────────────
# OANDA DATA HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_oanda_candles(instrument, granularity, count=200):
    """Fetch up to `count` candles from OANDA. Returns list of dicts with
    keys: time, open, high, low, close, volume."""
    try:
        r = InstrumentsCandles(instrument, params={
            'granularity': granularity,
            'count':       count,
            'price':       'M',
        })
        client.request(r)
        raw = r.response.get('candles', [])
        candles = []
        for c in raw:
            if not c.get('complete', True):
                continue
            m = c['mid']
            candles.append({
                'time':   c['time'],
                'open':   float(m['o']),
                'high':   float(m['h']),
                'low':    float(m['l']),
                'close':  float(m['c']),
                'volume': int(c.get('volume', 0)),
            })
        return candles
    except Exception as e:
        logging.error(f"fetch_oanda_candles({instrument},{granularity}): {e}")
        return []


def fetch_btc_candles(timeframe_str, count=200):
    """Fetch BTC/USDT candles from Binance public API (no auth needed)."""
    try:
        import ccxt
        binance = ccxt.binance({'enableRateLimit': True})
        tf_map  = {'M15': '15m', 'H1': '1h', 'H4': '4h', 'D': '1d'}
        tf      = tf_map.get(timeframe_str, '1h')
        raw     = binance.fetch_ohlcv('BTC/USDT', tf, limit=count)
        candles = []
        for bar in raw:
            ts, o, h, l, c, v = bar
            candles.append({
                'time':   datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
                'open':   float(o),
                'high':   float(h),
                'low':    float(l),
                'close':  float(c),
                'volume': float(v),
            })
        return candles
    except Exception as e:
        logging.error(f"fetch_btc_candles({timeframe_str}): {e}")
        return []


def fetch_candles(instrument, timeframe, count=200):
    """Unified candle fetcher."""
    if instrument == 'BTC_USD':
        return fetch_btc_candles(timeframe, count)
    return fetch_oanda_candles(instrument, GRANULARITY[timeframe], count)


# ─────────────────────────────────────────────────────────────────────────────
# INDICATOR CALCULATIONS
# ─────────────────────────────────────────────────────────────────────────────

def ema(prices, period):
    """Exponential moving average. Returns list same length as prices (NaN-padded)."""
    if len(prices) < period:
        return [None] * len(prices)
    k  = 2.0 / (period + 1)
    result = [None] * len(prices)
    # seed with simple MA
    result[period - 1] = mean(prices[:period])
    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1 - k)
    return result


def bollinger_bands(closes, period=20, std_dev=2.0):
    """Returns (upper, middle, lower) as lists."""
    upper  = [None] * len(closes)
    middle = [None] * len(closes)
    lower  = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        mu  = mean(window)
        sd  = stdev(window) if len(window) > 1 else 0
        middle[i] = mu
        upper[i]  = mu + std_dev * sd
        lower[i]  = mu - std_dev * sd
    return upper, middle, lower


def atr(candles, period=14):
    """Average True Range. Returns list (None for first period-1 elements)."""
    trs = [None]
    for i in range(1, len(candles)):
        h, l, pc = candles[i]['high'], candles[i]['low'], candles[i - 1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    result = [None] * len(candles)
    if len(trs) < period + 1:
        return result
    # seed
    result[period] = mean([t for t in trs[1:period + 1] if t is not None])
    for i in range(period + 1, len(candles)):
        if trs[i] is not None and result[i - 1] is not None:
            result[i] = (result[i - 1] * (period - 1) + trs[i]) / period
    return result


def calc_adr(daily_candles, period=10):
    """Average Daily Range over last `period` days."""
    completed = [c for c in daily_candles if c]
    if len(completed) < period:
        return None
    ranges = [c['high'] - c['low'] for c in completed[-period:]]
    return mean(ranges)


def calc_indicators(candles):
    """Calculate all indicators on a candle list. Returns dict of arrays."""
    closes = [c['close'] for c in candles]
    ind = {
        'ema9':   ema(closes, 9),
        'ema20':  ema(closes, 20),
        'ema21':  ema(closes, 21),
        'ema50':  ema(closes, 50),
        'bb_upper':  None,
        'bb_middle': None,
        'bb_lower':  None,
        'atr14': atr(candles, 14),
    }
    ind['bb_upper'], ind['bb_middle'], ind['bb_lower'] = bollinger_bands(closes)
    return ind


# ─────────────────────────────────────────────────────────────────────────────
# EMA ALIGNMENT ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def ema_alignment(indicators, idx=-1):
    """
    Check whether EMAs are stacked bullish or bearish.
    Returns: 'bullish' | 'bearish' | 'neutral'
    """
    e9  = indicators['ema9'][idx]
    e20 = indicators['ema20'][idx]
    e21 = indicators['ema21'][idx]
    e50 = indicators['ema50'][idx]
    if None in (e9, e20, e21, e50):
        return 'neutral'
    if e9 > e20 > e21 > e50:
        return 'bullish'
    if e9 < e20 < e21 < e50:
        return 'bearish'
    return 'neutral'


def ema_slope_direction(ema_values, lookback=3):
    """Determine slope of an EMA over last `lookback` bars."""
    vals = [v for v in ema_values[-lookback:] if v is not None]
    if len(vals) < 2:
        return 'neutral'
    if vals[-1] > vals[0]:
        return 'bullish'
    if vals[-1] < vals[0]:
        return 'bearish'
    return 'neutral'


# ─────────────────────────────────────────────────────────────────────────────
# FAIR VALUE GAP DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_fvg(candles, current_price, lookback=30):
    """
    Detect if there's an unfilled Fair Value Gap (FVG) near current price
    within the last `lookback` candles.

    FVG: candle[i-1].high < candle[i+1].low (bullish gap)
         candle[i-1].low  > candle[i+1].high (bearish gap)

    Returns: {'present': bool, 'type': 'bullish'|'bearish'|None, 'level': float|None}
    """
    result = {'present': False, 'type': None, 'level': None}
    if len(candles) < 3:
        return result

    window = candles[-lookback:] if len(candles) > lookback else candles
    proximity_pct = 0.003  # within 0.3% of current price

    for i in range(1, len(window) - 1):
        c_prev = window[i - 1]
        c_next = window[i + 1]

        # Bullish FVG: gap up
        if c_prev['high'] < c_next['low']:
            gap_mid = (c_prev['high'] + c_next['low']) / 2
            if abs(gap_mid - current_price) / current_price < proximity_pct:
                result = {'present': True, 'type': 'bullish', 'level': gap_mid}
                return result

        # Bearish FVG: gap down
        if c_prev['low'] > c_next['high']:
            gap_mid = (c_prev['low'] + c_next['high']) / 2
            if abs(gap_mid - current_price) / current_price < proximity_pct:
                result = {'present': True, 'type': 'bearish', 'level': gap_mid}
                return result

    return result


# ─────────────────────────────────────────────────────────────────────────────
# LIQUIDITY LEVEL DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_liquidity_levels(candles_d, candles_h4, current_price, instrument):
    """
    Identify if current price is near a significant liquidity level:
    - Prior day high/low
    - Prior week high/low
    - Round numbers

    Returns: {'present': bool, 'level': float|None, 'type': str}
    """
    proximity = ROUND_NUMBER_PROXIMITY.get(instrument, 50)
    candidates = []

    # Prior day H/L
    if len(candles_d) >= 2:
        prior_day = candles_d[-2]
        candidates.append(('prior_day_high', prior_day['high']))
        candidates.append(('prior_day_low',  prior_day['low']))

    # Prior H4 session high/low (last 6 bars = ~24h)
    if len(candles_h4) >= 6:
        h4_window = candles_h4[-6:]
        candidates.append(('h4_high', max(c['high'] for c in h4_window)))
        candidates.append(('h4_low',  min(c['low']  for c in h4_window)))

    # Round number check
    rn_step = ROUND_NUMBER_PROXIMITY[instrument] if instrument in ROUND_NUMBER_PROXIMITY else 50
    nearest_round = round(current_price / rn_step) * rn_step
    if abs(nearest_round - current_price) <= proximity * 0.5:
        candidates.append(('round_number', nearest_round))

    for label, level in candidates:
        if abs(level - current_price) <= proximity:
            return {'present': True, 'level': level, 'type': label}

    return {'present': False, 'level': None, 'type': ''}


# ─────────────────────────────────────────────────────────────────────────────
# BOLLINGER BAND SQUEEZE (COMPRESSION DETECTION)
# ─────────────────────────────────────────────────────────────────────────────

def bb_squeeze_ratio(indicators, idx=-1):
    """
    Returns BB bandwidth as ratio of current band width to 20-bar average.
    < 0.5 = strong squeeze, 0.5–0.8 = mild squeeze, > 1.0 = expansion
    """
    upper = indicators['bb_upper']
    lower = indicators['bb_lower']
    mid   = indicators['bb_middle']

    # Current bandwidth
    if upper[idx] is None or lower[idx] is None or mid[idx] is None:
        return 1.0

    cur_bw = upper[idx] - lower[idx]

    # Average bandwidth over last 20 valid readings
    widths = []
    for i in range(max(-40, -len(upper)), 0):
        if upper[i] is not None and lower[i] is not None:
            widths.append(upper[i] - lower[i])
    if not widths or mean(widths) == 0:
        return 1.0

    return cur_bw / mean(widths)


# ─────────────────────────────────────────────────────────────────────────────
# REGIME DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_regime(candles_h4, candles_d, indicators_h4, adr_current, instrument):
    """
    Classify current market regime.

    Returns: 'trending' | 'ranging' | 'compressed' | 'volatile'
    """
    adr_ref = ADR_NORMAL.get(instrument, {})
    adr_max     = adr_ref.get('max', 9999)
    adr_extreme = adr_ref.get('extreme', 99999)

    # VOLATILE: ADR > extreme threshold
    if adr_current and adr_current > adr_extreme:
        return 'volatile'

    # EMA alignment on H4
    h4_align = ema_alignment(indicators_h4)

    # BB squeeze
    squeeze = bb_squeeze_ratio(indicators_h4)

    # ATR trend (expanding or contracting)
    atr_vals = [v for v in indicators_h4['atr14'][-10:] if v is not None]
    atr_expanding = (atr_vals[-1] > atr_vals[0] * 1.1) if len(atr_vals) >= 2 else False

    # HH/LL detection on H4 (last 10 bars)
    if len(candles_h4) >= 10:
        recent = candles_h4[-10:]
        highs  = [c['high'] for c in recent]
        lows   = [c['low']  for c in recent]
        hh     = highs[-1] > highs[0] * 1.003
        ll     = lows[-1]  < lows[0]  * 0.997
        trending_structure = (h4_align == 'bullish' and hh) or (h4_align == 'bearish' and ll)
    else:
        trending_structure = False

    # COMPRESSED: tight BBs + declining ATR
    if squeeze < 0.65 and not atr_expanding:
        return 'compressed'

    # TRENDING: aligned EMAs + price structure
    if h4_align != 'neutral' and trending_structure and atr_expanding:
        return 'trending'

    # Default: RANGING
    return 'ranging'


# ─────────────────────────────────────────────────────────────────────────────
# LENS BIAS READER
# ─────────────────────────────────────────────────────────────────────────────

def read_lens_bias(instrument):
    """
    Read market_bias.json and return (direction, confidence) for the instrument.
    Returns: ('bullish'|'bearish'|'neutral', float 0–100)
    """
    try:
        with open(MARKET_BIAS, 'r') as f:
            bias_data = json.load(f)

        assets = bias_data.get('assets', bias_data)
        keys   = LENS_KEYS.get(instrument, [instrument])

        for key in keys:
            if key in assets:
                entry = assets[key]
                if isinstance(entry, dict):
                    direction = entry.get('direction', 'neutral').lower()
                    confidence = float(entry.get('confidence', 50))
                    return direction, confidence
    except Exception as e:
        logging.warning(f"read_lens_bias({instrument}): {e}")

    return 'neutral', 50.0


# ─────────────────────────────────────────────────────────────────────────────
# TIME-BASED EDGE MAP
# ─────────────────────────────────────────────────────────────────────────────

def build_edge_map(candles_m15_90d, instrument):
    """
    Analyze every 15-minute window slot across 90 days of M15 data.
    For each (hour, minute) slot, calculate:
      - How many candles started in that window
      - Directional win rate (bullish = close > open)

    Returns: list of top-3 dicts:
      {'window': 'HH:MM-HH:MM', 'edge': 'bullish'|'bearish', 'win_rate': float}
    """
    slot_stats = {}  # key: (hour, minute) → {'bullish': int, 'bearish': int, 'total': int}

    for candle in candles_m15_90d:
        try:
            # Parse UTC time from ISO string
            ts_str = candle['time']
            ts     = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            slot   = (ts.hour, ts.minute)

            if slot not in slot_stats:
                slot_stats[slot] = {'bullish': 0, 'bearish': 0, 'total': 0}

            slot_stats[slot]['total'] += 1
            if candle['close'] > candle['open']:
                slot_stats[slot]['bullish'] += 1
            else:
                slot_stats[slot]['bearish'] += 1
        except Exception:
            continue

    # Calculate win rates and directional bias
    results = []
    for (hour, minute), stats in slot_stats.items():
        total = stats['total']
        if total < 10:  # need enough samples
            continue

        bull_rate = stats['bullish'] / total
        bear_rate = stats['bearish'] / total

        # Edge = whichever direction dominates
        if bull_rate >= bear_rate:
            edge     = 'bullish'
            win_rate = bull_rate
        else:
            edge     = 'bearish'
            win_rate = bear_rate

        # Only include if meaningfully directional (>52% win rate)
        if win_rate > 0.52:
            end_hour   = hour + (minute + 15) // 60
            end_minute = (minute + 15) % 60
            window_str = f"{hour:02d}:{minute:02d}-{end_hour:02d}:{end_minute:02d}"
            results.append({
                'window':   window_str,
                'edge':     edge,
                'win_rate': round(win_rate * 100, 1),
                'samples':  total,
                'slot':     (hour, minute),
            })

    # Sort by win rate descending, take top 3
    results.sort(key=lambda x: x['win_rate'], reverse=True)
    return results[:3]


def is_in_top_window(top_windows, now_utc=None):
    """Check if current UTC time falls within one of the top windows."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    for entry in top_windows:
        try:
            start_str, end_str = entry['window'].split('-')
            sh, sm = int(start_str[:2]), int(start_str[3:])
            eh, em = int(end_str[:2]),   int(end_str[3:])
            window_start = now_utc.replace(hour=sh, minute=sm, second=0, microsecond=0)
            window_end   = now_utc.replace(hour=eh, minute=em, second=0, microsecond=0)
            if window_start <= now_utc < window_end:
                return True, entry
        except Exception:
            continue
    return False, None


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-TIMEFRAME CONVERGENCE SCORE
# ─────────────────────────────────────────────────────────────────────────────

def score_instrument(instrument, data, top_windows):
    """
    Score an instrument 0–100 based on multi-timeframe convergence.

    data: dict with keys 'M15', 'H1', 'H4', 'D' — each a dict with
          'candles' and 'indicators'

    Returns: (score: int, details: dict, bias_direction: str)
    """
    score   = 0
    details = {}

    candles_m15 = data['M15']['candles']
    candles_h1  = data['H1']['candles']
    candles_h4  = data['H4']['candles']
    candles_d   = data['D']['candles']
    ind_m15     = data['M15']['indicators']
    ind_h1      = data['H1']['indicators']
    ind_h4      = data['H4']['indicators']
    ind_d       = data['D']['indicators']

    if not candles_h4 or not candles_d:
        return 0, {'error': 'insufficient data'}, 'neutral'

    current_price = candles_m15[-1]['close'] if candles_m15 else candles_h4[-1]['close']

    # ── 1. EMA alignment on H4 and Daily (+20) ──────────────────────────────
    h4_align = ema_alignment(ind_h4)
    d_align  = ema_alignment(ind_d)

    if h4_align == d_align and h4_align != 'neutral':
        score += 20
        details['ema_h4_daily'] = f'+20 aligned {h4_align}'
    elif h4_align != 'neutral' or d_align != 'neutral':
        score += 8
        details['ema_h4_daily'] = f'+8 partial ({h4_align}/{d_align})'
    else:
        details['ema_h4_daily'] = '0 flat'

    ema_direction = h4_align if h4_align != 'neutral' else d_align

    # ── 2. EMA alignment on H1 and M15 with HTF (+15) ───────────────────────
    h1_align  = ema_alignment(ind_h1)
    m15_align = ema_alignment(ind_m15)

    if h1_align == ema_direction and m15_align == ema_direction and ema_direction != 'neutral':
        score += 15
        details['ema_h1_m15'] = f'+15 all aligned {ema_direction}'
    elif h1_align == ema_direction and ema_direction != 'neutral':
        score += 8
        details['ema_h1_m15'] = f'+8 H1 aligned'
    else:
        details['ema_h1_m15'] = '0 diverged'

    # ── 3. Price vs 50 EMA on H4 (+10) ──────────────────────────────────────
    e50_h4 = ind_h4['ema50'][-1]
    if e50_h4 is not None:
        if ema_direction == 'bullish' and current_price > e50_h4:
            score += 10
            details['price_vs_50ema'] = f'+10 above 50EMA ({e50_h4:.1f})'
        elif ema_direction == 'bearish' and current_price < e50_h4:
            score += 10
            details['price_vs_50ema'] = f'+10 below 50EMA ({e50_h4:.1f})'
        else:
            details['price_vs_50ema'] = f'0 wrong side of 50EMA'
    else:
        details['price_vs_50ema'] = '0 no data'

    # ── 4. Fair Value Gap near price (+10) ───────────────────────────────────
    fvg_m15 = detect_fvg(candles_m15, current_price, lookback=40)
    fvg_h1  = detect_fvg(candles_h1,  current_price, lookback=20)
    fvg     = fvg_m15 if fvg_m15['present'] else fvg_h1

    if fvg['present'] and fvg.get('type') == ema_direction:
        score += 10
        details['fvg'] = f"+10 {fvg['type']} FVG @ {fvg.get('level', ''):.2f}"
    elif fvg['present']:
        score += 4
        details['fvg'] = f"+4 FVG present (counter-trend {fvg['type']})"
    else:
        details['fvg'] = '0 no FVG'

    # ── 5. Liquidity level nearby (+10) ─────────────────────────────────────
    liq = detect_liquidity_levels(candles_d, candles_h4, current_price, instrument)
    if liq['present']:
        score += 10
        details['liquidity'] = f"+10 {liq['type']} @ {liq.get('level', ''):.2f}"
    else:
        details['liquidity'] = '0 no nearby level'

    # ── 6. Lens bias alignment (+15) ────────────────────────────────────────
    lens_dir, lens_conf = read_lens_bias(instrument)
    if lens_conf >= 65 and lens_dir == ema_direction:
        score += 15
        details['lens'] = f'+15 {lens_dir} {lens_conf:.0f}%'
    elif lens_conf >= 55 and lens_dir == ema_direction:
        score += 8
        details['lens'] = f'+8 {lens_dir} {lens_conf:.0f}%'
    else:
        details['lens'] = f'0 lens={lens_dir} {lens_conf:.0f}% (no alignment)'

    # ── 7. ADR regime check (+10) ────────────────────────────────────────────
    adr_val = calc_adr(candles_d, period=10)
    adr_cfg = ADR_NORMAL.get(instrument, {})
    adr_min     = adr_cfg.get('min',     0)
    adr_max     = adr_cfg.get('max',     99999)
    adr_extreme = adr_cfg.get('extreme', 99999)

    if adr_val is not None:
        if adr_min <= adr_val <= adr_max:
            score += 10
            details['adr'] = f'+10 normal ADR={adr_val:.1f}'
        elif adr_val > adr_extreme:
            details['adr'] = f'0 extreme ADR={adr_val:.1f} (skip)'
            score = max(0, score - 5)  # penalise extreme volatility
        else:
            details['adr'] = f'0 abnormal ADR={adr_val:.1f}'
    else:
        details['adr'] = '0 ADR unavailable'
        adr_val = None

    # ── 8. Time window edge (+10) ────────────────────────────────────────────
    in_window, window_entry = is_in_top_window(top_windows)
    if in_window and window_entry:
        score += 10
        details['time_window'] = f"+10 in top window {window_entry['window']} ({window_entry['win_rate']}%)"
    else:
        if top_windows:
            details['time_window'] = f"0 not in top windows ({top_windows[0]['window']}...)"
        else:
            details['time_window'] = '0 edge map not built'

    return min(score, 100), details, ema_direction, adr_val, lens_dir, lens_conf, fvg


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY SELECTOR
# ─────────────────────────────────────────────────────────────────────────────

def select_strategy(regime, ema_direction, fvg, lens_dir, lens_conf, score):
    """
    Choose the best strategy based on regime and convergence signals.

    Returns: (strategy_name, notes)
    """
    if regime == 'volatile':
        return 'skip', 'VOLATILE regime — skip or reduce to minimum size'

    if regime == 'compressed':
        return 'breakout_expansion', 'COMPRESSED — wait for BB expansion breakout'

    if regime == 'trending':
        if lens_conf >= 65 and lens_dir == ema_direction:
            return 'momentum_orb', f'TRENDING + Lens {lens_conf:.0f}% {lens_dir} — momentum ORB'
        return 'orb', f'TRENDING — standard ORB in {ema_direction} direction'

    if regime == 'ranging':
        if fvg.get('present'):
            return 'sweep_fade', 'RANGING + FVG — watch for liquidity sweep fade'
        return 'sweep_fade', 'RANGING — liquidity sweep reversal preferred'

    return 'orb', 'Default: standard ORB'


# ─────────────────────────────────────────────────────────────────────────────
# MONTE CARLO SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

def monte_carlo(trade_results, n_simulations=10000, initial_balance=2000.0):
    """
    Run Monte Carlo simulation on trade P&L results.

    trade_results: list of floats (P&L per trade in $, e.g. [25.5, -15.0, 40.0, ...])
    Returns: dict with statistics
    """
    if len(trade_results) < 5:
        return {
            'error':                  'insufficient trade history (need ≥5 trades)',
            'n_trades':               len(trade_results),
            'median_pnl':             '$0',
            'worst_case_5pct':        'N/A',
            'best_case_95pct':        'N/A',
            'ruin_probability':       'N/A',
            'drawdown_20pct_prob':    'N/A',
            'max_consecutive_losses': 0,
        }

    final_pnls      = []
    max_drawdowns   = []
    max_consec_loss = []

    for _ in range(n_simulations):
        sim_trades   = random.sample(trade_results, len(trade_results))
        balance      = initial_balance
        peak         = initial_balance
        max_dd       = 0.0
        consec_loss  = 0
        max_consec   = 0

        for pnl in sim_trades:
            balance += pnl
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
            if pnl < 0:
                consec_loss += 1
                max_consec   = max(max_consec, consec_loss)
            else:
                consec_loss = 0

        final_pnls.append(balance - initial_balance)
        max_drawdowns.append(max_dd)
        max_consec_loss.append(max_consec)

    final_pnls.sort()
    max_drawdowns.sort()

    p5_pnl  = final_pnls[int(0.05 * n_simulations)]
    p50_pnl = final_pnls[int(0.50 * n_simulations)]
    p95_pnl = final_pnls[int(0.95 * n_simulations)]

    ruin_count    = sum(1 for dd in max_drawdowns if dd > 0.50)
    dd20_count    = sum(1 for dd in max_drawdowns if dd > 0.20)
    ruin_prob     = ruin_count    / n_simulations * 100
    dd20_prob     = dd20_count    / n_simulations * 100
    avg_consec    = mean(max_consec_loss)

    def fmt(v):
        return f"+${v:.0f}" if v >= 0 else f"-${abs(v):.0f}"

    return {
        'n_trades':               len(trade_results),
        'n_simulations':          n_simulations,
        'median_pnl':             fmt(p50_pnl),
        'worst_case_5pct':        fmt(p5_pnl),
        'best_case_95pct':        fmt(p95_pnl),
        'ruin_probability':       f"{ruin_prob:.1f}%",
        'drawdown_20pct_prob':    f"{dd20_prob:.1f}%",
        'max_consecutive_losses': round(avg_consec),
        'approved':               p5_pnl > -(initial_balance * 0.10) and ruin_prob < 5.0,
    }


def load_recent_trades(instrument=None, lookback_days=30):
    """Load recent trade P&L from agent_trades.json."""
    try:
        with open(TRADES_JSON) as f:
            trades = json.load(f)

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        results = []
        for t in trades:
            # Filter by instrument if specified
            if instrument and t.get('pair', '') != instrument:
                continue
            if t.get('result') in ('no_trade', 'Pending'):
                continue
            try:
                ts = datetime.fromisoformat(t['timestamp'].replace('Z', '+00:00'))
                if ts < cutoff:
                    continue
            except Exception:
                pass
            pnl = t.get('pnl_usd', 0)
            if pnl is not None:
                results.append(float(pnl))
        return results
    except Exception as e:
        logging.warning(f"load_recent_trades: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# FULL INSTRUMENT ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyse_instrument(instrument, run_edge_map=True):
    """
    Full analysis pipeline for one instrument.
    Returns a recommendation dict ready for the JSON output.
    """
    logging.info(f"Analysing {instrument}...")
    print(f"\n  ── {instrument} ──")

    # ── Pull multi-timeframe data ────────────────────────────────────────────
    data = {}
    for tf in ['M15', 'H1', 'H4', 'D']:
        count = 500 if tf == 'M15' else 200
        candles = fetch_candles(instrument, tf, count)
        if not candles:
            print(f"    [{tf}] No data — skipping {instrument}")
            return {
                'score':          0,
                'recommendation': 'SKIP',
                'notes':          f'Data unavailable for {tf}',
            }
        indicators = calc_indicators(candles)
        data[tf] = {'candles': candles, 'indicators': indicators}
        print(f"    [{tf}] {len(candles)} candles loaded")

    # ── ADR ──────────────────────────────────────────────────────────────────
    adr_val = calc_adr(data['D']['candles'], period=10)
    print(f"    ADR(10d): {adr_val:.1f}" if adr_val else "    ADR: unavailable")

    # ── Regime detection ─────────────────────────────────────────────────────
    regime = detect_regime(
        data['H4']['candles'],
        data['D']['candles'],
        data['H4']['indicators'],
        adr_val,
        instrument,
    )
    print(f"    Regime: {regime.upper()}")

    # ── Time-based edge map ──────────────────────────────────────────────────
    top_windows = []
    if run_edge_map and len(data['M15']['candles']) >= 100:
        # For full edge map we'd want 90 days; here we use what we have
        top_windows = build_edge_map(data['M15']['candles'], instrument)
        if top_windows:
            print(f"    Top windows: " + ", ".join(
                f"{w['window']} ({w['edge']} {w['win_rate']}%)" for w in top_windows
            ))

    # ── Convergence score ────────────────────────────────────────────────────
    score, details, ema_direction, adr_out, lens_dir, lens_conf, fvg = score_instrument(
        instrument, data, top_windows
    )
    print(f"    Score: {score}/100 | Trend: {ema_direction}")

    # ── Strategy selection ────────────────────────────────────────────────────
    strategy, strategy_notes = select_strategy(
        regime, ema_direction, fvg, lens_dir, lens_conf, score
    )

    # ── Current price ────────────────────────────────────────────────────────
    current_price = data['M15']['candles'][-1]['close'] if data['M15']['candles'] else None

    # ── Best window string ────────────────────────────────────────────────────
    best_window = top_windows[0]['window'] if top_windows else 'unknown'
    if strategy == 'orb':
        # For ORB, prefer known session open windows
        session_open_windows = {'SPX500_USD': '13:30-14:15', 'DE30_EUR': '08:00-08:15',
                                 'XAU_USD': '13:30-14:00', 'BTC_USD': '13:30-14:15'}
        best_window = session_open_windows.get(instrument, best_window)

    recommendation = 'TRADE' if score >= TRADE_THRESHOLD and strategy != 'skip' else 'SKIP'

    result = {
        'score':           score,
        'strategy':        strategy,
        'bias':            ema_direction,
        'regime':          regime,
        'best_window':     best_window,
        'ema_alignment':   ema_direction,
        'fvg_present':     fvg.get('present', False),
        'lens_bias':       f"{lens_dir} {lens_conf:.0f}%",
        'adr':             round(adr_val, 1) if adr_val else None,
        'recommendation':  recommendation,
        'notes':           strategy_notes,
        'score_breakdown': details,
        'top_windows':     [{'window': w['window'], 'edge': w['edge'],
                             'win_rate': w['win_rate']} for w in top_windows],
    }

    print(f"    → {recommendation} | {strategy.upper()} | {ema_direction}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_analysis(instruments=None, run_monte_carlo=True):
    """
    Full pre-session analysis pass.
    Writes results to strategy_recommendation.json.
    """
    if instruments is None:
        instruments = ALL_INSTRUMENTS

    now = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"STRATEGIST — Pre-Session Analysis")
    print(f"UTC: {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"Instruments: {instruments}")
    print(f"{'='*60}")

    hub_post(AGENT_NAME, "status",
             f"Strategy analysis starting: {', '.join(instruments)}",
             tags=["analysis", "strategy"])

    instrument_results = {}
    for inst in instruments:
        try:
            result = analyse_instrument(inst)
            instrument_results[inst] = result
        except Exception as e:
            logging.error(f"analyse_instrument({inst}): {e}")
            instrument_results[inst] = {
                'score':          0,
                'recommendation': 'SKIP',
                'notes':          f'Analysis failed: {e}',
            }

    # ── Monte Carlo on overall recent trade history ──────────────────────────
    mc_result = {}
    if run_monte_carlo:
        print(f"\n  Running Monte Carlo (10,000 simulations)...")
        recent_trades = load_recent_trades(lookback_days=30)
        if recent_trades:
            mc_result = monte_carlo(recent_trades, n_simulations=10000)
            approved  = mc_result.get('approved', False)
            print(f"    Median P&L: {mc_result['median_pnl']}")
            print(f"    5th pct:    {mc_result['worst_case_5pct']}")
            print(f"    Ruin prob:  {mc_result['ruin_probability']}")
            print(f"    Approved:   {approved}")
        else:
            mc_result = {'note': 'No recent trades for Monte Carlo'}

    # ── Overall regime (majority vote) ───────────────────────────────────────
    regimes = [r.get('regime', 'ranging') for r in instrument_results.values()
               if r.get('score', 0) > 0]
    overall_regime = max(set(regimes), key=regimes.count) if regimes else 'ranging'

    # ── Build output ─────────────────────────────────────────────────────────
    output = {
        'updated':      now.isoformat(),
        'regime':       overall_regime,
        'instruments':  instrument_results,
        'monte_carlo':  mc_result,
    }

    os.makedirs(DASHBOARD_DIR, exist_ok=True)
    with open(STRATEGY_REC, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n  Written → {STRATEGY_REC}")

    # ── Summary for hub ──────────────────────────────────────────────────────
    trade_recs = [(inst, r['score'], r.get('strategy', 'orb'))
                  for inst, r in instrument_results.items()
                  if r.get('recommendation') == 'TRADE']
    skip_recs  = [inst for inst, r in instrument_results.items()
                  if r.get('recommendation') == 'SKIP']

    lines = [f"Strategy analysis complete | Regime: {overall_regime.upper()}"]
    if trade_recs:
        lines.append("TRADE: " + ", ".join(
            f"{i}({s}/100 {st.upper()})" for i, s, st in trade_recs
        ))
    if skip_recs:
        lines.append("SKIP:  " + ", ".join(skip_recs))
    if mc_result.get('median_pnl'):
        lines.append(f"MC: median={mc_result['median_pnl']} ruin={mc_result['ruin_probability']}")

    hub_post(AGENT_NAME, "strategy", "\n".join(lines), tags=["analysis", "strategy"])

    print(f"\n{'='*60}")
    print(f"Analysis complete. Overall regime: {overall_regime.upper()}")
    if trade_recs:
        print(f"TRADE recommendations: {[i for i, s, st in trade_recs]}")
    if skip_recs:
        print(f"SKIP:                  {skip_recs}")
    print(f"{'='*60}\n")

    return output


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    run_mc   = '--monte-carlo' in sys.argv or '--mc' in sys.argv
    inst_arg = [a for a in sys.argv[1:] if not a.startswith('--')]

    if inst_arg:
        instruments = [i.upper() for i in inst_arg]
    else:
        instruments = ALL_INSTRUMENTS

    run_analysis(instruments=instruments, run_monte_carlo=run_mc or True)
