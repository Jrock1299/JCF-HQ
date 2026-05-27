#!/usr/bin/env python3
"""
signal_detector.py — Layer 2: Signal Detection

Detects tradeable patterns using current candle data and the structure map.
Five signal types:
  A. Liquidity sweep reversal (primary)
  B. POC reaction (mean reversion)
  C. Fair Value Gap fill (imbalance)
  D. Support/Resistance reaction
  E. ORB breakout (supplementary, session opens only)
"""

import logging
import uuid
from datetime import datetime, timezone

from market_data import (
    get_candles_as_dicts, get_current_price,
    calculate_atr, get_relative_volume
)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _make_signal(sig_type: str, direction: str, entry: float, sl: float,
                 tp_targets: list, factors: dict, context: str) -> dict:
    """Create a standardised signal dict."""
    raw_score = sum(factors.values())
    return {
        'signal_id':  str(uuid.uuid4()),
        'timestamp':  datetime.now(timezone.utc).isoformat(),
        'type':       sig_type,
        'direction':  direction,
        'entry_price': round(entry, 2),
        'sl_price':   round(sl, 2),
        'tp_targets': [round(t, 2) for t in tp_targets],
        'raw_score':  raw_score,
        'factors':    factors,
        'structure_context': context,
    }


def _near(price_a: float, price_b: float, pct: float = 0.002) -> bool:
    """True if two prices are within 'pct' of each other."""
    return abs(price_a - price_b) / price_b < pct


def _get_structural_tps(direction: str, entry: float, sl: float,
                        structure_map: dict) -> list:
    """
    Find the next 2-3 structural levels in the trade direction as TPs.
    Filters by minimum 1:1 RR. Returns list of TP prices.
    """
    sl_dist = abs(entry - sl)
    tps = []

    if direction == 'long':
        candidates = []
        for z in structure_map.get('resistance_zones', []):
            if z['price'] > entry * 1.001:
                candidates.append(z['price'])
        for lp in structure_map.get('liquidity_pools', []):
            if lp['type'] == 'buy_stops' and lp['price'] > entry and not lp['swept']:
                candidates.append(lp['price'])
        if structure_map.get('frvp', {}).get('poc', 0) > entry:
            candidates.append(structure_map['frvp']['poc'])
        for fvg in structure_map.get('fair_value_gaps', []):
            if fvg['type'] == 'bearish' and fvg['low'] > entry:
                candidates.append(fvg['midpoint'])
        candidates.sort()
        for c in candidates:
            if c - entry >= sl_dist * 1.0:  # at least 1:1
                tps.append(c)
            if len(tps) >= 3:
                break

    else:  # short
        candidates = []
        for z in structure_map.get('support_zones', []):
            if z['price'] < entry * 0.999:
                candidates.append(z['price'])
        for lp in structure_map.get('liquidity_pools', []):
            if lp['type'] == 'sell_stops' and lp['price'] < entry and not lp['swept']:
                candidates.append(lp['price'])
        if structure_map.get('frvp', {}).get('poc', 0) < entry:
            candidates.append(structure_map['frvp']['poc'])
        for fvg in structure_map.get('fair_value_gaps', []):
            if fvg['type'] == 'bullish' and fvg['high'] < entry:
                candidates.append(fvg['midpoint'])
        candidates.sort(reverse=True)
        for c in candidates:
            if entry - c >= sl_dist * 1.0:  # at least 1:1
                tps.append(c)
            if len(tps) >= 3:
                break

    return tps


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL A — LIQUIDITY SWEEP REVERSAL
# ─────────────────────────────────────────────────────────────────────────────

def detect_liquidity_sweep(candles: list, structure_map: dict) -> list:
    """
    Pattern: Price wicks through an unswept liquidity pool, then closes back
    inside the prior range = smart money grabbed stops and reversed.
    """
    signals = []
    if len(candles) < 3:
        return signals

    current_price = candles[-1]['close']
    atr = calculate_atr(candles[-50:], 14) if len(candles) >= 50 else 0

    unswept_pools = [lp for lp in structure_map.get('liquidity_pools', [])
                     if not lp['swept']]

    for pool in unswept_pools:
        pool_price = pool['price']

        # Check most recent candle for the sweep
        c = candles[-1]
        prev_c = candles[-2]

        if pool['type'] == 'sell_stops':
            # Sweep of sell stops (price wicked below, then closed back above)
            if c['low'] < pool_price * (1 - 0.0005) and c['close'] > pool_price:
                sweep_size_pct = (pool_price - c['low']) / pool_price * 100
                direction = 'long'
                entry = c['close']
                sl = c['low'] * 0.9998  # just below the sweep wick

                tps = _get_structural_tps(direction, entry, sl, structure_map)
                if not tps:
                    continue

                factors = {
                    'sweep_into_pool': 20,
                    'sweep_size': min(15, int(sweep_size_pct * 200)),
                    'pool_size': min(10, pool['size'] * 3),
                }
                # Bonus: FVG confluence
                for fvg in structure_map.get('fair_value_gaps', []):
                    if fvg['type'] == 'bullish' and fvg['low'] <= entry <= fvg['high']:
                        factors['fvg_confluence'] = 12
                        break
                # Bonus: trend alignment
                trend = structure_map.get('trend_bias', {})
                if trend.get('direction') == 'bullish':
                    factors['trend_alignment'] = min(15, int(trend.get('confidence', 50) * 0.15))
                # Bonus: volume
                rv = get_relative_volume(candles[-21:])
                if rv > 1.3:
                    factors['volume_confirm'] = 8
                # Multi-timeframe bonus: same level exists on H4
                for z in structure_map.get('support_zones', []):
                    if z.get('timeframe') == 'H4' and _near(pool_price, z['price'], 0.003):
                        factors['multi_timeframe'] = 10
                        break

                ctx = (f"Swept sell_stops at {pool_price:.0f} "
                       f"(pool size={pool['size']}), closed back above. "
                       f"Trend: {trend.get('direction','?')}. "
                       f"Sweep wick: {sweep_size_pct:.2f}%")

                signals.append(_make_signal('liquidity_sweep', direction, entry,
                                            sl, tps, factors, ctx))

        elif pool['type'] == 'buy_stops':
            # Sweep of buy stops (price wicked above, then closed back below)
            if c['high'] > pool_price * (1 + 0.0005) and c['close'] < pool_price:
                sweep_size_pct = (c['high'] - pool_price) / pool_price * 100
                direction = 'short'
                entry = c['close']
                sl = c['high'] * 1.0002

                tps = _get_structural_tps(direction, entry, sl, structure_map)
                if not tps:
                    continue

                factors = {
                    'sweep_into_pool': 20,
                    'sweep_size': min(15, int(sweep_size_pct * 200)),
                    'pool_size': min(10, pool['size'] * 3),
                }
                for fvg in structure_map.get('fair_value_gaps', []):
                    if fvg['type'] == 'bearish' and fvg['low'] <= entry <= fvg['high']:
                        factors['fvg_confluence'] = 12
                        break
                trend = structure_map.get('trend_bias', {})
                if trend.get('direction') == 'bearish':
                    factors['trend_alignment'] = min(15, int(trend.get('confidence', 50) * 0.15))
                rv = get_relative_volume(candles[-21:])
                if rv > 1.3:
                    factors['volume_confirm'] = 8
                for z in structure_map.get('resistance_zones', []):
                    if z.get('timeframe') == 'H4' and _near(pool_price, z['price'], 0.003):
                        factors['multi_timeframe'] = 10
                        break

                ctx = (f"Swept buy_stops at {pool_price:.0f} "
                       f"(pool size={pool['size']}), closed back below. "
                       f"Trend: {trend.get('direction','?')}. "
                       f"Sweep wick: {sweep_size_pct:.2f}%")

                signals.append(_make_signal('liquidity_sweep', direction, entry,
                                            sl, tps, factors, ctx))

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL B — POC REACTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_poc_reaction(candles: list, structure_map: dict) -> list:
    """
    Price approaches POC and shows rejection — expect mean reversion.
    """
    signals = []
    frvp = structure_map.get('frvp', {})
    poc = frvp.get('poc')
    if not poc:
        return signals

    c = candles[-1]
    prev_c = candles[-2] if len(candles) >= 2 else c
    trend = structure_map.get('trend_bias', {})

    # Price within 0.2% of POC
    if not _near(c['close'], poc, 0.002):
        return signals

    # Approaching from below: wick through POC but closed below = rejection (short signal)
    # OR closed above = break through (no signal here, wait for next signal type)
    approaching_from_below = prev_c['close'] < poc and c['close'] < poc
    approaching_from_above = prev_c['close'] > poc and c['close'] > poc

    if approaching_from_below:
        # Rejection candle: high wicked into/above POC, closed below = potential short
        if c['high'] > poc * 0.999 and c['close'] < poc:
            direction = 'short'
            entry = c['close']
            sl = max(c['high'], poc) * 1.001
            tps = _get_structural_tps(direction, entry, sl, structure_map)
            if not tps:
                return signals
            factors = {'poc_reaction': 20}
            if trend.get('direction') == 'bearish':
                factors['trend_alignment'] = min(15, int(trend.get('confidence', 50) * 0.15))
            for z in structure_map.get('resistance_zones', []):
                if _near(poc, z['price'], 0.003):
                    factors['sr_confluence'] = 10
                    break
            rv = get_relative_volume(candles[-21:])
            if rv > 1.2:
                factors['volume_confirm'] = 8
            ctx = f"POC rejection at {poc:.0f} — approached from below, rejected. Trend: {trend.get('direction','?')}"
            signals.append(_make_signal('poc_reaction', direction, entry, sl, tps, factors, ctx))

    elif approaching_from_above:
        # Bounce off POC from above = potential long
        if c['low'] < poc * 1.001 and c['close'] > poc:
            direction = 'long'
            entry = c['close']
            sl = min(c['low'], poc) * 0.999
            tps = _get_structural_tps(direction, entry, sl, structure_map)
            if not tps:
                return signals
            factors = {'poc_reaction': 20}
            if trend.get('direction') == 'bullish':
                factors['trend_alignment'] = min(15, int(trend.get('confidence', 50) * 0.15))
            for z in structure_map.get('support_zones', []):
                if _near(poc, z['price'], 0.003):
                    factors['sr_confluence'] = 10
                    break
            rv = get_relative_volume(candles[-21:])
            if rv > 1.2:
                factors['volume_confirm'] = 8
            ctx = f"POC bounce at {poc:.0f} — approached from above, held. Trend: {trend.get('direction','?')}"
            signals.append(_make_signal('poc_reaction', direction, entry, sl, tps, factors, ctx))

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL C — FAIR VALUE GAP FILL
# ─────────────────────────────────────────────────────────────────────────────

def detect_fvg_fill(candles: list, structure_map: dict) -> list:
    """
    Price enters an unfilled FVG and shows a reaction at the midpoint
    or opposing edge.
    """
    signals = []
    c = candles[-1]
    trend = structure_map.get('trend_bias', {})

    for fvg in structure_map.get('fair_value_gaps', []):
        if fvg['filled']:
            continue

        # Bullish FVG: price came down to fill the gap → expect bounce long
        if fvg['type'] == 'bullish':
            in_gap = fvg['low'] <= c['close'] <= fvg['high']
            at_mid_or_low = c['close'] <= fvg['midpoint'] * 1.001
            # Rejection candle: low into gap, close above midpoint
            if in_gap and c['low'] <= fvg['midpoint'] and c['close'] > fvg['low']:
                direction = 'long'
                entry = c['close']
                sl = fvg['low'] * 0.999
                tps = _get_structural_tps(direction, entry, sl, structure_map)
                if not tps:
                    continue
                tf_weight = {'H4': 20, 'H1': 15, 'M15': 10}.get(fvg['timeframe'], 10)
                factors = {'fvg_fill': tf_weight}
                if trend.get('direction') == 'bullish':
                    factors['trend_alignment'] = min(15, int(trend.get('confidence', 50) * 0.15))
                if fvg['age_hours'] < 24:
                    factors['recency'] = 8
                for z in structure_map.get('support_zones', []):
                    if _near(fvg['midpoint'], z['price'], 0.005):
                        factors['sr_confluence'] = 10
                        break
                ctx = (f"Bullish FVG fill ({fvg['timeframe']}) at "
                       f"{fvg['low']:.0f}-{fvg['high']:.0f}, reacting at midpoint. "
                       f"Age: {fvg['age_hours']:.0f}h")
                signals.append(_make_signal('fvg_fill', direction, entry, sl, tps, factors, ctx))

        # Bearish FVG: price came up to fill the gap → expect rejection short
        elif fvg['type'] == 'bearish':
            in_gap = fvg['low'] <= c['close'] <= fvg['high']
            if in_gap and c['high'] >= fvg['midpoint'] and c['close'] < fvg['high']:
                direction = 'short'
                entry = c['close']
                sl = fvg['high'] * 1.001
                tps = _get_structural_tps(direction, entry, sl, structure_map)
                if not tps:
                    continue
                tf_weight = {'H4': 20, 'H1': 15, 'M15': 10}.get(fvg['timeframe'], 10)
                factors = {'fvg_fill': tf_weight}
                if trend.get('direction') == 'bearish':
                    factors['trend_alignment'] = min(15, int(trend.get('confidence', 50) * 0.15))
                if fvg['age_hours'] < 24:
                    factors['recency'] = 8
                for z in structure_map.get('resistance_zones', []):
                    if _near(fvg['midpoint'], z['price'], 0.005):
                        factors['sr_confluence'] = 10
                        break
                ctx = (f"Bearish FVG fill ({fvg['timeframe']}) at "
                       f"{fvg['low']:.0f}-{fvg['high']:.0f}, rejecting at midpoint. "
                       f"Age: {fvg['age_hours']:.0f}h")
                signals.append(_make_signal('fvg_fill', direction, entry, sl, tps, factors, ctx))

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL D — SUPPORT/RESISTANCE REACTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_sr_reaction(candles: list, structure_map: dict) -> list:
    """
    Price approaches a major S/R zone and shows a clean reaction.
    Only trades in trend-aligned direction.
    """
    signals = []
    c = candles[-1]
    trend = structure_map.get('trend_bias', {})
    trend_dir = trend.get('direction', 'neutral')

    # Support zones → long
    for zone in structure_map.get('support_zones', []):
        zone_price = zone['price']
        in_zone = zone['range'][0] <= c['close'] <= zone['range'][1]
        approaching = _near(c['close'], zone_price, 0.0015)
        if not (in_zone or approaching):
            continue
        # Rejection candle: wick into zone, closed above
        if c['low'] <= zone['range'][1] and c['close'] > zone['range'][0]:
            # Only long if trend is bullish or neutral (don't long support in downtrend)
            if trend_dir == 'bearish':
                continue
            direction = 'long'
            entry = c['close']
            sl = zone['range'][0] * 0.999
            tps = _get_structural_tps(direction, entry, sl, structure_map)
            if not tps:
                continue
            strength_score = {'major': 18, 'minor': 10}.get(zone['label'], 10)
            factors = {'sr_reaction': strength_score}
            if trend_dir == 'bullish':
                factors['trend_alignment'] = min(15, int(trend.get('confidence', 50) * 0.15))
            rv = get_relative_volume(candles[-21:])
            if rv > 1.2:
                factors['volume_confirm'] = 8
            ctx = (f"{zone['label'].capitalize()} support reaction at {zone_price:.0f} "
                   f"(strength={zone['strength']}, tf={zone.get('timeframe','?')}). "
                   f"Trend: {trend_dir}")
            signals.append(_make_signal('sr_reaction', direction, entry, sl, tps, factors, ctx))

    # Resistance zones → short
    for zone in structure_map.get('resistance_zones', []):
        zone_price = zone['price']
        in_zone = zone['range'][0] <= c['close'] <= zone['range'][1]
        approaching = _near(c['close'], zone_price, 0.0015)
        if not (in_zone or approaching):
            continue
        if c['high'] >= zone['range'][0] and c['close'] < zone['range'][1]:
            if trend_dir == 'bullish':
                continue
            direction = 'short'
            entry = c['close']
            sl = zone['range'][1] * 1.001
            tps = _get_structural_tps(direction, entry, sl, structure_map)
            if not tps:
                continue
            strength_score = {'major': 18, 'minor': 10}.get(zone['label'], 10)
            factors = {'sr_reaction': strength_score}
            if trend_dir == 'bearish':
                factors['trend_alignment'] = min(15, int(trend.get('confidence', 50) * 0.15))
            rv = get_relative_volume(candles[-21:])
            if rv > 1.2:
                factors['volume_confirm'] = 8
            ctx = (f"{zone['label'].capitalize()} resistance rejection at {zone_price:.0f} "
                   f"(strength={zone['strength']}, tf={zone.get('timeframe','?')}). "
                   f"Trend: {trend_dir}")
            signals.append(_make_signal('sr_reaction', direction, entry, sl, tps, factors, ctx))

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL E — ORB BREAKOUT (SUPPLEMENTARY)
# ─────────────────────────────────────────────────────────────────────────────

def detect_orb_breakout(candles: list, structure_map: dict,
                         session_open_hour_utc: int = None) -> list:
    """
    Detects an ORB breakout at NY open (13:30 UTC) or Asia open (00:00 UTC).
    Supplementary signal — adds to confluence, not a standalone trigger.
    Only looks at the most recent 3 M15 candles.
    """
    signals = []
    if session_open_hour_utc is None:
        return signals

    now_utc = candles[-1]['dt']
    # Only fire within 45 minutes of session open
    if now_utc.hour != session_open_hour_utc:
        return signals
    if now_utc.minute > 45:
        return signals

    # ORB = first 2 M15 candles after open
    if len(candles) < 4:
        return signals

    orb_candles = candles[-3:-1]  # 2nd and 3rd last (the ORB range)
    orb_high = max(c['high'] for c in orb_candles)
    orb_low  = min(c['low'] for c in orb_candles)
    orb_range = orb_high - orb_low

    # Minimum ORB size check
    if orb_range < 100 or orb_range > 2500:
        return signals

    c = candles[-1]
    trend = structure_map.get('trend_bias', {})

    if c['close'] > orb_high:
        direction = 'long'
        entry = c['close']
        sl = orb_low
        tps = _get_structural_tps(direction, entry, sl, structure_map)
        if tps:
            factors = {'orb_breakout': 10}
            if trend.get('direction') == 'bullish':
                factors['trend_alignment'] = 8
            ctx = f"ORB breakout LONG at session open. ORB={orb_low:.0f}-{orb_high:.0f}"
            signals.append(_make_signal('orb_breakout', direction, entry, sl, tps, factors, ctx))

    elif c['close'] < orb_low:
        direction = 'short'
        entry = c['close']
        sl = orb_high
        tps = _get_structural_tps(direction, entry, sl, structure_map)
        if tps:
            factors = {'orb_breakout': 10}
            if trend.get('direction') == 'bearish':
                factors['trend_alignment'] = 8
            ctx = f"ORB breakout SHORT at session open. ORB={orb_low:.0f}-{orb_high:.0f}"
            signals.append(_make_signal('orb_breakout', direction, entry, sl, tps, factors, ctx))

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# COMBINED DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_all_signals(structure_map: dict,
                        session_open_hour: int = None) -> list:
    """
    Run all signal detectors and return combined list.
    Fetches fresh M15 candles for detection (most recent 100 candles).
    """
    m15_candles = get_candles_as_dicts('15m', limit=100)
    if not m15_candles:
        return []

    all_signals = []
    all_signals.extend(detect_liquidity_sweep(m15_candles, structure_map))
    all_signals.extend(detect_poc_reaction(m15_candles, structure_map))
    all_signals.extend(detect_fvg_fill(m15_candles, structure_map))
    all_signals.extend(detect_sr_reaction(m15_candles, structure_map))
    if session_open_hour is not None:
        all_signals.extend(detect_orb_breakout(m15_candles, structure_map,
                                                session_open_hour))

    if all_signals:
        logging.info(f"Detected {len(all_signals)} signal(s): "
                     f"{[s['type']+'/'+s['direction'] for s in all_signals]}")
    return all_signals
