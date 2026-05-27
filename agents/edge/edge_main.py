#!/usr/bin/env python3
"""
Edge — SMA 8/21 Crossover on 1H

Entry:  8 SMA crosses 21 SMA on 1H candle close.
Filter: Optional 4H trend alignment (USE_H4_FILTER) — longs require H4 bullish,
        shorts require H4 bearish.
Cluster: 3 sub-positions sized at UNITS each (placed as one aggregate market
         order at OANDA; partial-closed per sub-position).
  pos1 → TP +15 pts
  pos2 → TP +25 pts
  pos3 → no fixed TP, trails 21 SMA after pos1 fills
Stops:  All three start at the 21 SMA value at time of entry. When pos1 hits
        TP, pos2 SL moves to BE (entry price) and pos3 begins trailing 21 SMA.
        Pos3 closes when a 1H candle closes below 21 SMA (long) or above (short).
Risk:   Existing daily-drawdown guard + max-loss-count guard preserved.
        First MARKET_OPEN_BLACKOUT_MIN minutes after US cash open is a blackout.
Instr:  SPX500_USD only. Practice account 101-001-22502524-002.
Loop:   5-minute tick; new-signal evaluation only on freshly closed H1 candles.
"""

import sys
import os
import json
import time
import logging
import uuid
import subprocess
import sys
sys.path.insert(0, "/root/.openclaw/scripts")
from telegram_personalities import wrap_message
from datetime import datetime, timezone, timedelta
from statistics import mean

sys.path.insert(0, '/root/.openclaw/scripts')
from hub_post import add_hub_message as hub_post
import session_notify   # legacy import retained for module compatibility

from edge_config import (
    AGENT_NAME, INSTRUMENT,
    GRANULARITY_H1, GRANULARITY_H4, SMA_FAST, SMA_SLOW,
    UNITS, CANDLE_COUNT_H1, CANDLE_COUNT_H4, POLL_INTERVAL_SECS,
    LOG_PATH, TRADE_HISTORY_PATH, DAILY_STATS_PATH,
    PORTFOLIO_PATH, PORTFOLIO_DASH, AGENT_TRADES_PATH, AGENT_PNL_PATH,
    TELEGRAM_UID,
    MAX_DAILY_LOSSES, MAX_DAILY_LOSS_PCT, MAX_HOLD_MINUTES,
    USE_H4_FILTER, TP1_PTS, TP2_PTS,
    MARKET_OPEN_UTC, MARKET_OPEN_BLACKOUT_MIN,
)
from edge_oanda import (
    fetch_candles, calculate_sma, get_smas, detect_cross,
    get_account_balance, place_market_order,
    close_position, close_position_units,
)

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
logging.getLogger('oandapyV20').setLevel(logging.CRITICAL)

# ─────────────────────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────────────────────

# Active position cluster (None when flat). Shape:
# {
#   'direction':   'long' | 'short',
#   'entry_price': float,
#   'entry_time':  iso str,
#   'entry_sma21': float,
#   'h4_trend':    'bullish' | 'bearish' | 'flat' | 'unknown' | 'skipped',
#   'be_moved':    bool,
#   'session':     str,
#   'positions': {
#       'pos1': {'units': N, 'tp': float, 'sl': float, 'status': 'open'|'closed',
#                'trailing': False},
#       'pos2': {'units': N, 'tp': float, 'sl': float, 'status': 'open'|'closed',
#                'trailing': False},
#       'pos3': {'units': N, 'tp': None,  'sl': float, 'status': 'open'|'closed',
#                'trailing': False},
#   },
# }
cluster = None

daily_stats = {
    'date':           '',
    'trades':         0,
    'wins':           0,
    'losses':         0,
    'daily_pnl':      0.0,
    'last_loss_time': None,
}

# Daily drawdown trigger time (HH:MM UTC) — set when MAX_DAILY_LOSS_PCT first breached
_daily_drawdown_time = None
_daily_drawdown_date = None

# Last H1 candle we evaluated (used to detect "new H1 candle closed since last tick")
_last_h1_candle_time = None

_last_summary_date = None

# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATION HELPERS (unchanged — owned by the notification system)
# ─────────────────────────────────────────────────────────────────────────────

def send_telegram(msg):
    subprocess.run([
        'openclaw', 'message', 'send',
        '--channel', 'telegram', '--target', TELEGRAM_UID, '--message', msg
    ])


# ─────────────────────────────────────────────────────────────────────────────
# PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def load_daily_stats():
    global daily_stats
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        with open(DAILY_STATS_PATH) as f:
            d = json.load(f)
        if d.get('date') == today:
            daily_stats = d
            return
    except Exception:
        pass
    daily_stats = {
        'date':           today,
        'trades':         0,
        'wins':           0,
        'losses':         0,
        'daily_pnl':      0.0,
        'last_loss_time': None,
    }
    save_daily_stats()


def save_daily_stats():
    with open(DAILY_STATS_PATH, 'w') as f:
        json.dump(daily_stats, f, indent=2)


def load_trade_history():
    try:
        with open(TRADE_HISTORY_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def save_trade(trade):
    history = load_trade_history()
    history.append(trade)
    with open(TRADE_HISTORY_PATH, 'w') as f:
        json.dump(history, f, indent=2)
    _append_to_agent_trades(trade)


def _append_to_agent_trades(trade):
    """Sync closed trade to the shared dashboard agent_trades.json."""
    try:
        try:
            with open(AGENT_TRADES_PATH) as f:
                data = json.load(f)
        except Exception:
            data = {'trades': []}

        if 'trades' not in data:
            data['trades'] = []

        data['trades'].append({
            'id':         trade.get('trade_id', str(uuid.uuid4())),
            'agent':      AGENT_NAME,
            'date':       (trade.get('entry_time') or '')[:10],
            'timestamp':  trade.get('exit_time', ''),
            'session':    trade.get('session', ''),
            'pair':       INSTRUMENT,
            'symbol':     INSTRUMENT,
            'direction':  trade.get('direction', ''),
            'setup':      '1H SMA 8/21 crossover',
            'entry':      trade.get('entry_price', 0),
            'stop':       trade.get('exit_sma21', 0),
            'tp1':        0,
            'result':     trade.get('result', ''),
            'pnl_usd':    round(trade.get('pnl', 0), 2),
            'r_multiple': 0,
            'notes':      trade.get('exit_reason', ''),
        })

        with open(AGENT_TRADES_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"_append_to_agent_trades: {e}")


def update_agent_pnl():
    """Refresh agent_pnl.json with current Edge stats."""
    try:
        try:
            with open(AGENT_PNL_PATH) as f:
                data = json.load(f)
        except Exception:
            data = {}

        history = load_trade_history()
        wins    = sum(1 for t in history if t.get('pnl', 0) > 0)
        losses  = sum(1 for t in history if t.get('pnl', 0) < 0)
        total   = len(history)
        graded  = wins + losses  # exclude BE from win-rate denominator
        total_pnl = sum(t.get('pnl', 0) for t in history)
        best    = max((t.get('pnl', 0) for t in history), default=0)
        wr      = round(wins / graded * 100, 1) if graded else 0

        balance = get_account_balance()
        data['edge'] = {
            'pnl':      round(total_pnl, 2),
            'trades':   total,
            'wr':       wr,
            'best':     round(best, 2),
            'sessions': daily_stats.get('trades', 0),
            'balance':  balance,
        }
        data['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        with open(AGENT_PNL_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"update_agent_pnl: {e}")


def update_portfolio_json():
    """Write edge_portfolio.json for dashboard consumption."""
    try:
        history  = load_trade_history()
        balance  = get_account_balance() or 5000.0
        total_pnl = sum(t.get('pnl', 0) for t in history)
        wins     = sum(1 for t in history if t.get('pnl', 0) > 0)
        losses   = sum(1 for t in history if t.get('pnl', 0) < 0)
        total    = len(history)
        graded   = wins + losses
        breakeven = total - graded
        wr       = round(wins / graded * 100, 1) if graded else 0
        recent   = sorted(history, key=lambda t: t.get('exit_time', ''), reverse=True)[:5]

        data = {
            'updated':    datetime.now(timezone.utc).isoformat(),
            'balance':    round(balance, 2),
            'total_pnl':  round(total_pnl, 2),
            'trades':     total,
            'wins':       wins,
            'losses':     losses,
            'breakeven':  breakeven,
            'win_rate':   wr,
            'daily_pnl':  round(daily_stats.get('daily_pnl', 0), 2),
            'recent':     recent,
            'position':   cluster,
        }
        for path in (PORTFOLIO_PATH, PORTFOLIO_DASH):
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"update_portfolio_json: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# RISK MANAGEMENT (preserved guard + market-open blackout)
# ─────────────────────────────────────────────────────────────────────────────

def check_daily_limits(balance):
    """Return (ok, reason). Halts on max-loss-count or daily-drawdown breaches."""
    global _daily_drawdown_time, _daily_drawdown_date
    losses = daily_stats.get('losses', 0)
    if losses >= MAX_DAILY_LOSSES:
        return False, f"Max daily losses reached ({losses})"
    if balance and balance > 0:
        drawdown_pct = abs(min(daily_stats['daily_pnl'], 0)) / balance * 100
        if drawdown_pct >= MAX_DAILY_LOSS_PCT:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            if _daily_drawdown_date != today:
                _daily_drawdown_time = datetime.now(timezone.utc).strftime('%H:%M')
                _daily_drawdown_date = today
            return False, f"Daily drawdown limit hit ({drawdown_pct:.1f}%)"
    return True, ''


def in_market_open_blackout(now_utc):
    """Within MARKET_OPEN_BLACKOUT_MIN minutes after US cash open (13:30 UTC during DST)."""
    open_h, open_m = MARKET_OPEN_UTC
    open_dt = now_utc.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    end_dt  = open_dt + timedelta(minutes=MARKET_OPEN_BLACKOUT_MIN)
    return open_dt <= now_utc < end_dt


# ─────────────────────────────────────────────────────────────────────────────
# H4 TREND FILTER
# ─────────────────────────────────────────────────────────────────────────────

def get_h4_trend(h4_candles):
    """Return 'bullish' if H4 SMA8 > SMA21, 'bearish' if <, 'flat' if equal, 'unknown' if insufficient data."""
    if not h4_candles or len(h4_candles) < SMA_SLOW + 1:
        return 'unknown'
    sma_fast = calculate_sma(h4_candles, SMA_FAST)
    sma_slow = calculate_sma(h4_candles, SMA_SLOW)
    if sma_fast is None or sma_slow is None:
        return 'unknown'
    if sma_fast > sma_slow:
        return 'bullish'
    if sma_fast < sma_slow:
        return 'bearish'
    return 'flat'


# ─────────────────────────────────────────────────────────────────────────────
# CLUSTER MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def open_cluster(direction, signal_price, sma21, h4_trend):
    """Open a 3-position cluster via one OANDA market order (3 × UNITS aggregate)."""
    global cluster

    total_units = 3 * UNITS
    trade_id, fill_price = place_market_order(direction, total_units)
    if not trade_id:
        logging.error(f"OPEN CLUSTER FAILED: order rejected ({direction} {total_units}u)")
        return None

    entry = fill_price if fill_price else signal_price

    if direction == 'long':
        tp1 = entry + TP1_PTS
        tp2 = entry + TP2_PTS
    else:
        tp1 = entry - TP1_PTS
        tp2 = entry - TP2_PTS

    positions = {
        'pos1': {'units': UNITS, 'tp': tp1, 'sl': sma21, 'status': 'open', 'trailing': False},
        'pos2': {'units': UNITS, 'tp': tp2, 'sl': sma21, 'status': 'open', 'trailing': False},
        'pos3': {'units': UNITS, 'tp': None, 'sl': sma21, 'status': 'open', 'trailing': False},
    }

    cluster = {
        'direction':   direction,
        'entry_price': entry,
        'entry_time':  datetime.now(timezone.utc).isoformat(),
        'entry_sma21': sma21,
        'h4_trend':    h4_trend,
        'be_moved':    False,
        'session':     'ALL_HRS',
        'positions':   positions,
    }

    dir_word = 'LONG' if direction == 'long' else 'SHORT'
    sym      = INSTRUMENT.split('_')[0]
    logging.info(
        f"OPEN CLUSTER: {dir_word} {sym} @ {entry:.2f} | "
        f"SL={sma21:.2f} | TP1={tp1:.2f} TP2={tp2:.2f} | H4={h4_trend}"
    )
    print(f"\n  🟢 EDGE-H1 {dir_word} {sym} @ {entry:.2f} | "
          f"SL {sma21:.2f} | TPs {tp1:.2f}/{tp2:.2f}/TRAIL | H4 {h4_trend}")
    hub_post(AGENT_NAME, "trade",
             f"EDGE-H1 {dir_word} {sym} @ {entry:.2f}",
             tags=["trading", "entry", "h1"])
    update_portfolio_json()
    return cluster


def _record_close(pos_key, sub, exit_price_hint, exit_reason):
    """Partial-close a sub-position at OANDA, persist the trade, update daily stats."""
    global daily_stats
    direction = cluster['direction']
    entry     = cluster['entry_price']
    units     = sub['units']

    fill_price, oanda_pnl = close_position_units(direction, units)
    actual_exit = fill_price if fill_price else exit_price_hint

    if oanda_pnl is not None and abs(oanda_pnl) > 0:
        pnl = oanda_pnl
    else:
        if direction == 'long':
            pnl = (actual_exit - entry) * units
        else:
            pnl = (entry - actual_exit) * units

    hold_minutes = int((
        datetime.now(timezone.utc) -
        datetime.fromisoformat(cluster['entry_time'])
    ).total_seconds() / 60)

    trade = {
        'trade_id':     str(uuid.uuid4()),
        'direction':    direction,
        'entry_price':  entry,
        'entry_time':   cluster['entry_time'],
        'exit_price':   actual_exit,
        'exit_time':    datetime.now(timezone.utc).isoformat(),
        'exit_reason':  exit_reason,
        'exit_sma21':   sub.get('sl', 0),
        'hold_minutes': hold_minutes,
        'units':        units,
        'pnl':          round(pnl, 2),
        'result':       'W' if pnl > 0 else ('L' if pnl < 0 else 'BE'),
        'session':      cluster.get('session', ''),
        'pos_key':      pos_key,
        'setup':        '1H SMA 8/21 crossover',
        'h4_trend':     cluster.get('h4_trend', ''),
    }

    daily_stats['trades']    += 1
    daily_stats['daily_pnl'] += pnl
    if pnl > 0:
        daily_stats['wins'] += 1
    elif pnl < 0:
        daily_stats['losses'] += 1
        daily_stats['last_loss_time'] = datetime.now(timezone.utc).isoformat()
    save_daily_stats()

    save_trade(trade)
    update_agent_pnl()

    sub['status']   = 'closed'
    sub['exit']     = actual_exit
    sub['exit_pnl'] = round(pnl, 2)

    sign = '+' if pnl >= 0 else '-'
    icon = '✅' if pnl > 0 else ('❌' if pnl < 0 else '⚪')
    logging.info(
        f"CLOSE {pos_key}: {direction} @ {actual_exit:.2f} | "
        f"PnL ${pnl:.2f} | hold {hold_minutes}min | {exit_reason}"
    )
    print(f"  {icon} {pos_key} CLOSE @ {actual_exit:.2f} | {sign}${abs(pnl):.2f} | {exit_reason}")
    return trade


def _move_remaining_to_be():
    """After pos1 TP: pos2 SL → entry; pos3 flips to trailing mode."""
    if not cluster:
        return
    entry = cluster['entry_price']
    cluster['be_moved'] = True
    p2 = cluster['positions']['pos2']
    if p2['status'] == 'open':
        p2['sl'] = entry
        logging.info(f"BE MOVE: pos2 SL → {entry:.2f}")
    p3 = cluster['positions']['pos3']
    if p3['status'] == 'open':
        p3['trailing'] = True
        logging.info(f"TRAIL ARM: pos3 begins trailing 21 SMA")


def _clear_cluster_if_empty():
    """If all sub-positions are closed, reset cluster and ensure OANDA is flat."""
    global cluster
    if not cluster:
        return
    if all(p['status'] == 'closed' for p in cluster['positions'].values()):
        # Belt-and-suspenders: close any residual aggregate position.
        close_position(INSTRUMENT, cluster['direction'])
        total_pnl = sum(p.get('exit_pnl', 0) for p in cluster['positions'].values())
        logging.info(f"CLUSTER CLOSED: aggregate P&L ${total_pnl:.2f}")
        cluster = None
        update_portfolio_json()


def manage_cluster(price, sma21_curr, h1_just_closed):
    """Per-tick management: TPs, SLs, trailing stop on pos3, max-hold safety net."""
    if not cluster:
        return

    direction = cluster['direction']
    positions = cluster['positions']

    # ── pos1: fixed TP1 / hard SL ─────────────────────────────────────────────
    p1 = positions['pos1']
    if p1['status'] == 'open':
        if direction == 'long':
            tp_hit = price >= p1['tp']
            sl_hit = price <= p1['sl']
        else:
            tp_hit = price <= p1['tp']
            sl_hit = price >= p1['sl']
        if tp_hit:
            _record_close('pos1', p1, p1['tp'], 'TP1 hit')
            _move_remaining_to_be()
        elif sl_hit:
            _record_close('pos1', p1, p1['sl'], 'SL hit (21 SMA at entry)')

    # ── pos2: fixed TP2; SL either entry-SMA21 or BE depending on be_moved ───
    p2 = positions['pos2']
    if p2['status'] == 'open':
        if direction == 'long':
            tp_hit = price >= p2['tp']
            sl_hit = price <= p2['sl']
        else:
            tp_hit = price <= p2['tp']
            sl_hit = price >= p2['sl']
        if tp_hit:
            _record_close('pos2', p2, p2['tp'], 'TP2 hit')
        elif sl_hit:
            reason = 'BE stop' if cluster.get('be_moved') else 'SL hit (21 SMA at entry)'
            _record_close('pos2', p2, p2['sl'], reason)

    # ── pos3: trail 21 SMA only after BE is set; before BE use hard SL ───────
    p3 = positions['pos3']
    if p3['status'] == 'open':
        if not p3.get('trailing'):
            # Pre-BE — same hard SL as pos1/pos2 at the entry SMA21
            if direction == 'long':
                sl_hit = price <= p3['sl']
            else:
                sl_hit = price >= p3['sl']
            if sl_hit:
                _record_close('pos3', p3, p3['sl'], 'SL hit (21 SMA at entry)')
        else:
            # Trailing — only act when a fresh H1 candle has just closed
            if h1_just_closed:
                exit_long  = direction == 'long'  and price < sma21_curr
                exit_short = direction == 'short' and price > sma21_curr
                if exit_long or exit_short:
                    _record_close('pos3', p3, price,
                                  f'1H close beyond 21 SMA ({sma21_curr:.2f})')
                else:
                    p3['sl'] = sma21_curr
                    logging.info(f"TRAIL: pos3 SL → {sma21_curr:.2f}")

    # ── Max-hold safety net (preserved guard) ────────────────────────────────
    if cluster and any(p['status'] == 'open' for p in cluster['positions'].values()):
        opened_at = datetime.fromisoformat(cluster['entry_time'])
        hold_mins = (datetime.now(timezone.utc) - opened_at).total_seconds() / 60
        if hold_mins >= MAX_HOLD_MINUTES:
            logging.info(f"MAX HOLD {MAX_HOLD_MINUTES}min reached — force-closing cluster")
            for k, p in cluster['positions'].items():
                if p['status'] == 'open':
                    _record_close(k, p, price, f'Max hold ({MAX_HOLD_MINUTES}min)')

    _clear_cluster_if_empty()


# ─────────────────────────────────────────────────────────────────────────────
# DAILY WRAP (notification system — unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def maybe_send_daily_summary():
    """Send the EDGE daily wrap at 23:00 UTC."""
    global _last_summary_date
    now = datetime.now(timezone.utc)
    today = now.strftime('%Y-%m-%d')
    if now.hour == 23 and now.minute < 5 and _last_summary_date != today:
        _last_summary_date = today
        _send_daily_summary(today)


def _send_daily_summary(date_str):
    history    = load_trade_history()
    today_ts   = [t for t in history if (t.get('exit_time') or '')[:10] == date_str]
    sym        = INSTRUMENT.split('_')[0]
    balance    = get_account_balance() or 0
    daily_pnl  = sum(t.get('pnl', 0) for t in today_ts)
    total      = len(today_ts)
    wins       = sum(1 for t in today_ts if t.get('pnl', 0) > 0)
    losses     = sum(1 for t in today_ts if t.get('pnl', 0) < 0)
    breakeven  = total - wins - losses

    lines = [
        f"📊 EDGE — DAILY WRAP",
        f"Date: {date_str}",
        "",
        "Trades taken:",
    ]

    if today_ts:
        for t in today_ts:
            direction = (t.get('direction') or '?').upper()
            pnl       = t.get('pnl', 0) or 0
            result    = t.get('result', '')
            if result == 'W' or (result not in ('BE',) and pnl > 0):
                outcome = "TP1 ✅ TP2 ✅ TP3 ✅"
            elif result == 'BE' or pnl == 0:
                outcome = "BE 🔁"
            else:
                outcome = "SL ❌"
            if pnl > 0:
                pnl_str = f"+${pnl:.2f}"
            elif pnl < 0:
                pnl_str = f"-${abs(pnl):.2f}"
            else:
                pnl_str = "$0"
            lines.append(f"- {sym} {direction} → {outcome} | {pnl_str}")
    else:
        lines.append("- (none)")

    if daily_pnl > 0:
        dpnl = f"+${daily_pnl:.2f}"
    elif daily_pnl < 0:
        dpnl = f"-${abs(daily_pnl):.2f}"
    else:
        dpnl = "$0"

    lines += [
        "",
        f"Daily P&L: {dpnl}",
        f"Running balance: ${balance:,.2f}",
        f"Total trades today: {total} | Win: {wins} Loss: {losses} BE: {breakeven}",
    ]

    if _daily_drawdown_date == date_str and _daily_drawdown_time:
        lines.append(
            f"⚠️ Daily drawdown limit hit at {_daily_drawdown_time} UTC "
            f"— trading paused for the day."
        )

    logging.info(f"DAILY WRAP: {total} trades | P&L:${daily_pnl:.2f}")
    send_telegram(wrap_message('edge', '\n'.join(lines)))


# ─────────────────────────────────────────────────────────────────────────────
# 5-MINUTE POLL
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_next_tick():
    """Sleep until ~2s past the next POLL_INTERVAL_SECS boundary."""
    now        = time.time()
    next_tick  = (int(now / POLL_INTERVAL_SECS) + 1) * POLL_INTERVAL_SECS
    sleep_secs = (next_tick + 2) - now
    time.sleep(max(sleep_secs, 1))


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def run():
    global cluster, daily_stats, _last_h1_candle_time

    logging.info("=" * 60)
    logging.info(f"EDGE — H1 SMA {SMA_FAST}/{SMA_SLOW} crossover "
                 f"(H4 filter: {USE_H4_FILTER})")
    logging.info(f"Instrument: {INSTRUMENT} | Units/pos: {UNITS} "
                 f"| Account: 101-001-22502524-002")
    logging.info("=" * 60)
    print(f"\nEDGE starting — H1 SMA {SMA_FAST}/{SMA_SLOW} crossover "
          f"| H4 filter: {USE_H4_FILTER}")

    load_daily_stats()
    hub_post(AGENT_NAME, "status",
             f"EDGE H1 {SMA_FAST}/{SMA_SLOW} bot started (H4 filter: {USE_H4_FILTER})",
             tags=["startup"])

    while True:
        try:
            wait_for_next_tick()
            now_utc = datetime.now(timezone.utc)
            today   = now_utc.strftime('%Y-%m-%d')

            if daily_stats.get('date') != today:
                load_daily_stats()

            maybe_send_daily_summary()

            # ── Fetch candles ────────────────────────────────────────────────
            h1 = fetch_candles(INSTRUMENT, GRANULARITY_H1, CANDLE_COUNT_H1)
            if len(h1) < SMA_SLOW + 2:
                logging.warning(f"Insufficient H1 candles ({len(h1)}) — skip tick")
                continue

            h4 = fetch_candles(INSTRUMENT, GRANULARITY_H4, CANDLE_COUNT_H4) \
                 if USE_H4_FILTER else []

            smas = get_smas(h1)
            if not smas:
                continue
            sma8_prev, sma8_curr, sma21_prev, sma21_curr = smas

            price          = h1[-1]['close']
            balance        = get_account_balance() or 5000.0
            h1_latest_time = h1[-1].get('time', '')
            h1_just_closed = (
                _last_h1_candle_time is not None
                and h1_latest_time != _last_h1_candle_time
            )

            print(f"  [{now_utc.strftime('%H:%M')}] {INSTRUMENT} close={price:.1f} "
                  f"SMA8={sma8_curr:.1f} SMA21={sma21_curr:.1f} "
                  f"state={'cluster-' + cluster['direction'] if cluster else 'flat'}")

            # ── Risk guard (preserved) ───────────────────────────────────────
            ok, reason = check_daily_limits(balance)
            if not ok:
                if cluster:
                    logging.warning(f"Daily limit hit — force-closing cluster: {reason}")
                    for k, p in cluster['positions'].items():
                        if p['status'] == 'open':
                            _record_close(k, p, price, f"Daily limit: {reason}")
                    _clear_cluster_if_empty()
                else:
                    logging.info(f"Daily limit — no new trades: {reason}")
                _last_h1_candle_time = h1_latest_time
                continue

            # ── If cluster is open, manage only (no new entries) ─────────────
            if cluster:
                manage_cluster(price, sma21_curr, h1_just_closed)
                _last_h1_candle_time = h1_latest_time
                continue

            # ── Flat: only evaluate signals on a freshly closed H1 candle ───
            if _last_h1_candle_time is None:
                # First observation after startup: record baseline, don't replay.
                _last_h1_candle_time = h1_latest_time
                logging.info(f"INIT: H1 baseline set to {h1_latest_time}")
                continue

            if not h1_just_closed:
                continue

            _last_h1_candle_time = h1_latest_time

            if in_market_open_blackout(now_utc):
                logging.info(
                    f"SIGNAL SKIPPED: market-open blackout "
                    f"(within {MARKET_OPEN_BLACKOUT_MIN}m of US open) | "
                    f"h1_close={h1_latest_time}"
                )
                continue

            bull, bear = detect_cross(sma8_prev, sma8_curr, sma21_prev, sma21_curr)
            if not (bull or bear):
                logging.info(
                    f"NO SIGNAL: h1_close={h1_latest_time} "
                    f"SMA8 {sma8_prev:.2f}->{sma8_curr:.2f} | "
                    f"SMA21 {sma21_prev:.2f}->{sma21_curr:.2f}"
                )
                continue

            direction = 'long' if bull else 'short'

            # ── 4H trend filter (optional) ───────────────────────────────────
            h4_trend = 'skipped'
            if USE_H4_FILTER:
                h4_trend = get_h4_trend(h4)
                aligned  = (
                    (direction == 'long'  and h4_trend == 'bullish') or
                    (direction == 'short' and h4_trend == 'bearish')
                )
                if not aligned:
                    logging.info(
                        f"SIGNAL SKIPPED ({direction}): H4 trend={h4_trend} | "
                        f"H1 SMA8={sma8_curr:.2f} SMA21={sma21_curr:.2f} | "
                        f"h1_close={h1_latest_time}"
                    )
                    continue

            logging.info(
                f"SIGNAL FIRED: {direction} | h1_close={h1_latest_time} | "
                f"H1 SMA8={sma8_curr:.2f} SMA21={sma21_curr:.2f} | "
                f"H4={h4_trend} | price={price:.2f}"
            )
            open_cluster(direction, price, sma21_curr, h4_trend)

        except KeyboardInterrupt:
            logging.info("EDGE stopped by user")
            print("\nEDGE stopped.")
            if cluster:
                h1 = fetch_candles(INSTRUMENT, GRANULARITY_H1, CANDLE_COUNT_H1)
                price_now = h1[-1]['close'] if h1 else 0
                for k, p in cluster['positions'].items():
                    if p['status'] == 'open':
                        _record_close(k, p, price_now, "Manual stop")
            break

        except Exception as e:
            logging.error(f"Main loop error: {type(e).__name__}: {e}", exc_info=True)
            print(f"  ERROR: {e}")
            time.sleep(5)


if __name__ == '__main__':
    run()
