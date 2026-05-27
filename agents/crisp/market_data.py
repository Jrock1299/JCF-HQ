#!/usr/bin/env python3
"""
market_data.py — Binance API wrapper with caching and rate limiting.
Uses ccxt sandbox mode for public market data (BTC/USDT only).
Private endpoints (order placement) are not used — paper trading only.
"""

import ccxt
import json
import logging
import os
import time
from datetime import datetime, timezone

from crisp_config import (
    load_credentials, SYMBOL,
    CANDLE_CACHE_DIR,
    STRUCTURE_UPDATE_INTERVAL,
)

# ─────────────────────────────────────────────────────────────────────────────
# EXCHANGE SETUP
# ─────────────────────────────────────────────────────────────────────────────

# Use sandbox mode for public data (same candles as live Binance)
_exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
        'adjustForTimeDifference': True,
    }
})
# Sandbox redirects to testnet endpoints but public OHLCV is the same data
_exchange.set_sandbox_mode(True)

# Cache: dict of (symbol, timeframe) → {'candles': [...], 'fetched_at': ts}
_candle_cache: dict = {}
_CACHE_TTL = {
    '4h':  3600,     # H4: refresh hourly
    '1h':  600,      # H1: refresh every 10min
    '15m': 120,      # M15: refresh every 2min
    '5m':  60,       # M5:  refresh every 1min
    '1m':  30,       # M1:  refresh every 30s
}

# ─────────────────────────────────────────────────────────────────────────────
# OHLCV FETCHING
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ohlcv(timeframe: str, limit: int = 200, force: bool = False) -> list:
    """
    Returns list of [timestamp_ms, open, high, low, close, volume] candles.
    Results are cached per timeframe. 'force=True' bypasses cache.
    """
    cache_key = (SYMBOL, timeframe)
    now = time.time()

    if not force and cache_key in _candle_cache:
        entry = _candle_cache[cache_key]
        ttl = _CACHE_TTL.get(timeframe, 120)
        if now - entry['fetched_at'] < ttl:
            return entry['candles']

    try:
        candles = _exchange.fetch_ohlcv(SYMBOL, timeframe, limit=limit)
        _candle_cache[cache_key] = {'candles': candles, 'fetched_at': now}
        _persist_cache(timeframe, candles)
        return candles
    except Exception as e:
        logging.error(f"fetch_ohlcv({timeframe},{limit}): {e}")
        # Return cached data if available (even if stale)
        if cache_key in _candle_cache:
            logging.warning(f"Using stale {timeframe} cache after fetch error")
            return _candle_cache[cache_key]['candles']
        return _load_cache(timeframe) or []


def get_current_price() -> float:
    """Returns the close price of the most recent 1m candle."""
    candles = fetch_ohlcv('1m', limit=2)
    if candles:
        return candles[-1][4]  # close
    raise ValueError("Cannot get current BTC price")


def get_candles_as_dicts(timeframe: str, limit: int = 200) -> list:
    """
    Returns candles as list of dicts for easier access:
    {ts, open, high, low, close, volume}
    """
    raw = fetch_ohlcv(timeframe, limit=limit)
    return [
        {
            'ts': c[0],
            'open': c[1],
            'high': c[2],
            'low': c[3],
            'close': c[4],
            'volume': c[5],
            'dt': datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc)
        }
        for c in raw
    ]


# ─────────────────────────────────────────────────────────────────────────────
# ATR CALCULATION
# ─────────────────────────────────────────────────────────────────────────────

def calculate_atr(candles: list, period: int = 14) -> float:
    """
    ATR using True Range on candle dicts.
    candles: list of dicts with high/low/close keys.
    Returns the ATR value (in price units, i.e. USD for BTC/USDT).
    """
    if len(candles) < period + 1:
        return 0.0

    trs = []
    for i in range(1, len(candles)):
        high = candles[i]['high']
        low = candles[i]['low']
        prev_close = candles[i-1]['close']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    # Wilder's smoothing (simple average for first, then EMA-style)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0

    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def get_atr_h1() -> float:
    candles = get_candles_as_dicts('1h', limit=50)
    return calculate_atr(candles, period=14)


def get_atr_h4() -> float:
    candles = get_candles_as_dicts('4h', limit=50)
    return calculate_atr(candles, period=14)


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_relative_volume(candles: list, lookback: int = 20) -> float:
    """
    Returns the volume of the most recent candle relative to the average
    of the prior 'lookback' candles. 1.0 = average, 2.0 = 2x average.
    """
    if len(candles) < lookback + 1:
        return 1.0
    recent_vol = candles[-1]['volume']
    avg_vol = sum(c['volume'] for c in candles[-lookback-1:-1]) / lookback
    if avg_vol == 0:
        return 1.0
    return recent_vol / avg_vol


# ─────────────────────────────────────────────────────────────────────────────
# CACHE PERSISTENCE (disk backup for crash recovery)
# ─────────────────────────────────────────────────────────────────────────────

def _persist_cache(timeframe: str, candles: list):
    try:
        path = os.path.join(CANDLE_CACHE_DIR, f'btc_{timeframe.replace("/","")}.json')
        with open(path, 'w') as f:
            json.dump({
                'timeframe': timeframe,
                'fetched_at': time.time(),
                'candles': candles[-500:]  # keep last 500 candles
            }, f)
    except Exception as e:
        logging.warning(f"Cache persist failed ({timeframe}): {e}")


def _load_cache(timeframe: str) -> list:
    try:
        path = os.path.join(CANDLE_CACHE_DIR, f'btc_{timeframe.replace("/","")}.json')
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            # Only use disk cache if it's reasonably fresh (< 1 hour)
            age = time.time() - data.get('fetched_at', 0)
            if age < 3600:
                logging.info(f"Loaded {timeframe} candles from disk cache ({age:.0f}s old)")
                return data['candles']
    except Exception as e:
        logging.warning(f"Cache load failed ({timeframe}): {e}")
    return []


def warm_cache():
    """Pre-fetch all required timeframes on startup."""
    logging.info("Warming candle cache...")
    for tf in ['4h', '1h', '15m', '5m']:
        fetch_ohlcv(tf, limit=200, force=True)
        time.sleep(0.2)
    logging.info("Cache warm complete")
