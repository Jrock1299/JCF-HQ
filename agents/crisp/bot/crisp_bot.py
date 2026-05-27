#!/usr/bin/env python3
"""
CRISP v4 — BTC/USDT Multi-Strategy Framework
2026-03-24

TWO TRADING MODES (can be active simultaneously on different sessions):

MODE A — Daily ORB (runs every session, always):
  0.001 BTC | TP1=$150 / TP2=$200 / TP3=$300 | SL=opposite ORB level
  No score gate — always runs if ADR + ORB quality pass

MODE B — Swing Trade (score >= 70 only):
  0.003 BTC (3x) | TP1=$300 / TP2=$500 / TP3=$1000 | SL=H4 structure level
  Uses Strategist bias direction

FOUR STRATEGIES PER SESSION (max 1 trade each, sequential):
  1. ORB breakout    — first 30 min
  2. Sweep fade      — post-ORB — score >= 50
  3. EMA pullback    — mid-session, trend continuation — score >= 50
  4. Momentum entry  — any time, prior-session-range breakout — score >= 50
  + Swing            — any time — score >= 70

SCORE AS MODE SELECTOR (not trade gate):
  < 50  : ORB only, standard lots
  50-69 : ORB + additional strategies, standard lots
  >= 70 : all above + Swing mode with 3x lots

Sessions:
  ASIAN — 00:00 UTC (cleanest BTC session — add this cron)
  NY    — 13:30 UTC (highest volume)

Paper trade only.
"""

import ccxt
import json
import time
import logging
import uuid
import os
import subprocess
from datetime import datetime, timezone, timedelta
from statistics import mean
import sys

sys.path.insert(0, "/root/.openclaw/scripts")
from hub_post import add_hub_message as hub_post
import session_notify

try:
    from crypto_enrichment import get_enricher as _get_enricher
    _CRISP_ENRICHER_AVAILABLE = True
except Exception:
    _CRISP_ENRICHER_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename='/root/.openclaw/agents/crisp/bot/crisp.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

binance = ccxt.binance({'enableRateLimit': True})

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

AGENT_NAME        = "crisp"
PAPER_MODE        = True
SYMBOL            = 'BTC/USDT'
MARKET_BIAS_PATH  = '/root/.openclaw/dashboard/market_bias.json'
TRADES_JSON_PATH  = '/root/.openclaw/dashboard/agent_trades.json'
STRATEGY_REC_PATH = '/root/.openclaw/dashboard/strategy_recommendation.json'
TELEGRAM_UID          = "797062420"
CRISP_ENRICHMENT_LOG  = '/root/.openclaw/agents/crisp/enrichment_log.csv'
DIVERGENCE_THRESHOLD  = 0.3   # percent — above this triggers score penalty
DIVERGENCE_PENALTY    = 20    # score points to subtract on divergence

# BTC pip = $1.00 (price ~$75,000 — targets of $150/$200/$300 are ~0.2-0.4% moves)
PIP_VALUE     = 1.0

# Mode A — Daily ORB
LOT_SIZE      = 0.001    # 0.001 BTC per trade
TP1_PIPS      = 150      # $150
TP2_PIPS      = 200      # $200
TP3_PIPS      = 300      # $300

# Mode B — Swing Trade (3x lots, wider targets)
SWING_LOT_SIZE    = 0.003   # 0.003 BTC (3x)
SWING_TP1_PIPS    = 300     # $300
SWING_TP2_PIPS    = 500     # $500
SWING_TP3_PIPS    = 1000    # $1000

ORB_MIN_PIPS  = 100   # skip if ORB < $100 (too tight)
ORB_MAX_PIPS  = 2500  # skip if ORB > $2500 (too volatile/chaotic)
ADR_THRESHOLD = 5000  # skip session if 5-day ADR > $5,000
ADR_MIN       = 500   # skip if ADR < $500 (market too flat)
LENS_KEYS     = ['BTC/USDT', 'BTC_USDT', 'BTC/USD']
LENS_THRESHOLD = 65   # apply directional filter at this confidence

paper_balance  = 10000.0
open_positions = {}
session_trades = []

SESSION_TIMES = {
    'ASIAN': {'open_hour': 0,  'open_min': 0,  'close_hour': 4,  'close_min': 0},
    'NY':    {'open_hour': 13, 'open_min': 30, 'close_hour': 17, 'close_min': 30},
}

# ─────────────────────────────────────────────────────────────────────────────
# EXCHANGE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_candles(symbol, timeframe, limit):
    try:
        return binance.fetch_ohlcv(symbol, timeframe, limit=limit)
    except Exception as e:
        logging.error(f"get_candles({symbol},{timeframe},{limit}): {e}")
        return []

def get_price(symbol):
    try:
        return binance.fetch_ticker(symbol)['last']
    except Exception as e:
        raise ValueError(f"Cannot get price for {symbol}: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGIST INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

def read_strategist_recommendation():
    """
    Read the Strategist's recommendation for BTC_USD.
    Score is used as mode selector — NOT as a trade gate.
    Returns: (score, strategy, bias, recommendation, notes)
    """
    try:
        with open(STRATEGY_REC_PATH) as f:
            rec = json.load(f)

        instruments = rec.get('instruments', {})
        entry = instruments.get('BTC_USD') or instruments.get('BTC/USDT')
        if not entry:
            return 50, 'orb', 'neutral', 'TRADE', 'No strategist data — score=50'

        score          = entry.get('score',          50)
        strategy       = entry.get('strategy',       'orb')
        bias           = entry.get('bias',           'neutral')
        recommendation = entry.get('recommendation', 'TRADE')
        notes          = entry.get('notes',          '')

        updated_str = rec.get('updated', '')
        if updated_str:
            try:
                updated   = datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
                age_hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
                if age_hours > 8:
                    logging.warning(f"Strategist data is {age_hours:.1f}h old")
                    notes += f' [data {age_hours:.0f}h old]'
            except Exception:
                pass

        return score, strategy, bias, recommendation, notes

    except FileNotFoundError:
        logging.info("strategy_recommendation.json not found — score=50")
        return 50, 'orb', 'neutral', 'TRADE', 'Strategist not run — score=50'
    except Exception as e:
        logging.warning(f"read_strategist_recommendation: {e}")
        return 50, 'orb', 'neutral', 'TRADE', f'Strategist read error: {e}'


# ─────────────────────────────────────────────────────────────────────────────
# FILTERS
# ─────────────────────────────────────────────────────────────────────────────

def get_5day_adr():
    """5-day Average Daily Range for BTC/USDT in USD."""
    try:
        candles = get_candles(SYMBOL, '1d', 7)
        if len(candles) < 5:
            return None
        last5 = candles[-6:-1]  # 5 complete days
        return mean([c[2] - c[3] for c in last5])  # high - low
    except Exception as e:
        logging.error(f"get_5day_adr: {e}")
        return None

def read_lens_bias():
    """
    Returns (direction, confidence) for BTC from market_bias.json.
    """
    try:
        with open(MARKET_BIAS_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        logging.warning("market_bias.json not found")
        return 'neutral', 0.0
    except Exception as e:
        logging.error(f"Lens read error: {e}")
        return 'neutral', 0.0

    bias_entry = None
    for key in LENS_KEYS:
        entry = data.get(key)
        if entry and isinstance(entry, dict):
            bias_entry = entry
            break
    if not bias_entry:
        for p in data.get('pairs', []):
            if p.get('symbol') in LENS_KEYS:
                bias_entry = p
                break

    if not bias_entry:
        return 'neutral', 0.0

    direction  = bias_entry.get('bias', 'neutral').lower()
    confidence = float(bias_entry.get('confidence', 0))
    if confidence <= 1.0:
        confidence *= 100
    return direction, confidence

def check_orb_quality(orb_high, orb_low):
    pips = (orb_high - orb_low) / PIP_VALUE
    if pips < ORB_MIN_PIPS:
        return False, f"ORB too tight: ${pips:.0f} < ${ORB_MIN_PIPS} min"
    if pips > ORB_MAX_PIPS:
        return False, f"ORB too wide: ${pips:.0f} > ${ORB_MAX_PIPS} max"
    return True, f"ORB OK: ${pips:.0f}"

def run_adr_gate():
    adr = get_5day_adr()
    if adr is None:
        return False, "ADR unavailable — proceeding"
    if adr > ADR_THRESHOLD:
        return True, f"ADR gate: ${adr:.0f} > ${ADR_THRESHOLD} max"
    if adr < ADR_MIN:
        return True, f"ADR gate: ${adr:.0f} < ${ADR_MIN} min (too flat)"
    return False, f"ADR OK: ${adr:.0f}"

def get_prior_day_bias():
    """Prior-day directional bias from daily candle."""
    try:
        candles = get_candles(SYMBOL, '1d', 3)
        if len(candles) < 2:
            return 'neutral'
        prev = candles[-2]
        move = (prev[4] - prev[1]) / prev[1]
        if move > 0.01:
            return 'bullish'
        elif move < -0.01:
            return 'bearish'
        return 'neutral'
    except Exception as e:
        logging.error(f"get_prior_day_bias: {e}")
        return 'neutral'

def get_round_number_proximity(price):
    """BTC gravitates to round $5k numbers. Returns distance as pct of price."""
    interval = 5000
    nearest  = round(price / interval) * interval
    return abs(price - nearest) / price

# ─────────────────────────────────────────────────────────────────────────────
# ORB DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_session_open(session_name):
    sess = SESSION_TIMES[session_name]
    while True:
        now = datetime.now(timezone.utc)
        if now.hour > sess['open_hour'] or \
           (now.hour == sess['open_hour'] and now.minute >= sess['open_min']):
            msg = f"{session_name} session open — {now.strftime('%H:%M:%S UTC')}"
            print(f"\n{'='*60}\n{msg}")
            logging.info(msg)
            hub_post(AGENT_NAME, "status", msg, tags=["session"])
            return
        wait_m = (sess['open_hour'] - now.hour) * 60 + (sess['open_min'] - now.minute)
        print(f"Waiting for {session_name} ({sess['open_hour']:02d}:{sess['open_min']:02d} UTC)... {wait_m}m")
        time.sleep(min(wait_m * 60, 60))

def wait_for_15m_candle_close():
    now       = datetime.now(timezone.utc)
    mins_into = now.minute % 15
    wait_secs = (15 - mins_into) * 60 - now.second
    if wait_secs >= 900:
        wait_secs -= 900
    if wait_secs > 5:
        print(f"Waiting {wait_secs}s for 15m candle to close...")
        time.sleep(wait_secs + 3)
    print("15m candle closed — monitoring 1m for breakout")

def get_orb_15m():
    """Returns (orb_high, orb_low) from last completed 15m candle."""
    try:
        candles = get_candles(SYMBOL, '15m', 3)
        if len(candles) < 2:
            return None, None
        orb = candles[-2]   # [ts, open, high, low, close, vol]
        return orb[2], orb[3]
    except Exception as e:
        logging.error(f"get_orb_15m: {e}")
        return None, None

def check_1m_breakout(orb_high, orb_low):
    """Both open AND close of last completed 1m candle must clear ORB level."""
    try:
        candles = get_candles(SYMBOL, '1m', 3)
        if len(candles) < 2:
            return None
        last = candles[-2]  # [ts, open, high, low, close, vol]
        c, o = last[4], last[1]
        if c > orb_high and o > orb_high:
            return 'long'
        elif c < orb_low and o < orb_low:
            return 'short'
        return None
    except Exception as e:
        logging.error(f"check_1m_breakout: {e}")
        return None

def detect_liquidity_sweep(orb_high, orb_low, state):
    """
    Detect stop hunt / false ORB breakout that reverses back inside range.
    BTC is notorious for stop hunts — ETF rebalancing and whale manipulation.
    """
    try:
        candles = get_candles(SYMBOL, '1m', 3)
        if len(candles) < 2:
            return None, state
        last      = candles[-2]
        close_p   = last[4]
        low_p     = last[3]
        high_p    = last[2]
        orb_range = orb_high - orb_low

        if low_p < orb_low:
            state['swept_low']         = True
            state['sweep_low_extreme'] = min(low_p, state.get('sweep_low_extreme', low_p))
        if high_p > orb_high:
            state['swept_high']         = True
            state['sweep_high_extreme'] = max(high_p, state.get('sweep_high_extreme', high_p))

        if state.get('fade_triggered'):
            return None, state

        if state.get('swept_low') and close_p > orb_low:
            reversal = close_p - state.get('sweep_low_extreme', orb_low)
            if reversal > orb_range * 0.3:
                state['fade_triggered'] = True
                return 'long', state

        if state.get('swept_high') and close_p < orb_high:
            reversal = state.get('sweep_high_extreme', orb_high) - close_p
            if reversal > orb_range * 0.3:
                state['fade_triggered'] = True
                return 'short', state

        return None, state
    except Exception as e:
        logging.error(f"detect_liquidity_sweep: {e}")
        return None, state

def get_asian_session_range():
    """
    Asian session consolidation range (00:00–06:00 UTC) as context.
    Returns (range_high, range_low) or (None, None).
    """
    try:
        candles = get_candles(SYMBOL, '1h', 10)
        if len(candles) < 6:
            return None, None
        asian = candles[-7:-1]  # last 6 complete hours
        high  = max(c[2] for c in asian)
        low   = min(c[3] for c in asian)
        return high, low
    except Exception as e:
        logging.error(f"get_asian_session_range: {e}")
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# ADDITIONAL STRATEGY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_m15_ema20():
    """Returns the 20-period EMA on M15 for BTC, or None on failure."""
    try:
        candles = get_candles(SYMBOL, '15m', 25)
        if len(candles) < 20:
            return None
        closes = [c[4] for c in candles[-22:-2]]  # 20 complete candles
        if len(closes) < 20:
            return None
        k   = 2.0 / (20 + 1)
        ema = closes[0]
        for close in closes[1:]:
            ema = close * k + ema * (1 - k)
        return ema
    except Exception as e:
        logging.error(f"get_m15_ema20: {e}")
        return None

def check_ema_pullback(trend_direction, ema20):
    """
    Detects pullback to 20 EMA on M15 with continuation candle.
    trend_direction: 'long' | 'short'
    Returns 'long', 'short', or None.
    """
    if ema20 is None:
        return None
    try:
        candles = get_candles(SYMBOL, '1m', 3)
        if len(candles) < 2:
            return None
        last    = candles[-2]
        low_p   = last[3]
        high_p  = last[2]
        close_p = last[4]
        open_p  = last[1]

        if trend_direction == 'long':
            if low_p <= ema20 * 1.001 and close_p > ema20 and close_p > open_p:
                return 'long'
        elif trend_direction == 'short':
            if high_p >= ema20 * 0.999 and close_p < ema20 and close_p < open_p:
                return 'short'
        return None
    except Exception as e:
        logging.error(f"check_ema_pullback: {e}")
        return None

def get_prior_session_range():
    """Returns (high, low) of the prior 6 hours for momentum detection."""
    try:
        candles = get_candles(SYMBOL, '1h', 10)
        if len(candles) < 6:
            return None, None
        prior6 = candles[-7:-1]
        high   = max(c[2] for c in prior6)
        low    = min(c[3] for c in prior6)
        return high, low
    except Exception as e:
        logging.error(f"get_prior_session_range: {e}")
        return None, None

def check_momentum_entry(prior_high, prior_low, ema20):
    """
    Momentum breakout: price breaks prior-session high/low with strong candle + EMA alignment.
    Returns 'long', 'short', or None.
    """
    if prior_high is None or ema20 is None:
        return None
    try:
        candles = get_candles(SYMBOL, '1m', 3)
        if len(candles) < 2:
            return None
        last    = candles[-2]
        close_p = last[4]
        open_p  = last[1]
        high_p  = last[2]
        low_p   = last[3]

        candle_range = abs(close_p - open_p)
        body_pct     = candle_range / (abs(high_p - low_p) + 0.01)

        if (close_p > prior_high and close_p > ema20 and
                close_p > open_p and body_pct > 0.6):
            return 'long'
        if (close_p < prior_low and close_p < ema20 and
                close_p < open_p and body_pct > 0.6):
            return 'short'
        return None
    except Exception as e:
        logging.error(f"check_momentum_entry: {e}")
        return None

def get_h4_structure_level(direction):
    """
    Returns H4 structural SL for Mode B swing trades.
    For long: lowest H4 low in last 4 candles.
    For short: highest H4 high in last 4 candles.
    """
    try:
        candles = get_candles(SYMBOL, '4h', 8)
        if len(candles) < 4:
            return None
        last4 = candles[-5:-1]  # 4 complete H4 candles
        if direction == 'long':
            return min(c[3] for c in last4)
        else:
            return max(c[2] for c in last4)
    except Exception as e:
        logging.error(f"get_h4_structure_level: {e}")
        return None

def check_swing_entry(bias_direction):
    """
    Mode B swing entry: price breaks H4 structural level in bias direction
    with a confirming 1m candle.
    Returns 'long', 'short', or None.
    """
    if bias_direction not in ('bullish', 'bearish'):
        return None
    try:
        candles = get_candles(SYMBOL, '4h', 8)
        if len(candles) < 5:
            return None

        prior4      = candles[-5:-1]
        struct_high = max(c[2] for c in prior4)
        struct_low  = min(c[3] for c in prior4)

        m1_candles = get_candles(SYMBOL, '1m', 3)
        if len(m1_candles) < 2:
            return None

        last    = m1_candles[-2]
        close_p = last[4]
        open_p  = last[1]

        if bias_direction == 'bullish' and close_p > struct_high and close_p > open_p:
            return 'long'
        if bias_direction == 'bearish' and close_p < struct_low and close_p < open_p:
            return 'short'
        return None
    except Exception as e:
        logging.error(f"check_swing_entry: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# POSITION MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def _log_crisp_enrichment(strategy: str, direction: str, binance_price,
                          aggregated_price, divergence_pct, base_score: int,
                          adjusted_score: int, trade_taken: bool) -> None:
    """Append one row to crisp enrichment_log.csv."""
    import csv
    from pathlib import Path
    log_path = Path(CRISP_ENRICHMENT_LOG)
    try:
        write_header = not log_path.exists() or log_path.stat().st_size == 0
        with open(log_path, "a", newline="") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["timestamp", "strategy", "direction", "binance_price",
                             "aggregated_price", "divergence_pct", "base_score",
                             "adjusted_score", "trade_taken"])
            w.writerow([
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                strategy,
                direction,
                round(binance_price, 2) if binance_price is not None else "",
                round(aggregated_price, 2) if aggregated_price is not None else "",
                round(divergence_pct, 4) if divergence_pct is not None else "",
                base_score,
                adjusted_score,
                trade_taken,
            ])
    except Exception as e:
        logging.debug(f"crisp enrichment_log write error: {e}")


def validate_breakout(direction: str, strategy: str, base_score: int) -> tuple[bool, int]:
    """
    Compare Binance spot price vs FreeCryptoAPI aggregated price.
    If divergence > DIVERGENCE_THRESHOLD (%): apply -DIVERGENCE_PENALTY to base_score.
    Returns (should_skip: bool, adjusted_score: int).
    Logs to enrichment_log.csv on every call.
    Gracefully returns (False, base_score) if enricher unavailable.
    """
    if not _CRISP_ENRICHER_AVAILABLE:
        return False, base_score

    binance_price = None
    aggregated_price = None
    divergence_pct = 0.0
    adjusted_score = base_score

    try:
        enricher = _get_enricher()
        summary = enricher.get_multi_exchange_summary("BTC")
        if summary is not None:
            binance_price    = summary["binance_price"]
            aggregated_price = summary["aggregated_price"]
            divergence_pct   = summary["max_divergence_pct"]

            if divergence_pct > DIVERGENCE_THRESHOLD:
                adjusted_score = base_score - DIVERGENCE_PENALTY
                logging.info(
                    f"[enrichment] Breakout divergence {divergence_pct:.4f}% > "
                    f"{DIVERGENCE_THRESHOLD}% — score {base_score} → {adjusted_score}"
                )
    except Exception as e:
        logging.debug(f"validate_breakout error: {e}")

    should_skip = adjusted_score < LENS_THRESHOLD
    _log_crisp_enrichment(strategy, direction, binance_price, aggregated_price,
                           divergence_pct, base_score, adjusted_score, not should_skip)
    return should_skip, adjusted_score


def _try_place_order(direction, orb_high, orb_low, session_name, mode, mode_config,
                     stop_loss_override=None, strategy_score: int = 0) -> bool:
    """
    Wrapper around place_paper_order that runs the FreeCryptoAPI divergence check first.
    If Binance/aggregated price diverges >0.3% and adjusted score drops below LENS_THRESHOLD,
    the trade is skipped and logged.
    """
    should_skip, adjusted_score = validate_breakout(direction, mode, strategy_score)
    if should_skip:
        logging.info(
            f"[enrichment] {mode} {direction.upper()} SKIPPED — "
            f"divergence penalty dropped score to {adjusted_score} < {LENS_THRESHOLD}"
        )
        print(f"  [{mode}] SKIP — exchange divergence penalty: score {strategy_score} → {adjusted_score}")
        return False
    return place_paper_order(direction, orb_high, orb_low, session_name, mode, mode_config,
                             stop_loss_override=stop_loss_override)


def place_paper_order(direction, orb_high, orb_low, session_name, mode, mode_config,
                      stop_loss_override=None):
    """
    Place a paper order.
    mode_config must contain: tp1_pips, tp2_pips, tp3_pips, lot_size.
    stop_loss_override: custom SL price (used by swing/H4 trades).
    """
    global paper_balance
    try:
        price = get_price(SYMBOL)
    except Exception as e:
        logging.error(f"place_paper_order price error: {e}")
        return False

    amount = mode_config.get('lot_size', LOT_SIZE)
    tp1_d  = mode_config['tp1_pips'] * PIP_VALUE
    tp2_d  = mode_config['tp2_pips'] * PIP_VALUE
    tp3_d  = mode_config['tp3_pips'] * PIP_VALUE

    if direction == 'long':
        stop_loss = stop_loss_override if stop_loss_override is not None else orb_low
        tp1_price = price + tp1_d
        tp2_price = price + tp2_d
        tp3_price = price + tp3_d
    else:
        stop_loss = stop_loss_override if stop_loss_override is not None else orb_high
        tp1_price = price - tp1_d
        tp2_price = price - tp2_d
        tp3_price = price - tp3_d

    stop_dist = abs(price - stop_loss)
    if stop_dist < 1.0:
        logging.warning(f"Stop too tight (${stop_dist:.2f}), skip")
        return False

    stop_risk  = round(stop_dist * amount, 2)
    tp1_reward = round(mode_config['tp1_pips'] * PIP_VALUE * amount, 2)

    trade_id = str(uuid.uuid4())

    rn_pct  = get_round_number_proximity(price)
    rn_note = f" (near round ${round(price/5000)*5000:.0f})" if rn_pct < 0.005 else ""

    open_positions[SYMBOL] = {
        'trade_id':        trade_id,
        'direction':       direction,
        'entry':           price,
        'stop_loss':       stop_loss,
        'tp1':             tp1_price,
        'tp2':             tp2_price,
        'tp3':             tp3_price,
        'amount':          amount,
        'breakeven_moved': False,
        'highest_tp_hit':  0,
        'open_time':       datetime.now(timezone.utc).isoformat(),
        'mode':            mode,
    }

    session_trades.append({
        'id':         trade_id,
        'agent':      AGENT_NAME,
        'date':       datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp':  datetime.now(timezone.utc).isoformat(),
        'session':    session_name,
        'pair':       SYMBOL,
        'symbol':     SYMBOL,
        'direction':  direction,
        'setup':      f'15m ORB ({mode})',
        'entry':      price,
        'stop':       stop_loss,
        'tp1':        tp1_price,
        'tp2':        tp2_price,
        'tp3':        tp3_price,
        'result':     'Pending',
        'pnl_usd':    0,
        'r_multiple': 0,
        'notes':      f'{mode} | {amount}BTC | SL:${stop_loss:.0f} | risk:${stop_risk} | tp1:${tp1_reward}{rn_note}',
    })

    msg = (f"PAPER TRADE: {SYMBOL} {direction.upper()} [{mode}] | "
           f"Entry:${price:.0f} SL:${stop_loss:.0f} | "
           f"TP1:${tp1_price:.0f} TP2:${tp2_price:.0f} TP3:${tp3_price:.0f} | "
           f"{amount}BTC Risk:${stop_risk} TP1:${tp1_reward}{rn_note}")
    print(f"  >> {msg}")
    logging.info(msg)
    hub_post(AGENT_NAME, "trade", msg, tags=["trading", "entry", session_name.lower()])
    entry_icon = "🟢" if direction == "long" else "🔴"
    dir_word   = "LONG" if direction == "long" else "SHORT"
    mode_tag   = " [SWING 3x]" if amount > LOT_SIZE else ""
    # TRADE ALERT — commented out; re-enable for live accounts
    # send_telegram_alert(
    #     f"{entry_icon} CRISP {dir_word} BTC @ ${price:.0f}{mode_tag} | "
    #     f"SL: ${stop_loss:.0f} | TP1: ${tp1_price:.0f}"
    # )
    return True

def manage_positions():
    global paper_balance
    to_close = []

    for symbol, pos in list(open_positions.items()):
        try:
            price     = get_price(symbol)
            direction = pos['direction']
            entry     = pos['entry']
            stop      = pos['stop_loss']
            amount    = pos['amount']

            pnl = (price - entry) * amount if direction == 'long' \
                  else (entry - price) * amount

            for tp_level, tp_price in [(3, pos['tp3']), (2, pos['tp2']), (1, pos['tp1'])]:
                if tp_level <= pos['highest_tp_hit']:
                    continue
                hit = (price >= tp_price if direction == 'long' else price <= tp_price)
                if hit:
                    pos['highest_tp_hit'] = tp_level
                    print(f"  TP{tp_level} HIT: {symbol} @ ${price:.0f} | PnL:${pnl:.2f}")
                    logging.info(f"TP{tp_level} HIT: {symbol} @ ${price:.0f} PnL:${pnl:.2f}")
                    be_note = ""
                    if tp_level >= 1 and not pos['breakeven_moved']:
                        pos['stop_loss']       = entry
                        stop                   = entry
                        pos['breakeven_moved'] = True
                        print(f"  BREAKEVEN: {symbol} SL → ${entry:.0f}")
                        logging.info(f"BREAKEVEN: {symbol} SL → ${entry:.0f}")
                        be_note = " | SL→BE"
                    sign    = "+" if pnl >= 0 else "-"
                    tp_icon = "✅" if tp_level == 1 else "🏆"
                    # TRADE ALERT — commented out; re-enable for live accounts
                    # send_telegram_alert(
                    #     f"{tp_icon} CRISP TP{tp_level} HIT BTC {sign}${abs(pnl):.2f}{be_note}"
                    # )
                    if tp_level == 3:
                        to_close.append((symbol, 'TP3', pnl))
                    break

            hit_stop = (price <= stop if direction == 'long' else price >= stop)
            if hit_stop and symbol not in [x[0] for x in to_close]:
                result = 'BE' if pos['breakeven_moved'] else 'SL'
                to_close.append((symbol, result, pnl))
                print(f"  {result} HIT: {symbol} @ ${price:.0f} | PnL:${pnl:.2f}")
                logging.info(f"{result} HIT: {symbol} @ ${price:.0f} PnL:${pnl:.2f}")
                sign = "+" if pnl >= 0 else "-"
                # TRADE ALERT — commented out; re-enable for live accounts
                # if result == 'BE':
                #     send_telegram_alert(f"⚪ CRISP BE HIT BTC {sign}${abs(pnl):.2f}")
                # else:
                #     send_telegram_alert(f"🔴 CRISP SL HIT BTC {sign}${abs(pnl):.2f}")

            tp_tag = f"TP{pos['highest_tp_hit']}" if pos['highest_tp_hit'] else "open"
            icon   = "🟢" if pnl > 0 else "🔴"
            print(f"  {icon} {symbol} {direction.upper()} [{pos['mode']}] | "
                  f"${entry:.0f}→${price:.0f} | PnL:${pnl:.2f} | {tp_tag} | SL:${stop:.0f}")

        except Exception as e:
            logging.error(f"manage_positions {symbol}: {e}")

    for symbol, result, pnl in to_close:
        paper_balance += pnl
        if symbol in open_positions:
            update_trade_log(open_positions[symbol]['trade_id'], result, pnl, f"Closed: {result}")
            del open_positions[symbol]

def close_position_time_stop(symbol):
    global paper_balance
    if symbol not in open_positions:
        return
    pos = open_positions[symbol]
    try:
        price = get_price(symbol)
    except Exception:
        price = pos['entry']

    pnl = (price - pos['entry']) * pos['amount'] if pos['direction'] == 'long' \
          else (pos['entry'] - price) * pos['amount']

    tp_hit = pos['highest_tp_hit']
    result = f"TP{tp_hit}+Time" if tp_hit > 0 else ("BE+Time" if pos['breakeven_moved'] else "Time Stop")
    paper_balance += pnl
    update_trade_log(pos['trade_id'], result, pnl, "Force-closed at session end.")
    msg = f"TIME STOP: {symbol} | {result} PnL:${pnl:.2f} | Balance:${paper_balance:.2f}"
    print(f"  {msg}")
    logging.info(msg)
    del open_positions[symbol]

def update_trade_log(trade_id, result, pnl, notes):
    for t in session_trades:
        if t['id'] == trade_id:
            t['result']     = result
            t['pnl_usd']    = round(pnl, 2)
            entry = t.get('entry', 0)
            stop  = t.get('stop', 0)
            risk  = abs(entry - stop) if entry and stop else 1
            t['r_multiple'] = round(pnl / risk, 1) if risk > 0 else 0
            t['notes']      = notes
            break

def record_no_trade(session_name, reason):
    session_trades.append({
        'id':         str(uuid.uuid4()),
        'agent':      AGENT_NAME,
        'date':       datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp':  datetime.now(timezone.utc).isoformat(),
        'session':    session_name,
        'pair':       SYMBOL,
        'symbol':     SYMBOL,
        'direction':  'none',
        'setup':      '15m ORB',
        'entry':      0, 'stop': 0, 'tp1': 0, 'tp2': 0, 'tp3': 0,
        'result':     'no_trade',
        'pnl_usd':    0,
        'r_multiple': 0,
        'notes':      reason,
    })
    print(f"  NO TRADE: {reason}")
    logging.info(f"NO TRADE: {reason}")

# ─────────────────────────────────────────────────────────────────────────────
# REPORTING
# ─────────────────────────────────────────────────────────────────────────────

def write_session_trades_to_json():
    def norm(t):
        return {
            "agent":     t.get('agent', AGENT_NAME),
            "symbol":    t.get('symbol') or t.get('pair') or '',
            "direction": t.get('direction', 'none'),
            "pnl":       t.get('pnl_usd', t.get('pnl', 0)) or 0,
            "date":      t.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d')),
            "timestamp": t.get('timestamp', datetime.now(timezone.utc).isoformat()),
        }
    try:
        with open(TRADES_JSON_PATH, 'r') as f:
            data = json.load(f)
    except Exception:
        data = {"trades": []}

    if not session_trades:
        session_trades.append({
            "agent": AGENT_NAME, "direction": "none", "pnl_usd": 0,
            "date": datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    data['trades'] = data.get('trades', []) + [norm(t) for t in session_trades]
    with open(TRADES_JSON_PATH, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  Wrote {len(session_trades)} records to agent_trades.json")

def send_telegram_alert(message):
    subprocess.run([
        "openclaw", "message", "send",
        "--channel", "telegram", "--target", TELEGRAM_UID, "--message", message
    ])

def _notify_session_end(session_name):
    """Build trade_details from session_trades and send consolidated session-end notification."""
    details = []
    for t in session_trades:
        outcome = t.get('result', 'SL')
        if outcome == 'no_trade':
            outcome = 'NO_TRADE'
        direc = (t.get('direction') or '?').upper()
        pnl   = t.get('pnl_usd', 0) or 0
        details.append({'agent': 'CRISP', 'instrument': 'BTC', 'direction': direc,
                         'outcome': outcome, 'pnl': pnl})

    traded  = sum(1 for t in session_trades if t.get('result') not in ('no_trade', 'Pending'))
    tot_pnl = sum(t.get('pnl_usd', 0) or 0 for t in session_trades)
    session_notify.session_end('CRISP', trades_count=traded, pnl=tot_pnl,
                                trade_details=details, session_name=session_name)


def send_telegram_report(session_name):
    traded = sum(1 for t in session_trades if t.get('result') not in ('no_trade', 'Pending'))
    date_s = datetime.now(timezone.utc).strftime('%b %d')
    lines  = [f"⚡ CRISP v4 — {session_name} SESSION", f"📅 {date_s} | {traded} trades", ""]

    for t in session_trades:
        result    = t.get('result', '')
        pnl       = t.get('pnl_usd', 0) or 0
        r_mult    = t.get('r_multiple', 0)
        direction = t.get('direction', '?')
        setup     = t.get('setup', 'ORB')

        if result == 'no_trade':
            note = (t.get('notes') or '')[:35]
            lines.append(f"➡️ BTC NO TRADE — {note}")
            continue

        icon = '✅' if (result.startswith('TP') or pnl > 0) else ('❌' if pnl < 0 else '➡️')
        sign = '+' if pnl >= 0 else '-'
        lines.append(f"{icon} BTC {setup} {direction} → {result} | {sign}${abs(pnl):.2f} | {r_mult}R")

    session_pnl = sum(t.get('pnl_usd', 0) or 0 for t in session_trades)
    total_pnl   = 0
    try:
        with open('/root/.openclaw/dashboard/agent_pnl.json') as f:
            total_pnl = json.load(f).get('crisp', {}).get('pnl', 0)
    except Exception:
        pass

    ss = '+' if session_pnl >= 0 else '-'
    ts = '+' if total_pnl   >= 0 else '-'
    lines += [
        "",
        f"📊 Session P&L: {ss}${abs(session_pnl):.2f}",
        f"💰 Total P&L:   {ts}${abs(total_pnl):.2f}",
        f"💼 Balance:     ${paper_balance:.2f}",
    ]
    message = "\n".join(lines)
    subprocess.run([
        "openclaw", "message", "send",
        "--channel", "telegram", "--target", TELEGRAM_UID, "--message", message
    ])
    print("  Telegram report sent.")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN SESSION RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_session(session_name):
    """
    Run a complete session.

    Strategy tiers based on score:
      < 50  : ORB only
      50-69 : ORB + sweep fade + EMA pullback + momentum
      >= 70 : all above + Swing mode (3x lots, H4 SL)
    """
    global session_trades
    session_trades = []

    print(f"\n{'='*60}")
    print(f"CRISP v4 — {session_name} SESSION | {SYMBOL}")
    print(f"Balance: ${paper_balance:.2f} | Mode: {'PAPER' if PAPER_MODE else 'LIVE'}")
    print(f"{'='*60}")
    logging.info(f"SESSION START: {session_name} | ${paper_balance:.2f}")
    hub_post(AGENT_NAME, "status",
             f"{session_name} starting. Balance: ${paper_balance:.2f}",
             tags=["session"])

    # ── Wait for session open ────────────────────────────────────────────────
    wait_for_session_open(session_name)
    session_open_time = datetime.now(timezone.utc)
    wait_for_15m_candle_close()

    # ── Session start notification (consolidated with Blade/Edge) ─────────────
    session_notify.session_start('CRISP', ['BTC'], session_name)

    # ── Strategist: score as mode selector (NOT trade gate) ──────────────────
    strat_score, strat_name, strat_bias, strat_rec, strat_notes = \
        read_strategist_recommendation()
    print(f"\n  Strategist: score={strat_score} bias={strat_bias} | {strat_notes}")
    logging.info(f"STRATEGIST [BTC_USD]: score={strat_score} bias={strat_bias} {strat_notes}")

    if strat_score >= 70:
        mode_label = "ORB + additional strategies + SWING (3x lots)"
    elif strat_score >= 50:
        mode_label = "ORB + additional strategies"
    else:
        mode_label = "ORB only (score < 50)"
    print(f"  Mode: {mode_label}")
    hub_post(AGENT_NAME, "status",
             f"{session_name} BTC score={strat_score} → {mode_label}",
             tags=["strategy"])

    # ── Pre-trade checks ─────────────────────────────────────────────────────
    print(f"\n  Pre-trade checks for {SYMBOL}...")

    lens_dir, lens_conf = read_lens_bias()
    print(f"  Lens: {lens_dir} {lens_conf:.0f}%")

    should_skip, adr_reason = run_adr_gate()
    adr = get_5day_adr()
    print(f"  {adr_reason}")
    if should_skip:
        hub_post(AGENT_NAME, "status", f"BTC ADR filtered: {adr_reason}", tags=["filter"])
        record_no_trade(session_name, adr_reason)
        write_session_trades_to_json()
        os.system("python3 /root/.openclaw/scripts/sync_agent_pnl.py")
        _notify_session_end(session_name)
        return

    orb_high, orb_low = get_orb_15m()
    if orb_high is None:
        reason = "ORB data unavailable"
        print(f"  {reason}")
        hub_post(AGENT_NAME, "error", f"BTC: {reason}", tags=["error"])
        record_no_trade(session_name, reason)
        write_session_trades_to_json()
        os.system("python3 /root/.openclaw/scripts/sync_agent_pnl.py")
        _notify_session_end(session_name)
        return

    print(f"  ORB: H=${orb_high:.0f} L=${orb_low:.0f} R=${orb_high-orb_low:.0f}")

    orb_ok, orb_reason = check_orb_quality(orb_high, orb_low)
    print(f"  {orb_reason}")
    if not orb_ok:
        record_no_trade(session_name, orb_reason)
        write_session_trades_to_json()
        os.system("python3 /root/.openclaw/scripts/sync_agent_pnl.py")
        _notify_session_end(session_name)
        return

    # Asian session: log overnight range as context
    if session_name == 'ASIAN':
        asian_high, asian_low = get_asian_session_range()
        if asian_high:
            print(f"  Asian overnight range: H=${asian_high:.0f} L=${asian_low:.0f}")
            logging.info(f"Asian range context: H={asian_high:.0f} L={asian_low:.0f}")

    # Determine ORB mode and direction filter
    prior_bias  = get_prior_day_bias()
    lens_strong = lens_conf >= LENS_THRESHOLD
    if lens_strong and lens_dir in ('bullish', 'bearish') and lens_dir == prior_bias:
        orb_mode = 'momentum_orb'
        orb_cfg  = {
            'tp1_pips': TP1_PIPS,
            'tp2_pips': int(TP2_PIPS * 1.3),
            'tp3_pips': int(TP3_PIPS * 1.6),
            'lot_size': LOT_SIZE,
            'direction_filter': lens_dir,
        }
        print(f"  Mode A: MOMENTUM ORB | Lens {lens_dir} {lens_conf:.0f}% + prior {prior_bias}")
    else:
        orb_mode = 'orb'
        orb_cfg  = {
            'tp1_pips': TP1_PIPS,
            'tp2_pips': TP2_PIPS,
            'tp3_pips': TP3_PIPS,
            'lot_size': LOT_SIZE,
            'direction_filter': lens_dir if lens_strong else None,
        }
        print(f"  Mode A: ORB standard | Lens={lens_dir} {lens_conf:.0f}%")

    hub_post(AGENT_NAME, "status",
             f"BTC {session_name} | {orb_mode} | ORB:${orb_high:.0f}/${orb_low:.0f} | {mode_label}",
             tags=["trading", session_name.lower()])

    # Preload prior session range for momentum strategy
    prior_high, prior_low = get_prior_session_range()

    # ── Monitoring loop ──────────────────────────────────────────────────────
    sess_cfg    = SESSION_TIMES[session_name]
    session_end = datetime.now(timezone.utc).replace(
        hour=sess_cfg['close_hour'], minute=sess_cfg['close_min'],
        second=0, microsecond=0
    )
    monitor_end = min(session_end, datetime.now(timezone.utc) + timedelta(hours=3))

    # Strategy fire tracking — each fires at most once per session
    strategy_fired = set()
    sweep_state    = {}
    orb_direction_seen = None  # track for EMA pullback

    print(f"\n  Monitoring until {monitor_end.strftime('%H:%M UTC')} | {mode_label}...")

    while datetime.now(timezone.utc) < monitor_end:
        now          = datetime.now(timezone.utc)
        mins_elapsed = (now - session_open_time).total_seconds() / 60
        post_orb     = mins_elapsed > 30
        has_pos      = SYMBOL in open_positions

        # ── MODE A: Daily ORB breakout (first 30 min, always) ────────────────
        if 'orb' not in strategy_fired and not post_orb and not has_pos:
            direction = check_1m_breakout(orb_high, orb_low)
            if direction:
                blocked    = False
                filter_dir = orb_cfg.get('direction_filter')
                if filter_dir == 'bullish' and direction == 'short':
                    print(f"  SHORT blocked — Lens {lens_conf:.0f}% bullish")
                    blocked = True
                elif filter_dir == 'bearish' and direction == 'long':
                    print(f"  LONG blocked — Lens {lens_conf:.0f}% bearish")
                    blocked = True

                if not blocked:
                    print(f"  ORB BREAKOUT: {direction.upper()}")
                    logging.info(f"ORB BREAKOUT: {SYMBOL} {direction.upper()} [{orb_mode}]")
                    if _try_place_order(direction, orb_high, orb_low,
                                        session_name, orb_mode, orb_cfg,
                                        strategy_score=strat_score):
                        strategy_fired.add('orb')
                        orb_direction_seen = direction

                if direction and orb_direction_seen is None:
                    orb_direction_seen = direction

        # ── Post-ORB strategies (score >= 50) ─────────────────────────────────
        if post_orb and strat_score >= 50 and not has_pos:

            # SWEEP FADE
            if 'sweep_fade' not in strategy_fired:
                sweep_dir, sweep_state = detect_liquidity_sweep(orb_high, orb_low, sweep_state)
                if sweep_dir:
                    print(f"  SWEEP FADE: {sweep_dir.upper()}")
                    logging.info(f"SWEEP FADE: {SYMBOL} {sweep_dir.upper()}")
                    orb_range = orb_high - orb_low
                    sweep_cfg = {
                        'tp1_pips': TP1_PIPS,
                        'tp2_pips': TP2_PIPS,
                        'tp3_pips': int(orb_range),
                        'lot_size': LOT_SIZE,
                    }
                    if _try_place_order(sweep_dir, orb_high, orb_low,
                                        session_name, 'sweep_fade', sweep_cfg,
                                        strategy_score=strat_score):
                        strategy_fired.add('sweep_fade')

            # EMA PULLBACK (requires established ORB direction)
            if 'ema_pullback' not in strategy_fired and orb_direction_seen:
                ema20  = get_m15_ema20()
                ep_dir = check_ema_pullback(orb_direction_seen, ema20)
                if ep_dir:
                    print(f"  EMA PULLBACK: {ep_dir.upper()} (trend: {orb_direction_seen})")
                    logging.info(f"EMA PULLBACK: {SYMBOL} {ep_dir.upper()}")
                    ep_cfg = {'tp1_pips': TP1_PIPS, 'tp2_pips': TP2_PIPS,
                              'tp3_pips': TP3_PIPS, 'lot_size': LOT_SIZE}
                    if _try_place_order(ep_dir, orb_high, orb_low,
                                        session_name, 'ema_pullback', ep_cfg,
                                        strategy_score=strat_score):
                        strategy_fired.add('ema_pullback')

            # MOMENTUM ENTRY (prior session range breakout)
            if 'momentum' not in strategy_fired:
                ema20   = get_m15_ema20()
                mom_dir = check_momentum_entry(prior_high, prior_low, ema20)
                if mom_dir:
                    print(f"  MOMENTUM ENTRY: {mom_dir.upper()}")
                    logging.info(f"MOMENTUM ENTRY: {SYMBOL} {mom_dir.upper()}")
                    mom_cfg = {'tp1_pips': TP1_PIPS, 'tp2_pips': TP2_PIPS,
                               'tp3_pips': TP3_PIPS, 'lot_size': LOT_SIZE}
                    if _try_place_order(mom_dir, orb_high, orb_low,
                                        session_name, 'momentum', mom_cfg,
                                        strategy_score=strat_score):
                        strategy_fired.add('momentum')

        # ── MODE B: Swing Trade (score >= 70, any time) ──────────────────────
        if strat_score >= 70 and 'swing' not in strategy_fired and not has_pos:
            swing_dir = check_swing_entry(strat_bias)
            if swing_dir:
                h4_sl     = get_h4_structure_level(swing_dir)
                swing_cfg = {
                    'tp1_pips': SWING_TP1_PIPS,
                    'tp2_pips': SWING_TP2_PIPS,
                    'tp3_pips': SWING_TP3_PIPS,
                    'lot_size': SWING_LOT_SIZE,
                }
                print(f"  SWING TRADE MODE B: {swing_dir.upper()} "
                      f"(bias={strat_bias} score={strat_score}) | 3x lots | H4 SL: {h4_sl}")
                logging.info(f"SWING TRADE: {SYMBOL} {swing_dir.upper()} score={strat_score}")
                if _try_place_order(swing_dir, orb_high, orb_low,
                                    session_name, 'swing', swing_cfg,
                                    stop_loss_override=h4_sl,
                                    strategy_score=strat_score):
                    strategy_fired.add('swing')

        # ── Manage open positions ─────────────────────────────────────────────
        if open_positions:
            manage_positions()

        phase = "POST-ORB" if post_orb else "ORB-WINDOW"
        print(f"  [{now.strftime('%H:%M:%S')}] {phase} | "
              f"Open: {list(open_positions.keys())} | "
              f"Fired: {list(strategy_fired)} | Balance: ${paper_balance:.2f}")
        time.sleep(30)

    # ── Force close ───────────────────────────────────────────────────────────
    if SYMBOL in open_positions:
        close_position_time_stop(SYMBOL)

    if not strategy_fired:
        already = any(t.get('result') == 'no_trade' for t in session_trades)
        if not already:
            record_no_trade(session_name, "No signal in window")

    total_trades = len([t for t in session_trades if t['result'] != 'no_trade'])
    print(f"\n{'='*60}")
    print(f"{session_name} SESSION COMPLETE | Balance: ${paper_balance:.2f} | Trades: {total_trades}")
    print(f"{'='*60}")
    logging.info(f"SESSION END: {session_name} | ${paper_balance:.2f}")
    hub_post(AGENT_NAME, "status",
             f"{session_name} complete. {total_trades} trades. Balance: ${paper_balance:.2f}",
             tags=["session", "complete"])

    write_session_trades_to_json()
    os.system("python3 /root/.openclaw/scripts/sync_agent_pnl.py")
    send_telegram_report(session_name)

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 crisp_bot.py <SESSION>")
        print("       Sessions: ASIAN | NY")
        sys.exit(1)

    session = sys.argv[1].upper()
    if session not in SESSION_TIMES:
        print(f"Unknown session '{session}'. Valid: {list(SESSION_TIMES.keys())}")
        sys.exit(1)

    run_session(session)
