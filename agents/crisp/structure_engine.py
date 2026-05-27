#!/usr/bin/env python3
"""
structure_engine.py — Layer 1: Market Structure Map

Builds and caches the structural map of the BTC market:
  - Support & resistance zones (swing H/L on H4 + H1)
  - Liquidity pools (equal highs/lows → stop clusters)
  - Fair Value Gaps (price imbalances)
  - Fixed Range Volume Profile / POC
  - Higher timeframe trend bias
"""

import json
import logging
import time
from datetime import datetime, timezone
from statistics import mean

from crisp_config import (
    STRUCTURE_MAP_PATH,
    SWING_LOOKBACK, SR_ZONE_CLUSTER_PCT, SR_TOUCH_RADIUS_PCT,
    LIQ_POOL_TOLERANCE, FVG_MIN_SIZE_PCT,
)
from market_data import (
    get_candles_as_dicts, get_current_price, calculate_atr, get_relative_volume
)

# ─────────────────────────────────────────────────────────────────────────────
# SUPPORT & RESISTANCE ZONES
# ─────────────────────────────────────────────────────────────────────────────

def find_swing_highs_lows(candles: list, lookback: int = SWING_LOOKBACK) -> list:
    """
    Find swing highs and lows. A swing high = candle whose high exceeds
    'lookback' candles on each side. Returns a list of level dicts.
    """
    levels = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        c = candles[i]
        # Swing high
        if all(candles[i]['high'] >= candles[j]['high']
               for j in range(i - lookback, i + lookback + 1) if j != i):
            levels.append({
                'price': c['high'],
                'type': 'resistance',
                'index': i,
                'dt': c['dt'],
            })
        # Swing low
        if all(candles[i]['low'] <= candles[j]['low']
               for j in range(i - lookback, i + lookback + 1) if j != i):
            levels.append({
                'price': c['low'],
                'type': 'support',
                'index': i,
                'dt': c['dt'],
            })
    return levels


def _cluster_levels(levels: list, tolerance_pct: float = SR_ZONE_CLUSTER_PCT) -> list:
    """
    Cluster nearby levels into zones. Returns list of zone dicts.
    """
    if not levels:
        return []

    zones = []
    used = set()
    for i, lv in enumerate(levels):
        if i in used:
            continue
        cluster = [lv]
        for j, other in enumerate(levels):
            if j == i or j in used:
                continue
            if (abs(lv['price'] - other['price']) / lv['price']) < tolerance_pct:
                cluster.append(other)
                used.add(j)
        used.add(i)

        prices = [c['price'] for c in cluster]
        zone_price = mean(prices)
        zones.append({
            'price': round(zone_price, 2),
            'range': [round(min(prices) * 0.9995, 2), round(max(prices) * 1.0005, 2)],
            'type': cluster[0]['type'],
            'strength': len(cluster),
            'label': 'major' if len(cluster) >= 3 else 'minor',
            'last_dt': max(c['dt'] for c in cluster).isoformat(),
        })
    return zones


def build_sr_zones(h4_candles: list, h1_candles: list) -> tuple:
    """Returns (support_zones, resistance_zones)."""
    h4_levels = find_swing_highs_lows(h4_candles, lookback=SWING_LOOKBACK)
    h1_levels = find_swing_highs_lows(h1_candles, lookback=SWING_LOOKBACK)

    # Tag timeframe
    for lv in h4_levels:
        lv['timeframe'] = 'H4'
    for lv in h1_levels:
        lv['timeframe'] = 'H1'

    all_levels = h4_levels + h1_levels
    support_raw = [l for l in all_levels if l['type'] == 'support']
    resist_raw = [l for l in all_levels if l['type'] == 'resistance']

    support_zones = _cluster_levels(support_raw)
    resist_zones = _cluster_levels(resist_raw)
    return support_zones, resist_zones


# ─────────────────────────────────────────────────────────────────────────────
# LIQUIDITY POOLS
# ─────────────────────────────────────────────────────────────────────────────

def find_liquidity_pools(candles: list, tolerance_pct: float = LIQ_POOL_TOLERANCE,
                         current_price: float = None) -> list:
    """
    Find clusters of equal highs (buy stops) or equal lows (sell stops).
    These represent liquidity pools where stop orders accumulate.
    """
    pools = []
    highs = [(i, c['high']) for i, c in enumerate(candles)]
    lows = [(i, c['low']) for i, c in enumerate(candles)]

    def find_clusters(price_points, pool_type):
        used = set()
        result = []
        for i, (idx_i, price_i) in enumerate(price_points):
            if i in used:
                continue
            cluster_idx = [i]
            cluster_prices = [price_i]
            for j, (idx_j, price_j) in enumerate(price_points):
                if j == i or j in used:
                    continue
                if abs(price_i - price_j) / price_i < tolerance_pct:
                    cluster_idx.append(j)
                    cluster_prices.append(price_j)
            if len(cluster_prices) >= 2:
                for k in cluster_idx:
                    used.add(k)
                pool_price = mean(cluster_prices)
                # Determine if already swept
                swept = False
                if current_price is not None:
                    if pool_type == 'buy_stops' and current_price > pool_price * 1.001:
                        swept = True
                    elif pool_type == 'sell_stops' and current_price < pool_price * 0.999:
                        swept = True
                result.append({
                    'price': round(pool_price, 2),
                    'type': pool_type,
                    'size': len(cluster_prices),
                    'swept': swept,
                    'timeframe': 'H1',
                })
        return result

    pools.extend(find_clusters(highs, 'buy_stops'))
    pools.extend(find_clusters(lows, 'sell_stops'))
    # Sort by price
    pools.sort(key=lambda x: x['price'])
    return pools


# ─────────────────────────────────────────────────────────────────────────────
# FAIR VALUE GAPS
# ─────────────────────────────────────────────────────────────────────────────

def find_fair_value_gaps(candles: list, timeframe_label: str,
                         current_price: float = None) -> list:
    """
    Detect Fair Value Gaps (3-candle imbalance pattern).

    Bullish FVG: candle[i-1].high < candle[i+1].low
    Bearish FVG: candle[i-1].low  > candle[i+1].high
    """
    gaps = []
    now_ts = time.time()

    for i in range(1, len(candles) - 1):
        prev = candles[i - 1]
        curr = candles[i]
        nxt  = candles[i + 1]

        # Bullish FVG (gap up — price came down to fill expected)
        gap_low  = prev['high']
        gap_high = nxt['low']
        if gap_high > gap_low:
            size_pct = (gap_high - gap_low) / curr['close']
            if size_pct >= FVG_MIN_SIZE_PCT:
                midpoint = (gap_high + gap_low) / 2
                fill_pct = 0
                filled = False
                if current_price is not None:
                    if current_price <= gap_low:
                        fill_pct = 100
                        filled = True
                    elif current_price < gap_high:
                        fill_pct = int((gap_high - current_price) / (gap_high - gap_low) * 100)
                age_hours = (now_ts - nxt['ts'] / 1000) / 3600
                gaps.append({
                    'high': round(gap_high, 2),
                    'low': round(gap_low, 2),
                    'midpoint': round(midpoint, 2),
                    'type': 'bullish',
                    'timeframe': timeframe_label,
                    'age_hours': round(age_hours, 1),
                    'filled': filled,
                    'fill_pct': fill_pct,
                })

        # Bearish FVG (gap down — price came up to fill expected)
        gap_high = prev['low']
        gap_low  = nxt['high']
        if gap_high > gap_low:
            size_pct = (gap_high - gap_low) / curr['close']
            if size_pct >= FVG_MIN_SIZE_PCT:
                midpoint = (gap_high + gap_low) / 2
                fill_pct = 0
                filled = False
                if current_price is not None:
                    if current_price >= gap_high:
                        fill_pct = 100
                        filled = True
                    elif current_price > gap_low:
                        fill_pct = int((current_price - gap_low) / (gap_high - gap_low) * 100)
                age_hours = (now_ts - nxt['ts'] / 1000) / 3600
                gaps.append({
                    'high': round(gap_high, 2),
                    'low': round(gap_low, 2),
                    'midpoint': round(midpoint, 2),
                    'type': 'bearish',
                    'timeframe': timeframe_label,
                    'age_hours': round(age_hours, 1),
                    'filled': filled,
                    'fill_pct': fill_pct,
                })

    # Filter out fully filled, sort newest first (by age)
    gaps = [g for g in gaps if not g['filled']]
    gaps.sort(key=lambda x: x['age_hours'])
    return gaps


# ─────────────────────────────────────────────────────────────────────────────
# FIXED RANGE VOLUME PROFILE / POC
# ─────────────────────────────────────────────────────────────────────────────

def calculate_frvp(candles: list, price_buckets: int = 100) -> dict:
    """
    Build a volume profile by distributing each candle's volume
    evenly across its high-low range, then bucketing into price levels.

    Returns POC, value area high/low, HVN and LVN lists.
    """
    if not candles:
        return {}

    all_highs = [c['high'] for c in candles]
    all_lows = [c['low'] for c in candles]
    price_min = min(all_lows)
    price_max = max(all_highs)
    if price_max <= price_min:
        return {}

    bucket_size = (price_max - price_min) / price_buckets
    volume_profile = [0.0] * price_buckets

    for c in candles:
        candle_range = c['high'] - c['low']
        if candle_range <= 0:
            continue
        # Distribute volume across price buckets spanned by this candle
        low_bucket = int((c['low'] - price_min) / bucket_size)
        high_bucket = int((c['high'] - price_min) / bucket_size)
        low_bucket = max(0, low_bucket)
        high_bucket = min(price_buckets - 1, high_bucket)
        n_buckets = high_bucket - low_bucket + 1
        vol_per_bucket = c['volume'] / n_buckets
        for b in range(low_bucket, high_bucket + 1):
            volume_profile[b] += vol_per_bucket

    # POC = bucket with most volume
    poc_bucket = volume_profile.index(max(volume_profile))
    poc_price = round(price_min + (poc_bucket + 0.5) * bucket_size, 2)

    # Value area: 70% of total volume
    total_vol = sum(volume_profile)
    target_vol = total_vol * 0.70
    sorted_buckets = sorted(range(price_buckets), key=lambda i: volume_profile[i], reverse=True)
    va_buckets = set()
    cumvol = 0
    for b in sorted_buckets:
        va_buckets.add(b)
        cumvol += volume_profile[b]
        if cumvol >= target_vol:
            break

    va_high = round(price_min + (max(va_buckets) + 1) * bucket_size, 2)
    va_low  = round(price_min + min(va_buckets) * bucket_size, 2)

    # High/low volume nodes
    avg_vol = total_vol / price_buckets
    hvn = [round(price_min + (i + 0.5) * bucket_size, 2)
           for i in range(price_buckets) if volume_profile[i] > avg_vol * 1.5]
    lvn = [round(price_min + (i + 0.5) * bucket_size, 2)
           for i in range(price_buckets) if volume_profile[i] < avg_vol * 0.5]

    return {
        'poc': poc_price,
        'value_area_high': va_high,
        'value_area_low': va_low,
        'high_volume_nodes': hvn[:5],
        'low_volume_nodes': lvn[:5],
    }


# ─────────────────────────────────────────────────────────────────────────────
# TREND CONTEXT
# ─────────────────────────────────────────────────────────────────────────────

def _ema(values: list, period: int) -> list:
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    ema = [None] * (period - 1)
    ema.append(sum(values[:period]) / period)
    for v in values[period:]:
        ema.append(ema[-1] * (1 - k) + v * k)
    return ema


def get_trend_context(h4_candles: list) -> dict:
    """
    Determine H4 trend bias using EMAs, structure, and RSI.
    Returns {'direction': 'bullish'|'bearish'|'neutral', 'confidence': 0-100}
    """
    if len(h4_candles) < 55:
        return {'direction': 'neutral', 'confidence': 50}

    closes = [c['close'] for c in h4_candles]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)

    # EMA alignment
    e20 = [e for e in ema20 if e is not None]
    e50 = [e for e in ema50 if e is not None]
    ema_bullish = len(e20) > 0 and len(e50) > 0 and e20[-1] > e50[-1]
    ema_bearish = len(e20) > 0 and len(e50) > 0 and e20[-1] < e50[-1]
    # EMA slope (last 5 values)
    ema20_rising = len(e20) >= 5 and e20[-1] > e20[-5]
    ema50_rising = len(e50) >= 5 and e50[-1] > e50[-5]
    ema20_falling = len(e20) >= 5 and e20[-1] < e20[-5]
    ema50_falling = len(e50) >= 5 and e50[-1] < e50[-5]

    # Structure: recent 20 H4 candles
    recent = h4_candles[-20:]
    highs = [c['high'] for c in recent]
    lows  = [c['low'] for c in recent]
    # Higher highs + higher lows = bullish structure
    hh = highs[-1] > max(highs[:-1])
    hl = lows[-1] > min(lows[:-1]) * 0.998  # slight tolerance
    lh = highs[-1] < max(highs[:-1])
    ll = lows[-1] < min(lows[:-1])

    # RSI(14) on H4
    rsi = _rsi14(closes)

    # Score components
    bull_score = 0
    bear_score = 0
    if ema_bullish:
        bull_score += 30
    if ema_bearish:
        bear_score += 30
    if ema20_rising and ema50_rising:
        bull_score += 20
    if ema20_falling and ema50_falling:
        bear_score += 20
    if hh and hl:
        bull_score += 25
    if lh and ll:
        bear_score += 25
    if rsi > 55:
        bull_score += 15
    elif rsi < 45:
        bear_score += 15

    total = bull_score + bear_score
    if total == 0:
        return {'direction': 'neutral', 'confidence': 50}

    if bull_score > bear_score:
        confidence = min(100, int((bull_score / 100) * 100))
        return {'direction': 'bullish', 'confidence': confidence}
    elif bear_score > bull_score:
        confidence = min(100, int((bear_score / 100) * 100))
        return {'direction': 'bearish', 'confidence': confidence}
    else:
        return {'direction': 'neutral', 'confidence': 50}


def _rsi14(closes: list) -> float:
    period = 14
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i-1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    # Wilder's smoothing
    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * 13 + gains[i]) / 14
        avg_loss = (avg_loss * 13 + losses[i]) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURE MAP BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_structure_map() -> dict:
    """
    Full structure calculation. Fetches all required candles and
    computes all structural levels. Returns the structure_map dict.
    """
    logging.info("Building structure map...")
    try:
        h4 = get_candles_as_dicts('4h', limit=200)
        h1 = get_candles_as_dicts('1h', limit=200)
        m15 = get_candles_as_dicts('15m', limit=200)
        price = get_current_price()

        support_zones, resist_zones = build_sr_zones(h4, h1)

        liq_pools = find_liquidity_pools(h1[-100:], current_price=price)

        fvgs_h4  = find_fair_value_gaps(h4, 'H4', current_price=price)
        fvgs_h1  = find_fair_value_gaps(h1, 'H1', current_price=price)
        fvgs_m15 = find_fair_value_gaps(m15, 'M15', current_price=price)
        # Combine, H4 first (most significant), limit to 10 total
        all_fvgs = (fvgs_h4 + fvgs_h1 + fvgs_m15)[:10]

        # FRVP on the last 24 H1 candles (one day)
        frvp = calculate_frvp(h1[-24:])

        trend = get_trend_context(h4)

        structure_map = {
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'btc_price': price,
            'trend_bias': trend,
            'support_zones': support_zones,
            'resistance_zones': resist_zones,
            'liquidity_pools': liq_pools,
            'fair_value_gaps': all_fvgs,
            'frvp': frvp,
        }

        # Cache to disk
        with open(STRUCTURE_MAP_PATH, 'w') as f:
            json.dump(structure_map, f, indent=2, default=str)

        logging.info(
            f"Structure map built: {len(support_zones)} support zones, "
            f"{len(resist_zones)} resistance zones, "
            f"{len(liq_pools)} liquidity pools, "
            f"{len(all_fvgs)} FVGs, "
            f"POC={frvp.get('poc', 'n/a')}, "
            f"trend={trend['direction']}({trend['confidence']}%)"
        )
        return structure_map

    except Exception as e:
        logging.error(f"build_structure_map failed: {e}")
        # Return last cached map if available
        try:
            with open(STRUCTURE_MAP_PATH) as f:
                cached = json.load(f)
            logging.warning("Using cached structure map after build failure")
            return cached
        except Exception:
            return {}


def load_structure_map() -> dict:
    """Load the most recently saved structure map from disk."""
    try:
        with open(STRUCTURE_MAP_PATH) as f:
            return json.load(f)
    except Exception:
        return {}
