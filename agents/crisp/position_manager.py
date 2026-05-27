#!/usr/bin/env python3
"""
position_manager.py — Layer 4: Adaptive Position Management

Paper trading only. Simulates two sub-positions per trade:
  pos1 → targets TP1 (partial profit)
  pos2 → targets TP2/TP3 with trailing stop after TP1

All SL/TP levels are structural, not fixed pips.
Breakeven trigger: 0.5x H1 ATR in profit.
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from crisp_config import (
    ACTIVE_POSITION_PATH, TRADE_HISTORY_PATH, DASHBOARD_TRADES,
    PAPER_BALANCE_START, RISK_PER_TRADE_PCT, BE_ATR_MULT,
    MAX_HOLD_HOURS_NORMAL, MAX_HOLD_HOURS_SWING,
    AGENT_NAME, send_telegram, hub_post,
)
from market_data import get_candles_as_dicts, calculate_atr

# ─────────────────────────────────────────────────────────────────────────────
# STATE PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def load_position() -> dict | None:
    """Load active position from disk (for crash recovery)."""
    try:
        with open(ACTIVE_POSITION_PATH) as f:
            pos = json.load(f)
        return pos if pos.get('active') else None
    except Exception:
        return None


def save_position(pos: dict | None):
    """Persist current position state to disk."""
    try:
        with open(ACTIVE_POSITION_PATH, 'w') as f:
            json.dump(pos if pos else {'active': False}, f, indent=2)
    except Exception as e:
        logging.error(f"save_position failed: {e}")


def load_paper_balance() -> float:
    """Load paper balance from trade_history.json."""
    try:
        with open(TRADE_HISTORY_PATH) as f:
            data = json.load(f)
        return data.get('paper_balance', PAPER_BALANCE_START)
    except Exception:
        return PAPER_BALANCE_START


def save_paper_balance(balance: float):
    """Update the paper balance in trade_history.json."""
    try:
        with open(TRADE_HISTORY_PATH) as f:
            data = json.load(f)
        data['paper_balance'] = round(balance, 2)
        with open(TRADE_HISTORY_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"save_paper_balance failed: {e}")


def log_trade_history(trade: dict):
    """Append a closed trade record to trade_history.json."""
    try:
        with open(TRADE_HISTORY_PATH) as f:
            data = json.load(f)
        data.setdefault('trades', []).append(trade)
        with open(TRADE_HISTORY_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"log_trade_history failed: {e}")


def update_dashboard(trade: dict):
    """Append trade to the shared dashboard agent_trades.json."""
    try:
        try:
            with open(DASHBOARD_TRADES) as f:
                data = json.load(f)
        except Exception:
            data = {"trades": []}
        data.setdefault('trades', []).append({
            'agent': AGENT_NAME,
            'trade_id': trade.get('trade_id'),
            'symbol': 'BTC/USDT',
            'direction': trade.get('direction'),
            'entry': trade.get('entry_price'),
            'exit': trade.get('exit_price'),
            'pnl': trade.get('pnl_usd'),
            'result': trade.get('result'),
            'timestamp': trade.get('close_time'),
        })
        with open(DASHBOARD_TRADES, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.warning(f"update_dashboard failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY
# ─────────────────────────────────────────────────────────────────────────────

def open_position(signal: dict, paper_balance: float) -> dict:
    """
    Create a paper position from a signal.

    Position sizing: Risk 1% of balance, position size = risk / SL_distance.
    Split into pos1 (50%) → TP1 and pos2 (50%) → TP2+ with trailing.
    """
    entry  = signal['entry_price']
    sl     = signal['sl_price']
    tps    = signal['tp_targets']
    direction = signal['direction']

    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        logging.error("Cannot open position: SL distance is zero")
        return None

    risk_usd   = paper_balance * RISK_PER_TRADE_PCT
    total_btc  = risk_usd / sl_dist
    btc_half   = total_btc / 2

    pos1_usd   = btc_half * entry
    pos2_usd   = btc_half * entry

    trade_id = str(uuid.uuid4())[:8]

    pos = {
        'active':      True,
        'trade_id':    trade_id,
        'signal_id':   signal['signal_id'],
        'signal_type': signal['type'],
        'direction':   direction,
        'entry_price': entry,
        'open_time':   datetime.now(timezone.utc).isoformat(),
        'open_ts':     time.time(),

        # SL/TP levels
        'sl':          sl,
        'sl_initial':  sl,
        'tp_targets':  tps,

        # Sub-positions
        'pos1': {
            'btc_size':  round(btc_half, 6),
            'usd_value': round(pos1_usd, 2),
            'tp':        tps[0] if tps else None,
            'closed':    False,
            'exit_price': None,
        },
        'pos2': {
            'btc_size':  round(btc_half, 6),
            'usd_value': round(pos2_usd, 2),
            'tp':        tps[1] if len(tps) > 1 else (tps[0] if tps else None),
            'closed':    False,
            'exit_price': None,
            'trailing_sl': None,
            'be_triggered': False,
        },

        # State flags
        'be_triggered':  False,
        'tp1_hit':       False,
        'max_fav_exc':   0.0,
        'max_adv_exc':   0.0,

        # Risk tracking
        'risk_usd':       round(risk_usd, 2),
        'total_btc':      round(total_btc, 6),
        'balance_at_open': paper_balance,

        # Context
        'score':          signal.get('raw_score', 0),
        'factors':        signal.get('factors', {}),
        'context':        signal.get('structure_context', ''),
    }

    save_position(pos)
    logging.info(
        f"OPENED {direction.upper()} @ ${entry:.2f} | "
        f"SL: ${sl:.2f} | TPs: {[f'${t:.0f}' for t in tps]} | "
        f"Size: {total_btc:.6f} BTC | Risk: ${risk_usd:.2f} | "
        f"ID: {trade_id}"
    )
    return pos


# ─────────────────────────────────────────────────────────────────────────────
# POSITION MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def manage_position(pos: dict, current_price: float,
                    paper_balance: float) -> tuple:
    """
    Check position against current price. Returns (updated_pos, updated_balance, events).
    events: list of strings describing what happened.
    If both sub-positions are closed, pos is set inactive.
    """
    if not pos or not pos.get('active'):
        return pos, paper_balance, []

    direction = pos['direction']
    entry     = pos['entry_price']
    sl        = pos['sl']
    events    = []

    # Track excursions
    if direction == 'long':
        fav = current_price - entry
        adv = entry - current_price
    else:
        fav = entry - current_price
        adv = current_price - entry

    pos['max_fav_exc'] = max(pos.get('max_fav_exc', 0), fav)
    pos['max_adv_exc'] = max(pos.get('max_adv_exc', 0), adv)

    # --- Check SL ---
    sl_hit = (direction == 'long' and current_price <= sl) or \
             (direction == 'short' and current_price >= sl)

    if sl_hit:
        pnl = _close_all(pos, sl, paper_balance, 'SL_HIT')
        paper_balance += pnl
        save_paper_balance(paper_balance)
        events.append(f"SL_HIT @ ${sl:.2f} | PnL: ${pnl:.2f}")
        pos['active'] = False
        save_position(pos)
        _record_and_alert(pos, sl, 'SL_HIT', pnl, paper_balance)
        return pos, paper_balance, events

    # --- Check Pos1 TP1 ---
    if not pos['pos1']['closed']:
        tp1 = pos['pos1']['tp']
        tp1_hit = tp1 and (
            (direction == 'long' and current_price >= tp1) or
            (direction == 'short' and current_price <= tp1)
        )
        if tp1_hit:
            p1_pnl = _close_pos1(pos, tp1, paper_balance)
            paper_balance += p1_pnl
            save_paper_balance(paper_balance)
            pos['tp1_hit'] = True
            events.append(f"TP1_HIT @ ${tp1:.2f} | Pos1 PnL: ${p1_pnl:.2f}")
            # Move pos2 SL to breakeven
            pos['pos2']['be_triggered'] = True
            pos['sl'] = pos['entry_price']
            save_position(pos)
            _send_tp1_alert(pos, tp1, p1_pnl, paper_balance)
            logging.info(f"TP1 hit @ ${tp1:.2f} | Pos1 PnL: ${p1_pnl:.2f} | SL → BE")

    # --- Breakeven trigger (before TP1, based on ATR) ---
    if not pos['be_triggered'] and not pos['tp1_hit']:
        atr_h1 = _get_atr_h1_cached()
        be_trigger = atr_h1 * BE_ATR_MULT
        if fav >= be_trigger:
            pos['be_triggered'] = True
            pos['sl'] = pos['entry_price']
            save_position(pos)
            events.append(f"BE_TRIGGERED — SL moved to entry ${entry:.2f}")
            logging.info(f"BE triggered after ${fav:.0f} profit (ATR-based)")

    # --- Check Pos2 TP ---
    if not pos['pos2']['closed'] and pos['tp1_hit']:
        tp2 = pos['pos2']['tp']
        tp2_hit = tp2 and (
            (direction == 'long' and current_price >= tp2) or
            (direction == 'short' and current_price <= tp2)
        )
        if tp2_hit:
            p2_pnl = _close_pos2(pos, tp2, paper_balance)
            paper_balance += p2_pnl
            save_paper_balance(paper_balance)
            events.append(f"TP2_HIT @ ${tp2:.2f} | Pos2 PnL: ${p2_pnl:.2f}")
            pos['active'] = False
            save_position(pos)
            _record_and_alert(pos, tp2, 'TP2_HIT', p2_pnl, paper_balance)
            return pos, paper_balance, events

        # Trailing stop for pos2 (after TP1 hit)
        _update_trailing_stop(pos, current_price)
        trail_sl = pos['pos2'].get('trailing_sl')
        if trail_sl:
            trail_hit = (direction == 'long' and current_price <= trail_sl) or \
                        (direction == 'short' and current_price >= trail_sl)
            if trail_hit:
                p2_pnl = _close_pos2(pos, trail_sl, paper_balance)
                paper_balance += p2_pnl
                save_paper_balance(paper_balance)
                events.append(f"TRAIL_STOP_HIT @ ${trail_sl:.2f} | Pos2 PnL: ${p2_pnl:.2f}")
                pos['active'] = False
                save_position(pos)
                _record_and_alert(pos, trail_sl, 'TRAIL_STOP', p2_pnl, paper_balance)
                return pos, paper_balance, events

    # --- Time stop ---
    hours_open = (time.time() - pos['open_ts']) / 3600
    max_hours  = MAX_HOLD_HOURS_SWING if len(pos['tp_targets']) >= 3 else MAX_HOLD_HOURS_NORMAL
    if hours_open > max_hours:
        pnl = _close_all(pos, current_price, paper_balance, 'TIME_STOP')
        paper_balance += pnl
        save_paper_balance(paper_balance)
        events.append(f"TIME_STOP after {hours_open:.1f}h | PnL: ${pnl:.2f}")
        pos['active'] = False
        save_position(pos)
        _record_and_alert(pos, current_price, 'TIME_STOP', pnl, paper_balance)

    return pos, paper_balance, events


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _close_pos1(pos: dict, exit_price: float, balance: float) -> float:
    p1 = pos['pos1']
    p1['closed'] = True
    p1['exit_price'] = exit_price
    if pos['direction'] == 'long':
        pnl = (exit_price - pos['entry_price']) * p1['btc_size']
    else:
        pnl = (pos['entry_price'] - exit_price) * p1['btc_size']
    p1['pnl'] = round(pnl, 2)
    return round(pnl, 2)


def _close_pos2(pos: dict, exit_price: float, balance: float) -> float:
    p2 = pos['pos2']
    p2['closed'] = True
    p2['exit_price'] = exit_price
    if pos['direction'] == 'long':
        pnl = (exit_price - pos['entry_price']) * p2['btc_size']
    else:
        pnl = (pos['entry_price'] - exit_price) * p2['btc_size']
    p2['pnl'] = round(pnl, 2)
    return round(pnl, 2)


def _close_all(pos: dict, exit_price: float, balance: float,
               reason: str) -> float:
    """Close all unclosed sub-positions at exit_price."""
    total_pnl = 0.0
    if not pos['pos1']['closed']:
        total_pnl += _close_pos1(pos, exit_price, balance)
    if not pos['pos2']['closed']:
        total_pnl += _close_pos2(pos, exit_price, balance)
    pos['close_time'] = datetime.now(timezone.utc).isoformat()
    pos['exit_price'] = exit_price
    pos['result'] = reason
    pos['pnl_usd'] = round(total_pnl, 2)
    pos['pnl_pct'] = round(total_pnl / pos['balance_at_open'] * 100, 3) if pos['balance_at_open'] else 0
    return round(total_pnl, 2)


def _update_trailing_stop(pos: dict, current_price: float):
    """
    Update trailing stop for pos2 based on recent M15 swing structure.
    Only moves in the profitable direction.
    """
    direction = pos['direction']
    try:
        candles = get_candles_as_dicts('15m', limit=20)
        recent_lows  = [c['low'] for c in candles[-5:]]
        recent_highs = [c['high'] for c in candles[-5:]]

        if direction == 'long':
            new_trail = min(recent_lows) * 0.9997
            current_trail = pos['pos2'].get('trailing_sl')
            # Only move trail forward (higher, for longs)
            if current_trail is None or new_trail > current_trail:
                # Only set if trail is below current price
                if new_trail < current_price:
                    pos['pos2']['trailing_sl'] = round(new_trail, 2)
        else:
            new_trail = max(recent_highs) * 1.0003
            current_trail = pos['pos2'].get('trailing_sl')
            if current_trail is None or new_trail < current_trail:
                if new_trail > current_price:
                    pos['pos2']['trailing_sl'] = round(new_trail, 2)
    except Exception as e:
        logging.warning(f"Trail stop update failed: {e}")


_atr_h1_cache = {'value': 0, 'ts': 0}

def _get_atr_h1_cached() -> float:
    if time.time() - _atr_h1_cache['ts'] > 600:
        try:
            from market_data import get_atr_h1
            _atr_h1_cache['value'] = get_atr_h1()
            _atr_h1_cache['ts'] = time.time()
        except Exception:
            pass
    return _atr_h1_cache['value'] or 500  # fallback $500 if ATR unavailable


# ─────────────────────────────────────────────────────────────────────────────
# ALERTS + LOGGING
# ─────────────────────────────────────────────────────────────────────────────

def send_entry_alert(pos: dict):
    direction = pos['direction'].upper()
    entry     = pos['entry_price']
    sl        = pos['sl']
    tps       = pos['tp_targets']
    score     = pos.get('score', 0)
    sig_type  = pos.get('signal_type', '?').replace('_', ' ')
    risk_usd  = pos.get('risk_usd', 0)
    context   = pos.get('context', '')

    tp_lines = ''
    for i, tp in enumerate(tps[:3], 1):
        dist = abs(tp - entry)
        rr   = dist / abs(entry - sl) if abs(entry - sl) > 0 else 0
        tp_lines += f"\nTP{i}: ${tp:,.0f} — ${dist:.0f} ({rr:.1f}R)"

    msg = (
        f"🔵 CRISP v5 — NEW TRADE\n\n"
        f"BTC/USDT {direction} @ ${entry:,.2f}\n"
        f"Score: {score}/100 | {sig_type}\n\n"
        f"{context[:100] if context else ''}\n"
        f"\nSL: ${sl:,.2f} — Risk: ${risk_usd:.2f}"
        f"{tp_lines}\n"
        f"\nID: {pos['trade_id']}"
    )
    send_telegram(msg)
    hub_post(AGENT_NAME, 'trade_open', msg, tags=['crisp_v5', 'trade'])


def _send_tp1_alert(pos: dict, tp1: float, pnl: float, balance: float):
    direction = pos['direction'].upper()
    tp2 = pos['pos2'].get('tp')
    msg = (
        f"✅ CRISP v5 — TP1 HIT\n\n"
        f"BTC/USDT {direction} → TP1 @ ${tp1:,.2f}\n"
        f"Pos1 P&L: +${pnl:.2f} | Balance: ${balance:,.2f}\n\n"
        f"Pos2 active → SL moved to entry\n"
        f"Targeting TP2: ${tp2:,.0f}" if tp2 else ""
    )
    send_telegram(msg)
    hub_post(AGENT_NAME, 'trade_update', msg, tags=['crisp_v5', 'tp1'])


def _record_and_alert(pos: dict, exit_price: float, result: str,
                      pnl: float, balance: float):
    """Log the completed trade and send Telegram alert."""
    pos['close_time'] = pos.get('close_time', datetime.now(timezone.utc).isoformat())
    pos['exit_price'] = exit_price
    pos['result'] = result
    pos['pnl_usd'] = round(pnl, 2)
    pos['pnl_pct'] = round(pnl / pos['balance_at_open'] * 100, 3) if pos['balance_at_open'] else 0

    log_trade_history(pos)
    update_dashboard(pos)

    direction = pos['direction'].upper()
    hold_h = (time.time() - pos['open_ts']) / 3600
    sign = '+' if pnl >= 0 else ''

    icon = '✅' if pnl > 0 else ('⚪' if abs(pnl) < 5 else '🔴')
    msg = (
        f"{icon} CRISP v5 — {result}\n\n"
        f"BTC/USDT {direction} → {result} @ ${exit_price:,.2f}\n"
        f"P&L: {sign}${pnl:.2f} ({sign}{pos['pnl_pct']:.2f}%)\n"
        f"Hold: {hold_h:.1f}h | Balance: ${balance:,.2f}\n"
        f"ID: {pos['trade_id']}"
    )
    send_telegram(msg)
    hub_post(AGENT_NAME, 'trade_close', msg,
             tags=['crisp_v5', result.lower(), 'win' if pnl > 0 else 'loss'])
    logging.info(f"CLOSED {result}: {direction} @ ${exit_price:.2f} | "
                 f"PnL: {sign}${pnl:.2f} | Balance: ${balance:.2f}")
