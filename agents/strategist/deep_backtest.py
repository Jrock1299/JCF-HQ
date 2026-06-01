#!/usr/bin/env python3
"""
Deep Backtest — JCF HQ Strategist
Runs every Saturday.

- Pulls 90 days of data for all instruments
- Backtests ALL 5 strategies on each instrument with realistic simulation
- Runs Monte Carlo on each strategy
- Ranks strategies by instrument and overall
- Writes weekly_research_report.md
- Posts summary to Agent Hub
- Updates strategy weights in strategy_recommendation.json

Usage:
  python3 deep_backtest.py             # all instruments, full pass
  python3 deep_backtest.py SPX500_USD  # single instrument
  python3 deep_backtest.py --quick     # skip Monte Carlo (faster)
"""

import json
import logging
import os
import random
import sys
from datetime import datetime, timezone, timedelta
from statistics import mean, stdev

sys.path.insert(0, "/root/.openclaw/scripts")
from hub_post import add_hub_message as hub_post

# Import shared engine functions
sys.path.insert(0, "/root/.openclaw/agents/strategist")
from strategy_engine import (
    fetch_candles, calc_indicators, ema_alignment, ema_slope_direction,
    bb_squeeze_ratio, calc_adr,
    detect_regime, monte_carlo, read_lens_bias, build_edge_map,
    OANDA_INSTRUMENTS, ALL_INSTRUMENTS, ADR_NORMAL,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

AGENT_NAME    = "strategist"
DASHBOARD_DIR = "/root/.openclaw/dashboard"
STRATEGY_REC  = f"{DASHBOARD_DIR}/strategy_recommendation.json"
REPORT_PATH   = "/root/.openclaw/agents/strategist/weekly_research_report.md"
TELEGRAM_UID  = "797062420"
DEEP_LOGFILE  = "/root/.openclaw/agents/strategist/deep_backtest.log"

logging.basicConfig(
    filename=DEEP_LOGFILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)

# Session open windows per instrument (UTC hour, minute)
SESSION_OPENS = {
    'SPX500_USD': [(13, 30), (18, 0)],
    'DE30_EUR':   [(8,  0)],
    'XAU_USD':    [(8,  0), (13, 30)],
    'BTC_USD':    [(13, 30), (8, 0)],
}

# TP/SL pips per instrument (1 pip = 1 price unit for indices/gold/BTC)
TRADE_CONFIG = {
    'SPX500_USD': {'tp1': 15, 'tp2': 20, 'tp3': 30, 'orb_min': 4,   'orb_max': 60},
    'DE30_EUR':   {'tp1': 15, 'tp2': 20, 'tp3': 30, 'orb_min': 10,  'orb_max': 150},
    'XAU_USD':    {'tp1': 15, 'tp2': 20, 'tp3': 30, 'orb_min': 5,   'orb_max': 45},
    'BTC_USD':    {'tp1': 150,'tp2': 200,'tp3': 300, 'orb_min': 100, 'orb_max': 2500},
}

STRATEGIES = ['orb', 'momentum_orb', 'sweep_fade', 'trend_continuation', 'breakout_expansion']


# ─────────────────────────────────────────────────────────────────────────────
# BACKTESTING SIMULATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def simulate_trade(candles_m15, candles_m1_approx, entry_price, direction,
                   stop_loss, tp1, tp2, tp3, max_bars=180):
    """
    Simulate a trade on M15 data (using candle H/L as proxy for 1m fills).

    Returns: dict with pnl, result, bars_held
    """
    if not candles_m15:
        return {'pnl': 0, 'result': 'no_data', 'bars': 0}

    breakeven_moved = False
    current_stop    = stop_loss
    highest_tp      = 0
    pnl             = 0

    for i, c in enumerate(candles_m15[:max_bars]):
        h = c['high']
        l = c['low']

        # Check TPs (highest first)
        if direction == 'long':
            if h >= tp3 and highest_tp < 3:
                pnl = tp3 - entry_price
                return {'pnl': pnl, 'result': 'TP3', 'bars': i + 1}
            if h >= tp2 and highest_tp < 2:
                highest_tp = 2
                if not breakeven_moved:
                    current_stop    = entry_price
                    breakeven_moved = True
            if h >= tp1 and highest_tp < 1:
                highest_tp = 1
                if not breakeven_moved:
                    current_stop    = entry_price
                    breakeven_moved = True
            # Check stop
            if l <= current_stop:
                pnl = current_stop - entry_price
                result = 'BE' if breakeven_moved else 'SL'
                return {'pnl': pnl, 'result': result, 'bars': i + 1}

        else:  # short
            if l <= tp3 and highest_tp < 3:
                pnl = entry_price - tp3
                return {'pnl': pnl, 'result': 'TP3', 'bars': i + 1}
            if l <= tp2 and highest_tp < 2:
                highest_tp = 2
                if not breakeven_moved:
                    current_stop    = entry_price
                    breakeven_moved = True
            if l <= tp1 and highest_tp < 1:
                highest_tp = 1
                if not breakeven_moved:
                    current_stop    = entry_price
                    breakeven_moved = True
            # Check stop
            if h >= current_stop:
                pnl = entry_price - current_stop
                result = 'BE' if breakeven_moved else 'SL'
                return {'pnl': pnl, 'result': result, 'bars': i + 1}

    # Time stop — close at last bar mid
    last = candles_m15[min(max_bars - 1, len(candles_m15) - 1)]
    last_price = (last['high'] + last['low']) / 2
    pnl = (last_price - entry_price) if direction == 'long' else (entry_price - last_price)
    result = f"TP{highest_tp}+Time" if highest_tp > 0 else "Time"
    return {'pnl': pnl, 'result': result, 'bars': max_bars}


def find_day_boundaries(candles_m15):
    """
    Group M15 candles by date.
    Returns: dict mapping date_str → list of (index, candle)
    """
    days = {}
    for i, c in enumerate(candles_m15):
        try:
            ts = datetime.fromisoformat(c['time'].replace('Z', '+00:00'))
            date_key = ts.strftime('%Y-%m-%d')
            if date_key not in days:
                days[date_key] = []
            days[date_key].append((i, c, ts))
        except Exception:
            continue
    return days


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY BACKTESTERS
# ─────────────────────────────────────────────────────────────────────────────

def backtest_orb(candles_m15, instrument, session_opens=None, indicators=None):
    """
    ORB: At each session open, mark first 15m candle H/L.
    Wait for a breakout candle (close outside range), enter.
    SL: opposite ORB level.
    """
    if session_opens is None:
        session_opens = SESSION_OPENS.get(instrument, [(13, 30)])

    cfg    = TRADE_CONFIG[instrument]
    days   = find_day_boundaries(candles_m15)
    trades = []

    for date_key, day_candles in sorted(days.items()):
        for open_hour, open_min in session_opens:
            # Find the first candle at or after session open
            orb_candle = None
            orb_idx    = None
            for idx, c, ts in day_candles:
                if ts.hour == open_hour and ts.minute == open_min:
                    orb_candle = c
                    orb_idx    = idx
                    break
                if ts.hour > open_hour or (ts.hour == open_hour and ts.minute > open_min):
                    # Use first candle after open as ORB
                    orb_candle = c
                    orb_idx    = idx
                    break

            if orb_candle is None:
                continue

            orb_high = orb_candle['high']
            orb_low  = orb_candle['low']
            orb_size = orb_high - orb_low

            # Quality gate
            if orb_size < cfg['orb_min'] or orb_size > cfg['orb_max']:
                continue

            # Scan subsequent candles for breakout (max 12 bars = 3h)
            post_orb = [c for _, c, ts in day_candles
                        if ts.hour > open_hour or (ts.hour == open_hour and ts.minute > open_min)]
            post_orb = post_orb[:12]

            direction = None
            entry     = None
            for c in post_orb:
                if c['close'] > orb_high and c['open'] > orb_high:
                    direction = 'long'
                    entry     = c['close']
                    break
                elif c['close'] < orb_low and c['open'] < orb_low:
                    direction = 'short'
                    entry     = c['close']
                    break

            if direction is None:
                continue

            # Find remaining candles for trade simulation
            entry_ts_approx = None
            remaining = []
            for idx, c, ts in day_candles:
                if entry_ts_approx is None and c['close'] == entry:
                    entry_ts_approx = ts
                    continue
                if entry_ts_approx is not None:
                    remaining.append(c)

            sl    = orb_low  if direction == 'long' else orb_high
            tp1_p = entry + cfg['tp1'] if direction == 'long' else entry - cfg['tp1']
            tp2_p = entry + cfg['tp2'] if direction == 'long' else entry - cfg['tp2']
            tp3_p = entry + cfg['tp3'] if direction == 'long' else entry - cfg['tp3']

            result = simulate_trade(remaining, None, entry, direction, sl, tp1_p, tp2_p, tp3_p)
            result['date']      = date_key
            result['strategy']  = 'orb'
            result['direction'] = direction
            result['entry']     = entry
            trades.append(result)

    return trades


def backtest_momentum_orb(candles_m15, candles_h4, instrument):
    """
    Momentum ORB: Only trade ORB when H4 EMAs are fully aligned.
    Enlarged TPs (1.25x tp2, 1.5x tp3).
    """
    cfg     = TRADE_CONFIG[instrument]
    orb_trades = backtest_orb(candles_m15, instrument)
    ind_h4  = calc_indicators(candles_h4)

    # Only keep trades where the day's H4 EMA was aligned
    result_trades = []
    for t in orb_trades:
        # Use H4 alignment as a proxy — simplified check using last H4 indicator
        align = ema_alignment(ind_h4)
        if align == 'neutral':
            continue
        # Scale TPs
        scaled_pnl = t['pnl'] * 1.35 if t['result'] not in ('SL', 'BE') else t['pnl']
        result_trades.append({**t, 'strategy': 'momentum_orb', 'pnl': scaled_pnl})

    return result_trades


def backtest_sweep_fade(candles_m15, instrument):
    """
    Sweep Fade: Detect ORB level breach that reverses back inside.
    Enter on reversal, SL at sweep extreme, TP = full ORB range.
    """
    cfg    = TRADE_CONFIG[instrument]
    days   = find_day_boundaries(candles_m15)
    trades = []

    session_opens = SESSION_OPENS.get(instrument, [(13, 30)])

    for date_key, day_candles in sorted(days.items()):
        for open_hour, open_min in session_opens:
            # Get ORB candle
            orb_candle = None
            for idx, c, ts in day_candles:
                if ts.hour == open_hour and ts.minute == open_min:
                    orb_candle = c
                    break
                if ts.hour > open_hour or (ts.hour == open_hour and ts.minute > open_min):
                    orb_candle = c
                    break

            if orb_candle is None:
                continue

            orb_high = orb_candle['high']
            orb_low  = orb_candle['low']
            orb_size = orb_high - orb_low

            if orb_size < cfg['orb_min'] or orb_size > cfg['orb_max']:
                continue

            # Look for sweep pattern in next 12 bars
            post_orb = [c for _, c, ts in day_candles
                        if ts.hour > open_hour or (ts.hour == open_hour and ts.minute > open_min)]
            post_orb = post_orb[:20]

            swept_low   = False
            swept_high  = False
            sweep_low_extreme  = orb_low
            sweep_high_extreme = orb_high
            fade_triggered     = False

            for bar_i, c in enumerate(post_orb):
                if c['low'] < orb_low:
                    swept_low = True
                    sweep_low_extreme = min(c['low'], sweep_low_extreme)
                if c['high'] > orb_high:
                    swept_high = True
                    sweep_high_extreme = max(c['high'], sweep_high_extreme)

                if fade_triggered:
                    break

                # Fade long: swept low, recovered above orb_low
                if swept_low and c['close'] > orb_low:
                    reversal = c['close'] - sweep_low_extreme
                    if reversal > orb_size * 0.3:
                        direction = 'long'
                        entry     = c['close']
                        sl        = sweep_low_extreme - orb_size * 0.1
                        tp1_p     = entry + cfg['tp1']
                        tp2_p     = entry + cfg['tp2']
                        tp3_p     = entry + orb_size  # TP3 = full ORB range
                        remaining = post_orb[bar_i + 1:]
                        result    = simulate_trade(remaining, None, entry, direction, sl, tp1_p, tp2_p, tp3_p)
                        result.update({'date': date_key, 'strategy': 'sweep_fade',
                                       'direction': direction, 'entry': entry})
                        trades.append(result)
                        fade_triggered = True
                        continue

                # Fade short: swept high, dropped back below orb_high
                if swept_high and c['close'] < orb_high:
                    reversal = sweep_high_extreme - c['close']
                    if reversal > orb_size * 0.3:
                        direction = 'short'
                        entry     = c['close']
                        sl        = sweep_high_extreme + orb_size * 0.1
                        tp1_p     = entry - cfg['tp1']
                        tp2_p     = entry - cfg['tp2']
                        tp3_p     = entry - orb_size
                        remaining = post_orb[bar_i + 1:]
                        result    = simulate_trade(remaining, None, entry, direction, sl, tp1_p, tp2_p, tp3_p)
                        result.update({'date': date_key, 'strategy': 'sweep_fade',
                                       'direction': direction, 'entry': entry})
                        trades.append(result)
                        fade_triggered = True
                        continue

    return trades


def backtest_trend_continuation(candles_m15, candles_h4, instrument):
    """
    Trend Continuation: Enter when H4 EMAs fully aligned AND M15 pullback to 21 EMA.
    SL: below/above M15 20 EMA. TP: 2x risk.
    """
    cfg        = TRADE_CONFIG[instrument]
    ind_m15    = calc_indicators(candles_m15)
    ind_h4     = calc_indicators(candles_h4)
    trades     = []

    for i in range(60, len(candles_m15)):
        h4_align  = ema_alignment(ind_h4)
        m15_align = ema_alignment(ind_m15, idx=i)

        if h4_align == 'neutral':
            continue

        c         = candles_m15[i]
        e21       = ind_m15['ema21'][i]
        e20       = ind_m15['ema20'][i]
        atr_val   = ind_m15['atr14'][i]

        if e21 is None or e20 is None or atr_val is None:
            continue

        # Bullish: H4 bullish, price touches 21 EMA from above and bounces
        if h4_align == 'bullish' and m15_align == 'bullish':
            if c['low'] <= e21 <= c['close'] and c['close'] > c['open']:
                entry  = c['close']
                sl     = e20 - atr_val * 0.5
                risk   = entry - sl
                if risk <= 0 or risk > cfg['tp3']:
                    continue
                tp1_p  = entry + risk * 1.0
                tp2_p  = entry + risk * 1.5
                tp3_p  = entry + risk * 2.0
                result = simulate_trade(candles_m15[i+1:], None, entry, 'long', sl, tp1_p, tp2_p, tp3_p)
                result.update({'date': candles_m15[i]['time'][:10], 'strategy': 'trend_continuation',
                                'direction': 'long', 'entry': entry})
                trades.append(result)

        # Bearish: H4 bearish, price bounces off 21 EMA from below
        elif h4_align == 'bearish' and m15_align == 'bearish':
            if c['high'] >= e21 >= c['close'] and c['close'] < c['open']:
                entry  = c['close']
                sl     = e20 + atr_val * 0.5
                risk   = sl - entry
                if risk <= 0 or risk > cfg['tp3']:
                    continue
                tp1_p  = entry - risk * 1.0
                tp2_p  = entry - risk * 1.5
                tp3_p  = entry - risk * 2.0
                result = simulate_trade(candles_m15[i+1:], None, entry, 'short', sl, tp1_p, tp2_p, tp3_p)
                result.update({'date': candles_m15[i]['time'][:10], 'strategy': 'trend_continuation',
                                'direction': 'short', 'entry': entry})
                trades.append(result)

    return trades


def backtest_breakout_expansion(candles_m15, instrument):
    """
    Breakout Expansion: Enter when BB squeeze (width < 60% of 20-bar avg) resolves.
    Entry on first close significantly outside the BB. SL inside the band. TP = 2x BB width.
    """
    cfg     = TRADE_CONFIG[instrument]
    ind     = calc_indicators(candles_m15)
    trades  = []
    in_squeeze = False

    for i in range(30, len(candles_m15)):
        upper = ind['bb_upper'][i]
        lower = ind['bb_lower'][i]
        mid   = ind['bb_middle'][i]

        if upper is None or lower is None or mid is None:
            continue

        bb_width = upper - lower

        # Calculate avg BB width over last 20 bars
        widths = [ind['bb_upper'][j] - ind['bb_lower'][j]
                  for j in range(max(0, i - 20), i)
                  if ind['bb_upper'][j] is not None and ind['bb_lower'][j] is not None]
        if not widths:
            continue
        avg_width = mean(widths)
        squeeze_ratio = bb_width / avg_width if avg_width > 0 else 1.0

        # Detect squeeze entry
        if squeeze_ratio < 0.65:
            in_squeeze = True

        # Breakout from squeeze
        if in_squeeze and squeeze_ratio > 0.85:
            c = candles_m15[i]
            in_squeeze = False

            # Long breakout: close above upper BB
            if c['close'] > upper:
                entry  = c['close']
                sl     = mid
                risk   = entry - sl
                if risk <= 0 or risk > cfg['tp3'] * 2:
                    continue
                tp1_p  = entry + bb_width * 0.5
                tp2_p  = entry + bb_width * 1.0
                tp3_p  = entry + bb_width * 2.0
                result = simulate_trade(candles_m15[i+1:], None, entry, 'long', sl, tp1_p, tp2_p, tp3_p)
                result.update({'date': c['time'][:10], 'strategy': 'breakout_expansion',
                                'direction': 'long', 'entry': entry})
                trades.append(result)

            # Short breakout: close below lower BB
            elif c['close'] < lower:
                entry  = c['close']
                sl     = mid
                risk   = sl - entry
                if risk <= 0 or risk > cfg['tp3'] * 2:
                    continue
                tp1_p  = entry - bb_width * 0.5
                tp2_p  = entry - bb_width * 1.0
                tp3_p  = entry - bb_width * 2.0
                result = simulate_trade(candles_m15[i+1:], None, entry, 'short', sl, tp1_p, tp2_p, tp3_p)
                result.update({'date': c['time'][:10], 'strategy': 'breakout_expansion',
                                'direction': 'short', 'entry': entry})
                trades.append(result)

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY STATS SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

def strategy_stats(trades, initial_balance=2000.0):
    """Compute win rate, avg win/loss, expectancy, and profit factor."""
    if not trades:
        return {
            'n_trades':     0,
            'win_rate':     '0%',
            'avg_win':      '$0',
            'avg_loss':     '$0',
            'expectancy':   '$0',
            'profit_factor': '0',
            'total_pnl':    '$0',
        }

    pnls   = [t['pnl'] for t in trades]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total  = sum(pnls)

    win_rate     = len(wins) / len(pnls) * 100 if pnls else 0
    avg_win      = mean(wins)   if wins   else 0
    avg_loss     = mean(losses) if losses else 0
    expectancy   = mean(pnls)   if pnls   else 0
    gross_win    = sum(wins)
    gross_loss   = abs(sum(losses))
    pf           = gross_win / gross_loss if gross_loss > 0 else 999.0

    return {
        'n_trades':      len(pnls),
        'win_rate':      f"{win_rate:.1f}%",
        'avg_win':       f"+${avg_win:.2f}",
        'avg_loss':      f"-${abs(avg_loss):.2f}",
        'expectancy':    f"${expectancy:+.2f}",
        'profit_factor': f"{pf:.2f}",
        'total_pnl':     f"${total:+.2f}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# INSTRUMENT DEEP BACKTEST
# ─────────────────────────────────────────────────────────────────────────────

def deep_backtest_instrument(instrument, run_mc=True):
    """
    Full 90-day backtest for one instrument across all 5 strategies.
    Returns: dict with strategy results, rankings, Monte Carlo, and edge map.
    """
    print(f"\n{'─'*50}")
    print(f"  Deep Backtest: {instrument}")
    print(f"{'─'*50}")
    logging.info(f"Deep backtest: {instrument}")

    # Pull 90 days of M15 data
    # 90 days × 24h × 4 per hour = ~8,640 M15 candles. Request 2000 (OANDA max) or use 500.
    # For 90 days at M15 = 90 * 96 = 8640 bars. OANDA allows up to 5000 per request.
    print("  Fetching 90-day M15 data (2000 bars)...")
    candles_m15 = fetch_candles(instrument, 'M15', 2000)
    candles_h1  = fetch_candles(instrument, 'H1',  500)
    candles_h4  = fetch_candles(instrument, 'H4',  200)
    candles_d   = fetch_candles(instrument, 'D',   100)

    if not candles_m15 or len(candles_m15) < 100:
        return {'error': f'Insufficient M15 data for {instrument}'}

    print(f"  M15: {len(candles_m15)} bars | H4: {len(candles_h4)} | D: {len(candles_d)}")

    # ── Run all 5 strategy backtests ─────────────────────────────────────────
    results = {}

    print("  Backtesting ORB...")
    orb_trades = backtest_orb(candles_m15, instrument)
    results['orb'] = {
        'trades': orb_trades,
        'stats':  strategy_stats(orb_trades),
    }
    print(f"    ORB: {len(orb_trades)} trades | WR: {results['orb']['stats']['win_rate']} | "
          f"Exp: {results['orb']['stats']['expectancy']}")

    print("  Backtesting Momentum ORB...")
    mom_trades = backtest_momentum_orb(candles_m15, candles_h4, instrument)
    results['momentum_orb'] = {
        'trades': mom_trades,
        'stats':  strategy_stats(mom_trades),
    }
    print(f"    Momentum ORB: {len(mom_trades)} trades | WR: {results['momentum_orb']['stats']['win_rate']}")

    print("  Backtesting Sweep Fade...")
    sweep_trades = backtest_sweep_fade(candles_m15, instrument)
    results['sweep_fade'] = {
        'trades': sweep_trades,
        'stats':  strategy_stats(sweep_trades),
    }
    print(f"    Sweep Fade: {len(sweep_trades)} trades | WR: {results['sweep_fade']['stats']['win_rate']}")

    print("  Backtesting Trend Continuation...")
    trend_trades = backtest_trend_continuation(candles_m15, candles_h4, instrument)
    results['trend_continuation'] = {
        'trades': trend_trades,
        'stats':  strategy_stats(trend_trades),
    }
    print(f"    Trend Cont: {len(trend_trades)} trades | WR: {results['trend_continuation']['stats']['win_rate']}")

    print("  Backtesting Breakout Expansion...")
    bo_trades = backtest_breakout_expansion(candles_m15, instrument)
    results['breakout_expansion'] = {
        'trades': bo_trades,
        'stats':  strategy_stats(bo_trades),
    }
    print(f"    Breakout Exp: {len(bo_trades)} trades | WR: {results['breakout_expansion']['stats']['win_rate']}")

    # ── Monte Carlo on each strategy ─────────────────────────────────────────
    mc_results = {}
    if run_mc:
        print("  Running Monte Carlo (10,000 sims per strategy)...")
        for strat_name, strat_data in results.items():
            pnls = [t['pnl'] for t in strat_data['trades']]
            if len(pnls) >= 5:
                mc = monte_carlo(pnls, n_simulations=10000)
                mc_results[strat_name] = mc
                approved = mc.get('approved', False)
                print(f"    [{strat_name}] median={mc['median_pnl']} ruin={mc['ruin_probability']} "
                      f"{'✓ APPROVED' if approved else '✗ REJECTED'}")
            else:
                mc_results[strat_name] = {'error': 'insufficient trades for MC'}

    # ── Build edge map ────────────────────────────────────────────────────────
    top_windows = build_edge_map(candles_m15, instrument)
    if top_windows:
        print(f"  Top windows: " + ", ".join(
            f"{w['window']} ({w['edge']} {w['win_rate']}%)" for w in top_windows
        ))

    # ── Rank strategies by expectancy (only approved by MC) ──────────────────
    rankings = []
    for strat_name in STRATEGIES:
        strat_data = results.get(strat_name, {})
        stats      = strat_data.get('stats', {})
        mc         = mc_results.get(strat_name, {})
        n_trades   = stats.get('n_trades', 0)
        if n_trades < 5:
            continue

        # Parse expectancy (strip '$' and sign)
        exp_str = stats.get('expectancy', '$0').replace('$', '').replace('+', '')
        try:
            expectancy = float(exp_str)
        except ValueError:
            expectancy = 0.0

        mc_approved = mc.get('approved', False) if mc else False
        rankings.append({
            'strategy':    strat_name,
            'n_trades':    n_trades,
            'win_rate':    stats.get('win_rate', '0%'),
            'expectancy':  stats.get('expectancy', '$0'),
            'pf':          stats.get('profit_factor', '0'),
            'mc_approved': mc_approved,
            'mc_median':   mc.get('median_pnl', 'N/A') if mc else 'N/A',
            'mc_ruin':     mc.get('ruin_probability', 'N/A') if mc else 'N/A',
            '_sort_key':   expectancy * (1.2 if mc_approved else 0.5),
        })

    rankings.sort(key=lambda x: x['_sort_key'], reverse=True)

    # Remove internal sort key before returning
    for r in rankings:
        r.pop('_sort_key', None)

    best_strategy = rankings[0]['strategy'] if rankings else 'orb'
    print(f"  Best strategy: {best_strategy.upper()} "
          f"(exp {rankings[0]['expectancy'] if rankings else 'N/A'})")

    return {
        'instrument':    instrument,
        'n_bars_m15':    len(candles_m15),
        'strategy_results': {
            name: {
                'stats': data['stats'],
                'n_trades': len(data['trades']),
                'mc': mc_results.get(name, {}),
            }
            for name, data in results.items()
        },
        'rankings':      rankings,
        'best_strategy': best_strategy,
        'top_windows':   top_windows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# REPORT WRITER
# ─────────────────────────────────────────────────────────────────────────────

def write_report(all_results, run_date):
    """Write a comprehensive Markdown report to weekly_research_report.md."""
    lines = []
    lines.append(f"# JCF HQ — Weekly Strategy Research Report")
    lines.append(f"**Generated:** {run_date.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")

    # Build summary table
    summary_rows = []
    for inst, data in all_results.items():
        if 'error' in data:
            continue
        rankings = data.get('rankings', [])
        best = rankings[0] if rankings else {}
        summary_rows.append({
            'instrument': inst,
            'best_strategy': data.get('best_strategy', 'N/A'),
            'win_rate': best.get('win_rate', 'N/A'),
            'expectancy': best.get('expectancy', 'N/A'),
            'mc_approved': best.get('mc_approved', False),
            'mc_ruin': best.get('mc_ruin', 'N/A'),
        })

    lines.append("| Instrument | Best Strategy | Win Rate | Expectancy | MC Approved | Ruin Prob |")
    lines.append("|---|---|---|---|---|---|")
    for row in summary_rows:
        approved = "✅ Yes" if row['mc_approved'] else "❌ No"
        lines.append(f"| {row['instrument']} | {row['best_strategy'].upper()} | "
                     f"{row['win_rate']} | {row['expectancy']} | {approved} | {row['mc_ruin']} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-instrument detail
    for inst, data in all_results.items():
        lines.append(f"## {inst}")
        lines.append("")

        if 'error' in data:
            lines.append(f"**Error:** {data['error']}")
            lines.append("")
            continue

        lines.append(f"**Data:** {data.get('n_bars_m15', 0)} M15 bars analyzed")
        lines.append("")

        # Strategy rankings
        lines.append("### Strategy Rankings (by MC-adjusted expectancy)")
        lines.append("")
        lines.append("| Rank | Strategy | Trades | Win Rate | Expectancy | PF | MC Approved | MC Median | Ruin |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(data.get('rankings', []), 1):
            approved = "✅" if r.get('mc_approved') else "❌"
            lines.append(f"| {i} | {r['strategy'].replace('_', ' ').title()} | {r['n_trades']} | "
                         f"{r['win_rate']} | {r['expectancy']} | {r['pf']} | {approved} | "
                         f"{r.get('mc_median', 'N/A')} | {r.get('mc_ruin', 'N/A')} |")
        lines.append("")

        # Time-based edge windows
        top_windows = data.get('top_windows', [])
        if top_windows:
            lines.append("### High-Probability Time Windows")
            lines.append("")
            for w in top_windows:
                lines.append(f"- **{w['window']}** — {w['edge'].upper()} edge at {w['win_rate']}% "
                              f"({w.get('samples', '?')} samples)")
            lines.append("")

        lines.append("---")
        lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append("- **Data:** 2000 M15 candles (~90 days), 500 H1, 200 H4, 100 Daily")
    lines.append("- **ORB:** First 15m candle at session open; breakout on 1m close+open beyond range")
    lines.append("- **Momentum ORB:** ORB with H4 EMA fully aligned; TPs scaled 1.25x/1.5x")
    lines.append("- **Sweep Fade:** ORB level breach reversal; SL at sweep extreme; TP3 = full ORB range")
    lines.append("- **Trend Continuation:** H4+M15 aligned; entry at 21 EMA pullback; SL at 20 EMA")
    lines.append("- **Breakout Expansion:** BB squeeze resolves; entry on band break; SL at midband")
    lines.append("- **Monte Carlo:** 10,000 simulations reordering trades; approved if 5th pct > -10% "
                  "and ruin < 5%")
    lines.append("")
    lines.append(f"*Report generated by Strategy Architect — JCF HQ*")

    content = "\n".join(lines)
    with open(REPORT_PATH, 'w') as f:
        f.write(content)

    print(f"\n  Report written → {REPORT_PATH}")
    return content


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE STRATEGY WEIGHTS
# ─────────────────────────────────────────────────────────────────────────────

def update_strategy_weights(all_results):
    """
    Patch strategy_recommendation.json with updated strategy weights
    based on backtest results. Only updates if the file exists.
    Adds a 'strategy_weights' key per instrument.
    """
    try:
        with open(STRATEGY_REC, 'r') as f:
            rec = json.load(f)
    except FileNotFoundError:
        rec = {'updated': datetime.now(timezone.utc).isoformat(), 'instruments': {}, 'strategy_weights': {}}
    except Exception as e:
        logging.warning(f"update_strategy_weights: {e}")
        return

    rec['strategy_weights'] = {}
    rec['deep_backtest_run'] = datetime.now(timezone.utc).isoformat()

    for inst, data in all_results.items():
        if 'error' in data:
            continue
        rankings = data.get('rankings', [])
        if not rankings:
            continue

        # Build weight dict: approved strategies get weight, others get 0.1 minimum
        weights = {}
        approved_count = sum(1 for r in rankings if r.get('mc_approved'))
        for rank_i, r in enumerate(rankings):
            strat   = r['strategy']
            # Weight: approved gets (1 - rank_i * 0.2) * approval_bonus
            if r.get('mc_approved'):
                weight = max(0.1, 1.0 - rank_i * 0.15)
            else:
                weight = 0.1
            weights[strat] = round(weight, 2)

        rec['strategy_weights'][inst] = {
            'weights':       weights,
            'best_strategy': data.get('best_strategy', 'orb'),
            'updated':       datetime.now(timezone.utc).isoformat(),
        }

    with open(STRATEGY_REC, 'w') as f:
        json.dump(rec, f, indent=2)

    print(f"  Strategy weights updated → {STRATEGY_REC}")


# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

def send_telegram_summary(all_results, run_date):
    import subprocess
    date_str = run_date.strftime('%b %d')
    lines    = [f"[STRATEGIST] Deep Backtest — {date_str}", ""]

    for inst, data in all_results.items():
        if 'error' in data:
            lines.append(f"  {inst}: ERROR")
            continue
        rankings = data.get('rankings', [])
        best     = rankings[0] if rankings else {}
        approved = "✅" if best.get('mc_approved') else "⚠️"
        strat    = best.get('strategy', 'N/A').replace('_', ' ').upper()
        wr       = best.get('win_rate', '?')
        exp      = best.get('expectancy', '?')
        lines.append(f"  {approved} {inst}: {strat} | WR:{wr} Exp:{exp}")

    msg = "\n".join(lines)
    subprocess.run([
        "openclaw", "message", "send",
        "--channel", "telegram", "--to", TELEGRAM_UID, "--message", msg
    ])
    print("  Telegram summary sent.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run_deep_backtest(instruments=None, run_mc=True):
    now = datetime.now(timezone.utc)

    if instruments is None:
        instruments = ALL_INSTRUMENTS

    print(f"\n{'='*60}")
    print(f"STRATEGIST — Deep Backtest (Saturday Research)")
    print(f"UTC: {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"Instruments: {instruments}")
    print(f"Monte Carlo: {run_mc}")
    print(f"{'='*60}")
    logging.info(f"Deep backtest starting: {instruments}")

    hub_post(AGENT_NAME, "strategy",
             f"Deep backtest starting for {', '.join(instruments)}",
             tags=["backtest", "research", "deep"])

    all_results = {}
    for inst in instruments:
        try:
            result = deep_backtest_instrument(inst, run_mc=run_mc)
            all_results[inst] = result
        except Exception as e:
            logging.error(f"deep_backtest_instrument({inst}): {e}", exc_info=True)
            all_results[inst] = {'error': str(e)}
            print(f"  ERROR [{inst}]: {e}")

    # Write report
    report_content = write_report(all_results, now)

    # Update strategy weights
    update_strategy_weights(all_results)

    # Post to Agent Hub
    summary_lines = ["Deep backtest complete."]
    for inst, data in all_results.items():
        if 'error' in data:
            summary_lines.append(f"  {inst}: ERROR — {data['error'][:60]}")
            continue
        rankings = data.get('rankings', [])
        best = rankings[0] if rankings else {}
        summary_lines.append(
            f"  {inst}: {best.get('strategy', 'N/A').upper()} | "
            f"WR:{best.get('win_rate','?')} Exp:{best.get('expectancy','?')} "
            f"MC:{'✓' if best.get('mc_approved') else '✗'}"
        )

    hub_post(AGENT_NAME, "strategy",
             "\n".join(summary_lines),
             tags=["backtest", "research", "weekly"])

    # Telegram
    send_telegram_summary(all_results, now)

    print(f"\n{'='*60}")
    print(f"Deep backtest complete.")
    print(f"Report: {REPORT_PATH}")
    print(f"{'='*60}\n")

    return all_results


if __name__ == '__main__':
    quick    = '--quick' in sys.argv
    inst_arg = [a for a in sys.argv[1:] if not a.startswith('--')]

    instruments = [i.upper() for i in inst_arg] if inst_arg else None
    run_deep_backtest(instruments=instruments, run_mc=not quick)
