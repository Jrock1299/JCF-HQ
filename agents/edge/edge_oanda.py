"""
Edge — OANDA API wrapper
Candle fetching, SMA calculation, live order placement, position queries.
All calls use the Scalper Account (101-001-22502524-002).
"""

import json
import logging
import oandapyV20
from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles
from oandapyV20.endpoints.orders import OrderCreate
from oandapyV20.endpoints.positions import PositionClose
from oandapyV20.endpoints.accounts import AccountDetails

from edge_config import (
    OANDA_ACCOUNT_ID, OANDA_ENVIRONMENT, AUTH_PROFILES_PATH,
    SMA_FAST, SMA_SLOW, INSTRUMENT, CANDLE_COUNT_H1,
)

# Back-compat alias for the previous CANDLE_COUNT constant.
CANDLE_COUNT = CANDLE_COUNT_H1

# ─────────────────────────────────────────────────────────────────────────────
# CLIENT INIT
# ─────────────────────────────────────────────────────────────────────────────

with open(AUTH_PROFILES_PATH) as f:
    _auth = json.load(f)

# Use oanda:scalper key if present (002 account token), otherwise fall back to
# the shared oanda:default key. Market data (candles) works with either key;
# account-level calls (balance, orders) require the 002-specific token.
_scalper_key = _auth['profiles'].get('oanda:scalper', {}).get('key', '')
_key = (
    _scalper_key
    if _scalper_key and not _scalper_key.startswith('PASTE_')
    else _auth['profiles']['oanda:default']['key']
)
client  = API(access_token=_key, environment=OANDA_ENVIRONMENT)


# ─────────────────────────────────────────────────────────────────────────────
# CANDLES
# ─────────────────────────────────────────────────────────────────────────────

def fetch_candles(instrument=INSTRUMENT, granularity='M1', count=CANDLE_COUNT):
    """
    Fetch closed M1 candles from OANDA. Returns list of dicts:
      {'time': str, 'open': float, 'high': float, 'low': float, 'close': float, 'complete': bool}
    Only returns completed (closed) candles.
    """
    try:
        r = InstrumentsCandles(instrument, params={
            'granularity': granularity,
            'count':       count + 1,   # +1 because the last candle may still be open
            'price':       'M',         # midpoint prices
        })
        client.request(r)
        raw = r.response.get('candles', [])
        result = []
        for c in raw:
            if not c.get('complete', False):
                continue   # skip the currently-open candle
            m = c.get('mid', {})
            result.append({
                'time':  c['time'],
                'open':  float(m.get('o', 0)),
                'high':  float(m.get('h', 0)),
                'low':   float(m.get('l', 0)),
                'close': float(m.get('c', 0)),
            })
        return result
    except Exception as e:
        logging.error(f"fetch_candles({instrument},{granularity},{count}): {type(e).__name__}: {e}")
        return []


def get_current_price(instrument=INSTRUMENT):
    """Return the latest mid-close price (from the most recent completed candle)."""
    candles = fetch_candles(instrument, 'M1', 3)
    if candles:
        return candles[-1]['close']
    raise ValueError(f"Cannot fetch price for {instrument}")


# ─────────────────────────────────────────────────────────────────────────────
# SMA CALCULATION
# ─────────────────────────────────────────────────────────────────────────────

def calculate_sma(candles, period):
    """Simple moving average of the last `period` candle closes."""
    if len(candles) < period:
        return None
    closes = [c['close'] for c in candles[-period:]]
    return sum(closes) / len(closes)


def get_smas(candles):
    """
    Calculate SMA9 and SMA21 for the last two candles (needed for cross detection).
    Returns (sma9_prev, sma9_curr, sma21_prev, sma21_curr) or None if insufficient data.
    """
    if len(candles) < SMA_SLOW + 2:
        return None

    sma9_curr  = calculate_sma(candles,       SMA_FAST)
    sma9_prev  = calculate_sma(candles[:-1],  SMA_FAST)
    sma21_curr = calculate_sma(candles,       SMA_SLOW)
    sma21_prev = calculate_sma(candles[:-1],  SMA_SLOW)

    if None in (sma9_curr, sma9_prev, sma21_curr, sma21_prev):
        return None

    return sma9_prev, sma9_curr, sma21_prev, sma21_curr


def get_avg_body_size(candles, lookback=20):
    """Average candle body size over last N candles."""
    if len(candles) < lookback:
        lookback = len(candles)
    bodies = [abs(c['close'] - c['open']) for c in candles[-lookback:]]
    return sum(bodies) / len(bodies) if bodies else 1.0


# ─────────────────────────────────────────────────────────────────────────────
# CROSS DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_cross(sma9_prev, sma9_curr, sma21_prev, sma21_curr):
    """
    Detect SMA crossover on closed candle values.
    Returns (bullish_cross: bool, bearish_cross: bool).
    """
    bullish = sma9_prev <= sma21_prev and sma9_curr > sma21_curr
    bearish = sma9_prev >= sma21_prev and sma9_curr < sma21_curr
    return bullish, bearish


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT
# ─────────────────────────────────────────────────────────────────────────────

def get_account_balance():
    """Fetch current NAV from OANDA Scalper Account."""
    try:
        r = AccountDetails(OANDA_ACCOUNT_ID)
        client.request(r)
        return float(r.response['account']['NAV'])
    except Exception as e:
        # 403 = token not scoped to this account yet — log quietly, not as error
        msg = str(e)
        if '403' in msg or 'forbidden' in msg.lower() or 'authorization' in msg.lower():
            logging.debug(f"get_account_balance: token not yet authorized for {OANDA_ACCOUNT_ID}")
        else:
            logging.error(f"get_account_balance: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# ORDER PLACEMENT (paper mode uses simulation, live uses OANDA practice)
# ─────────────────────────────────────────────────────────────────────────────

def place_market_order(direction, units, instrument=INSTRUMENT):
    """
    Place a market order on the OANDA practice account.
    direction: 'long' or 'short'
    units: positive integer (5 for standard)
    Returns trade_id string or None on failure.
    """
    signed_units = str(units) if direction == 'long' else str(-units)
    body = {
        "order": {
            "type":        "MARKET",
            "instrument":  instrument,
            "units":       signed_units,
            "timeInForce": "FOK",
        }
    }
    try:
        r = OrderCreate(OANDA_ACCOUNT_ID, data=body)
        client.request(r)
        resp = r.response
        trade_id = (resp.get('orderFillTransaction') or {}).get('tradeOpened', {}).get('tradeID')
        fill_price = float((resp.get('orderFillTransaction') or {}).get('price', 0))
        logging.info(f"ORDER FILLED: {instrument} {direction} {units}u @ {fill_price} | trade_id={trade_id}")
        return trade_id, fill_price
    except Exception as e:
        logging.error(f"place_market_order({direction},{units}): {type(e).__name__}: {e}")
        return None, None


def close_position(instrument=INSTRUMENT, direction=None):
    """
    Close the open position on the instrument.
    Uses OANDA's position close endpoint (closes all units).
    Returns (fill_price, realized_pnl) or (None, None) on failure.
    """
    if direction == 'long':
        body = {"longUnits": "ALL"}
    elif direction == 'short':
        body = {"shortUnits": "ALL"}
    else:
        body = {"longUnits": "ALL", "shortUnits": "ALL"}

    try:
        r = PositionClose(OANDA_ACCOUNT_ID, instrument, data=body)
        client.request(r)
        resp = r.response
        txn = resp.get('longOrderFillTransaction') or resp.get('shortOrderFillTransaction') or {}
        fill_price  = float(txn.get('price', 0))
        realized_pl = float(txn.get('pl', 0))
        logging.info(f"POSITION CLOSED: {instrument} @ {fill_price} | P&L: ${realized_pl:.2f}")
        return fill_price, realized_pl
    except Exception as e:
        logging.error(f"close_position({instrument}): {type(e).__name__}: {e}")
        return None, None


def close_position_units(direction, units, instrument=INSTRUMENT):
    """
    Partial close: reduce the open position by a specific number of units.
    Used when a cluster sub-position (pos1/pos2/pos3) hits its TP or SL while
    the other sub-positions stay open at OANDA.
    Returns (fill_price, realized_pnl) or (None, None) on failure.
    """
    if direction == 'long':
        body = {"longUnits": str(int(units))}
    elif direction == 'short':
        body = {"shortUnits": str(int(units))}
    else:
        return None, None
    try:
        r = PositionClose(OANDA_ACCOUNT_ID, instrument, data=body)
        client.request(r)
        resp = r.response
        txn = resp.get('longOrderFillTransaction') or resp.get('shortOrderFillTransaction') or {}
        fill_price  = float(txn.get('price', 0))
        realized_pl = float(txn.get('pl', 0))
        logging.info(
            f"POSITION PARTIAL CLOSE: {instrument} {direction} {units}u @ "
            f"{fill_price} | P&L: ${realized_pl:.2f}"
        )
        return fill_price, realized_pl
    except Exception as e:
        logging.error(
            f"close_position_units({instrument},{direction},{units}): "
            f"{type(e).__name__}: {e}"
        )
        return None, None
