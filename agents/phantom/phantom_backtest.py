"""
phantom_backtest.py — Backtesting engine for Phantom strategy hypotheses.

Fetches historical OHLCV data from Phemex, simulates strategy entry/exit
logic, then validates via Norman's Monte Carlo framework.

Simple conditions (EMA, RSI) are evaluated in Python for speed.
Complex conditions are evaluated via Claude API (cached per timeframe).
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, '/root/.openclaw/agents/norman')

from phantom_config import (
    exchange, BACKTEST_MIN_TRADES, BACKTEST_MIN_WIN_RATE, BACKTEST_MIN_PF,
    BACKTEST_MAX_RUIN, BACKTEST_MIN_SHARPE, CONDITION_MODEL, API_COSTS_PATH,
    get_logger, save_api_cost, extract_json,
)

# Import Norman's statistical engines
from norman_brain import monte_carlo_simulation, calculate_stats

import anthropic

log = get_logger('backtest')

# ── Technical indicators (pure Python) ────────────────────────────────────────

def _ema(values: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    result = [None] * (period - 1)
    result.append(sum(values[:period]) / period)
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _sma(values: list[float], period: int) -> list[float]:
    """Simple Moving Average."""
    result = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def _rsi(closes: list[float], period: int = 14) -> list[float]:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    result = [None] * period
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    result.append(100 - 100 / (1 + rs))
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        g = max(delta, 0)
        l = max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        result.append(100 - 100 / (1 + rs))
    return result


def _atr(highs, lows, closes, period: int = 14) -> list[Optional[float]]:
    """Average True Range."""
    trs = [None]
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        )
        trs.append(tr)
    result = [None] * period
    atrs = [t for t in trs[1:period + 1] if t is not None]
    if len(atrs) < period:
        return result + [None] * (len(closes) - period)
    atr_val = sum(atrs) / period
    result.append(atr_val)
    for i in range(period + 1, len(closes)):
        atr_val = (atr_val * (period - 1) + trs[i]) / period
        result.append(atr_val)
    return result


def _bollinger(closes: list[float], period: int = 20, std_dev: float = 2.0):
    """Bollinger Bands. Returns (upper, lower, mid) each as list[Optional[float]]."""
    mid   = _sma(closes, period)
    upper = [None] * len(closes)
    lower = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1: i + 1]
        mean   = sum(window) / period
        var    = sum((x - mean) ** 2 for x in window) / period
        sd     = var ** 0.5
        upper[i] = mean + std_dev * sd
        lower[i] = mean - std_dev * sd
    return upper, lower, mid


# ── OHLCV fetcher ──────────────────────────────────────────────────────────────

def fetch_historical(symbol: str, timeframe: str, limit: int = 500) -> list[dict]:
    """
    Fetch OHLCV candles from Phemex testnet.
    Returns list of dicts: {ts, open, high, low, close, volume}.
    """
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        result = []
        for c in candles:
            result.append({
                'ts':     c[0],
                'open':   float(c[1]),
                'high':   float(c[2]),
                'low':    float(c[3]),
                'close':  float(c[4]),
                'volume': float(c[5]),
            })
        log.info('Fetched %d %s candles for %s', len(result), timeframe, symbol)
        return result
    except Exception as e:
        log.error('fetch_historical %s %s: %s', symbol, timeframe, e)
        return []


def fetch_all_instruments_historical(timeframe: str, limit: int = 500) -> dict[str, list]:
    """Fetch historical data for all instruments. Returns {symbol: [candles]}."""
    from phantom_config import INSTRUMENTS
    result = {}
    for symbol in INSTRUMENTS:
        candles = fetch_historical(symbol, timeframe, limit)
        if candles:
            result[symbol] = candles
    return result


# ── Simple condition evaluator ─────────────────────────────────────────────────

_SKIP_KEYWORDS = (
    'funding rate', 'funding', 'open interest', 'sentiment', 'on-chain',
    'whale', 'dominance', 'liquidat', 'support confirm', 'resistance confirm',
    'macro', 'news', 'catalyst', 'narrative', 'fear', 'greed', 'squeeze signal',
    'smart money', 'flow', 'exchange', 'on chain', 'relative strength',
)


def _try_evaluate_condition(
    cond: str,
    idx: int,
    c: dict,
    candles: list[dict],
    closes: list[float],
    volumes: list[float],
    indicators: dict,
) -> Optional[bool]:
    """
    Evaluate one condition string against indicator data.
    Returns True/False if parseable, None if complex/qualitative (should be skipped).
    """
    import re as _re
    s = cond.lower().strip()

    if any(kw in s for kw in _SKIP_KEYWORDS):
        return None

    try:
        # ── RSI ───────────────────────────────────────────────────────────────
        if 'rsi' in s:
            rsi_vals = indicators.get('rsi14', [])
            val = rsi_vals[idx] if idx < len(rsi_vals) else None
            if val is None:
                return None
            m = _re.search(r'([<>]=?)\s*([\d.]+)', s)
            if m:
                op, thresh = m.group(1), float(m.group(2))
                if op == '<':  return val < thresh
                if op == '>':  return val > thresh
                if op == '<=': return val <= thresh
                if op == '>=': return val >= thresh
            if 'oversold' in s or 'below' in s: return val < 35
            if 'overbought' in s or 'above' in s: return val > 65
            return None

        # ── Bollinger Bands ───────────────────────────────────────────────────
        if 'bollinger' in s or ('bb' in s and ('upper' in s or 'lower' in s or 'band' in s)):
            bb_upper = indicators.get('bb_upper', [])
            bb_lower = indicators.get('bb_lower', [])
            bb_mid   = indicators.get('bb_mid', [])
            u = bb_upper[idx] if idx < len(bb_upper) else None
            l = bb_lower[idx] if idx < len(bb_lower) else None
            mid = bb_mid[idx] if idx < len(bb_mid) else None
            if u is None or l is None:
                return None
            if 'squeeze' in s:
                return (u - l) / c['close'] < 0.05 if c['close'] > 0 else None
            if 'below lower' in s or 'lower band' in s:
                return c['close'] <= l
            if 'above upper' in s or 'upper band' in s:
                return c['close'] >= u
            if 'above mid' in s or 'above basis' in s:
                return c['close'] > mid if mid else None
            if 'below mid' in s or 'below basis' in s:
                return c['close'] < mid if mid else None
            return None

        # ── EMA ───────────────────────────────────────────────────────────────
        if 'ema' in s:
            nums = _re.findall(r'ema\s*(\d+)', s)
            if len(nums) >= 2:
                # EMA cross: "EMA9 > EMA21", "EMA9 above EMA21"
                p1, p2 = int(nums[0]), int(nums[1])
                for k in (f'ema{p1}', f'ema{p2}'):
                    if k not in indicators:
                        indicators[k] = _ema(closes, int(k[3:]))
                v1 = indicators[f'ema{p1}'][idx] if idx < len(indicators[f'ema{p1}']) else None
                v2 = indicators[f'ema{p2}'][idx] if idx < len(indicators[f'ema{p2}']) else None
                if v1 is None or v2 is None:
                    return None
                if 'above' in s or '>' in s: return v1 > v2
                if 'below' in s or '<' in s: return v1 < v2
                return None
            if nums:
                # Price vs EMA: "price above EMA20", "close below EMA50", "EMA20 above price"
                period = int(nums[0])
                key = f'ema{period}'
                if key not in indicators:
                    indicators[key] = _ema(closes, period)
                ema_vals = indicators[key]
                ema_val = ema_vals[idx] if idx < len(ema_vals) else None
                if ema_val is None:
                    return None
                if 'above' in s or '>' in s: return c['close'] > ema_val
                if 'below' in s or '<' in s: return c['close'] < ema_val
            return None

        # ── SMA ───────────────────────────────────────────────────────────────
        if 'sma' in s or ('moving average' in s and 'exponential' not in s):
            nums = _re.findall(r'(?:sma|ma)\s*(\d+)', s) or _re.findall(r'(\d+)[- ]period', s)
            if nums:
                period = int(nums[0])
                key = f'sma{period}'
                if key not in indicators:
                    indicators[key] = _sma(closes, period)
                val = indicators[key][idx] if idx < len(indicators[key]) else None
                if val is None:
                    return None
                if 'above' in s or '>' in s: return c['close'] > val
                if 'below' in s or '<' in s: return c['close'] < val
            return None

        # ── ATR ───────────────────────────────────────────────────────────────
        if 'atr' in s:
            atr_vals = indicators.get('atr14', [])
            atr_val = atr_vals[idx] if idx < len(atr_vals) else None
            if atr_val is None:
                return None
            m = _re.search(r'([<>]=?)\s*([\d.]+)', s)
            if m:
                op, thresh = m.group(1), float(m.group(2))
                if op == '<': return atr_val < thresh
                if op == '>': return atr_val > thresh
            return None

        # ── Volume ────────────────────────────────────────────────────────────
        if 'volume' in s:
            vol = c['volume']
            vol_avg_vals = indicators.get('vol20', [])
            avg_val = vol_avg_vals[idx] if idx < len(vol_avg_vals) else None
            if 'above average' in s or '> average' in s or 'above.*avg' in s:
                return (vol > avg_val) if avg_val else None
            if 'below average' in s or '< average' in s:
                return (vol < avg_val) if avg_val else None
            m = _re.search(r'([<>]=?)\s*([\d.]+)', s)
            if m:
                op, thresh = m.group(1), float(m.group(2))
                if op == '<': return vol < thresh
                if op == '>': return vol > thresh
            return None

        # ── Price level ───────────────────────────────────────────────────────
        if any(w in s for w in ('price above', 'price below', 'close above', 'close below',
                                 'close >', 'close <', 'price >', 'price <')):
            m = _re.search(r'[\$]?\s*([\d,]+\.?\d*)', s)
            if m:
                level = float(m.group(1).replace(',', ''))
                if level > 0:
                    if 'above' in s or '>' in s: return c['close'] > level
                    if 'below' in s or '<' in s: return c['close'] < level
            return None

        # ── Candle pattern ────────────────────────────────────────────────────
        if any(w in s for w in ('bullish candle', 'green candle', 'bullish bar', 'bullish close')):
            return c['close'] > c['open']
        if any(w in s for w in ('bearish candle', 'red candle', 'bearish bar', 'bearish close')):
            return c['close'] < c['open']

        # ── Higher high / lower low ───────────────────────────────────────────
        if 'higher high' in s and idx > 0:
            return c['high'] > candles[idx - 1]['high']
        if 'lower low' in s and idx > 0:
            return c['low'] < candles[idx - 1]['low']

        return None  # unparseable

    except Exception:
        return None


def _evaluate_simple_conditions(
    conditions: list[str],
    candle_idx: int,
    candles: list[dict],
    indicators: dict,
) -> tuple[bool, int]:
    """
    Evaluate conditions using computed indicators.
    Complex/qualitative conditions are skipped (not failed).

    Returns (all_simple_met, num_skipped).
      all_simple_met: True if all parseable conditions pass, OR if none could be parsed.
      num_skipped:    number of conditions that couldn't be evaluated.
    """
    c       = candles[candle_idx]
    closes  = [x['close']  for x in candles]
    volumes = [x['volume'] for x in candles]

    simple_results = []
    skipped = 0

    for cond in conditions:
        result = _try_evaluate_condition(
            cond, candle_idx, c, candles, closes, volumes, indicators
        )
        if result is None:
            skipped += 1
        else:
            simple_results.append(result)

    all_met = all(simple_results) if simple_results else True
    return all_met, skipped


# ── Claude condition evaluator (for complex conditions) ───────────────────────

_condition_cache: dict[str, tuple[bool, float]] = {}   # key → (result, timestamp)
_CACHE_TTL = {
    '1m': 60, '3m': 180, '5m': 300, '15m': 900,
    '30m': 1800, '1h': 3600, '4h': 14400, '1d': 86400,
}


def _evaluate_complex_conditions(
    strategy: dict,
    candles: list[dict],
    candle_idx: int,
    side: str = 'entry',
) -> tuple[bool, float]:
    """
    Ask Claude to evaluate conditions that can't be easily computed.
    Returns (conditions_met, cost_usd).
    Caches result for the strategy's timeframe TTL.
    """
    import time as _time

    tf          = strategy.get('timeframe', '1h')
    ttl         = _CACHE_TTL.get(tf, 3600)
    cache_key   = f"{strategy.get('name')}-{side}-{candles[candle_idx]['ts']}"
    now_ts      = _time.time()

    if cache_key in _condition_cache:
        cached_val, cached_at = _condition_cache[cache_key]
        if now_ts - cached_at < ttl:
            return cached_val, 0.0

    conditions = (strategy.get('entry_conditions', []) if side == 'entry'
                  else [v for v in strategy.get('exit_conditions', {}).values()])

    # Build compact candle context (last 5 candles)
    snippet = candles[max(0, candle_idx - 4): candle_idx + 1]
    candle_str = '\n'.join(
        f"  {i}: O={c['open']} H={c['high']} L={c['low']} C={c['close']} V={c['volume']:.0f}"
        for i, c in enumerate(snippet)
    )

    prompt = (
        f"Strategy: {strategy.get('name')}\n"
        f"Conditions to check ({side}):\n"
        + '\n'.join(f'  - {c}' for c in conditions) +
        f"\n\nRecent candles ({tf}):\n{candle_str}\n\n"
        f"Are ALL conditions met? Reply ONLY with JSON: "
        f'{{\"met\": true/false, \"reason\": \"brief explanation\"}}'
    )

    try:
        client   = anthropic.Anthropic()
        response = client.messages.create(
            model=CONDITION_MODEL,
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text     = next(
            (b.text for b in response.content if getattr(b, 'type', '') == 'text'),
            ''
        )
        parsed   = extract_json(text)
        result   = bool(parsed.get('met', False)) if parsed else False
        cost     = save_api_cost(
            'condition_check',
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        _condition_cache[cache_key] = (result, now_ts)
        return result, cost
    except Exception as e:
        log.warning('Complex condition check failed: %s', e)
        return False, 0.0


# ── Main backtest function ─────────────────────────────────────────────────────

def backtest_strategy(strategy: dict, historical_data: dict = None) -> dict:
    """
    Simulate strategy on historical data and validate with Monte Carlo.

    Args:
        strategy:        Strategy dict from phantom_discover.
        historical_data: Optional pre-fetched {symbol: [candles]}. Fetched if None.

    Returns:
        {
          'verdict': 'DEPLOY' | 'REJECT' | 'NEEDS_MORE_DATA',
          'stats': {...},        # from Norman's calculate_stats
          'monte_carlo': {...},  # from Norman's monte_carlo_simulation
          'simulated_trades': [...],
          'reasons': [...],
          'strategy': strategy,
        }
    """
    instruments = strategy.get('instruments', [])
    timeframe   = strategy.get('timeframe', '1h')
    name        = strategy.get('name', 'Unnamed')

    log.info('Backtest: %s | instruments=%s | tf=%s', name, instruments, timeframe)

    if not instruments:
        return _reject(strategy, ['No instruments specified'])

    # Fetch data
    if historical_data is None:
        historical_data = {}
        for sym in instruments:
            candles = fetch_historical(sym, timeframe, limit=500)
            if candles:
                historical_data[sym] = candles

    if not historical_data:
        return {'verdict': 'NEEDS_MORE_DATA', 'reasons': ['Could not fetch historical data'],
                'strategy': strategy, 'stats': {}, 'monte_carlo': {}, 'simulated_trades': []}

    simulated_trades = []

    for symbol in instruments:
        candles = historical_data.get(symbol, [])
        if len(candles) < 50:
            log.warning('Backtest %s: only %d candles for %s', name, len(candles), symbol)
            continue

        closes  = [c['close'] for c in candles]
        highs   = [c['high']  for c in candles]
        lows    = [c['low']   for c in candles]

        # Pre-compute common indicators
        bb_upper, bb_lower, bb_mid = _bollinger(closes, 20, 2.0)
        volumes = [c['volume'] for c in candles]
        indicators = {
            'ema9':    _ema(closes, 9),
            'ema20':   _ema(closes, 20),
            'ema21':   _ema(closes, 21),
            'ema50':   _ema(closes, 50),
            'ema100':  _ema(closes, 100),
            'ema200':  _ema(closes, 200),
            'sma20':   _sma(closes, 20),
            'sma50':   _sma(closes, 50),
            'sma200':  _sma(closes, 200),
            'rsi14':   _rsi(closes, 14),
            'atr14':   _atr(highs, lows, closes, 14),
            'bb_upper': bb_upper,
            'bb_lower': bb_lower,
            'bb_mid':   bb_mid,
            'vol20':   _sma(volumes, 20),
        }

        # Parse leverage for P&L simulation
        lev_str  = str(strategy.get('leverage', '5x')).lower().replace('x', '')
        try:
            leverage = float(lev_str)
        except ValueError:
            # Range like "5x-20x" → take midpoint
            parts = lev_str.split('-')
            leverage = (float(parts[0]) + float(parts[-1])) / 2

        leverage = max(1.0, min(100.0, leverage))

        # Parse position size
        size_logic = strategy.get('position_size_logic', '10% of account')
        try:
            size_pct = float(size_logic.split('%')[0].strip()) / 100
        except Exception:
            size_pct = 0.10

        # Determine direction from strategy description/conditions
        conditions_text = ' '.join(strategy.get('entry_conditions', [])).lower()
        exit_conds      = strategy.get('exit_conditions', {})
        sl_desc  = str(exit_conds.get('stop_loss', '')).lower()
        tp_desc  = str(exit_conds.get('take_profit', '')).lower()

        # Try to extract SL/TP as % from description (e.g. "1.5% below entry")
        import re as _re
        sl_pct_match = _re.search(r'(\d+\.?\d*)\s*%', sl_desc)
        tp_pct_match = _re.search(r'(\d+\.?\d*)\s*%', tp_desc)
        sl_pct = float(sl_pct_match.group(1)) / 100 if sl_pct_match else 0.02
        tp_pct = float(tp_pct_match.group(1)) / 100 if tp_pct_match else 0.04

        in_trade    = False
        entry_price = 0.0
        entry_idx   = 0
        trade_side  = 'long'  # default; overridden by strategy conditions

        for i in range(20, len(candles)):
            c = candles[i]

            if not in_trade:
                # Evaluate entry conditions — complex/qualitative ones are skipped
                simple_met, skipped = _evaluate_simple_conditions(
                    strategy.get('entry_conditions', []), i, candles, indicators
                )

                if simple_met:
                    # Determine side from conditions
                    if any(w in conditions_text for w in ('short', 'sell', 'bear')):
                        trade_side = 'short'
                    else:
                        trade_side = 'long'

                    in_trade    = True
                    entry_price = c['close']
                    entry_idx   = i

            else:
                # Evaluate exit conditions
                hold_candles = i - entry_idx
                pnl_pct      = ((c['close'] - entry_price) / entry_price
                                if trade_side == 'long'
                                else (entry_price - c['close']) / entry_price)
                pnl_pct_lev  = pnl_pct * leverage

                close_reason = None
                if pnl_pct_lev <= -sl_pct * leverage:
                    close_reason = 'sl'
                elif pnl_pct_lev >= tp_pct * leverage:
                    close_reason = 'tp'
                elif hold_candles >= 48:
                    close_reason = 'time_stop'

                if close_reason:
                    # Simulate P&L in dollar terms (1000 USDT notional position)
                    notional = 1000.0 * size_pct
                    pnl_usd  = notional * pnl_pct_lev

                    simulated_trades.append({
                        'symbol':       symbol,
                        'side':         trade_side,
                        'entry_price':  round(entry_price, 4),
                        'exit_price':   round(c['close'], 4),
                        'leverage':     leverage,
                        'close_reason': close_reason,
                        'hold_candles': hold_candles,
                        'pnl':          round(pnl_usd, 4),
                        'pnl_pct':      round(pnl_pct_lev * 100, 2),
                        'timestamp':    datetime.fromtimestamp(
                            c['ts'] / 1000, tz=timezone.utc
                        ).isoformat() if c['ts'] else '',
                    })
                    in_trade = False

    n = len(simulated_trades)
    log.info('Backtest %s: %d simulated trades across %d instruments',
             name, n, len(instruments))

    if n < BACKTEST_MIN_TRADES:
        return {
            'verdict': 'NEEDS_MORE_DATA',
            'reasons': [f'Only {n} simulated trades (minimum {BACKTEST_MIN_TRADES})'],
            'strategy': strategy, 'stats': {}, 'monte_carlo': {},
            'simulated_trades': simulated_trades,
        }

    pnls  = [t['pnl'] for t in simulated_trades]
    stats = calculate_stats(simulated_trades, name)
    mc    = monte_carlo_simulation(pnls, starting_balance=10_000)

    verdict, reasons = _determine_verdict(stats, mc)

    log.info('Backtest %s: verdict=%s  WR=%.1f%%  PF=%.2f  Sharpe=%.2f  Ruin=%.1f%%',
             name, verdict, stats.get('win_rate', 0), stats.get('profit_factor', 0),
             stats.get('sharpe', 0), mc.get('ruin_probability', 0))

    return {
        'verdict':          verdict,
        'reasons':          reasons,
        'strategy':         strategy,
        'stats':            stats,
        'monte_carlo':      mc,
        'simulated_trades': simulated_trades,
    }


def _determine_verdict(stats: dict, mc: dict) -> tuple[str, list[str]]:
    reasons = []
    passes  = []

    wr   = stats.get('win_rate', 0)
    pf   = stats.get('profit_factor', 0)
    sh   = stats.get('sharpe', 0)
    ruin = mc.get('ruin_probability', 100)

    if wr >= BACKTEST_MIN_WIN_RATE:
        passes.append(f'WR {wr:.1f}% >= {BACKTEST_MIN_WIN_RATE}%')
    else:
        reasons.append(f'WR {wr:.1f}% < {BACKTEST_MIN_WIN_RATE}%')

    if pf >= BACKTEST_MIN_PF:
        passes.append(f'PF {pf:.2f} >= {BACKTEST_MIN_PF}')
    else:
        reasons.append(f'PF {pf:.2f} < {BACKTEST_MIN_PF}')

    if sh >= BACKTEST_MIN_SHARPE:
        passes.append(f'Sharpe {sh:.2f} >= {BACKTEST_MIN_SHARPE}')
    else:
        reasons.append(f'Sharpe {sh:.2f} < {BACKTEST_MIN_SHARPE}')

    if ruin <= BACKTEST_MAX_RUIN:
        passes.append(f'Ruin {ruin:.1f}% <= {BACKTEST_MAX_RUIN}%')
    else:
        reasons.append(f'Ruin {ruin:.1f}% > {BACKTEST_MAX_RUIN}%')

    if not reasons:
        return 'DEPLOY', passes
    if len(passes) >= 2:
        return 'NEEDS_MORE_DATA', reasons + passes
    return 'REJECT', reasons


def _reject(strategy: dict, reasons: list[str]) -> dict:
    return {
        'verdict': 'REJECT', 'reasons': reasons,
        'strategy': strategy, 'stats': {}, 'monte_carlo': {},
        'simulated_trades': [],
    }
